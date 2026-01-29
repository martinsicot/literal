"""Anki deck importer service."""

import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from literal.models.user import UserWordState
from literal.models.word import Word


@dataclass
class AnkiNote:
    """Parsed note from Anki deck."""

    note_id: int
    fields: list[str]
    tags: list[str]


@dataclass
class AnkiReviewLog:
    """Review log entry from Anki."""

    card_id: int
    timestamp: datetime
    ease: int  # 1=Again, 2=Hard, 3=Good, 4=Easy
    interval: int  # New interval in days (or negative for learning)
    type: int  # 0=learning, 1=review, 2=relearning, 3=filtered


@dataclass
class ImportResult:
    """Result of an import operation."""

    words_imported: int
    words_updated: int
    words_skipped: int
    reviews_imported: int
    errors: list[str]


class AnkiImporter:
    """
    Import vocabulary from Anki .apkg files.

    Handles:
    - Extracting and parsing .apkg (SQLite in ZIP)
    - Parsing notes table for vocabulary
    - Parsing revlog for review history
    - Calculating SM-2 state from history
    """

    # Anki ease to SM-2 quality mapping
    EASE_TO_QUALITY = {
        1: 0,  # Again -> 0
        2: 2,  # Hard -> 2
        3: 3,  # Good -> 3
        4: 5,  # Easy -> 5
    }

    def __init__(
        self,
        session: AsyncSession,
        field_mapping: dict[str, int] | None = None,
    ):
        """
        Initialize importer.

        Args:
            session: Database session
            field_mapping: Mapping of field names to positions in note fields
                          Default: {"word": 0, "translation": 1}
        """
        self.session = session
        self.field_mapping = field_mapping or {"word": 0, "translation": 1}

    def extract_apkg(self, apkg_path: Path) -> Path:
        """
        Extract .apkg file to temporary directory.

        Args:
            apkg_path: Path to .apkg file

        Returns:
            Path to extracted collection.anki2 database
        """
        temp_dir = tempfile.mkdtemp(prefix="literal_anki_")
        with zipfile.ZipFile(apkg_path, "r") as zip_ref:
            zip_ref.extractall(temp_dir)

        # Find the database file
        db_path = Path(temp_dir) / "collection.anki2"
        if not db_path.exists():
            # Try alternative name
            db_path = Path(temp_dir) / "collection.anki21"

        if not db_path.exists():
            raise FileNotFoundError(
                f"Could not find Anki database in {apkg_path}"
            )

        return db_path

    def parse_notes(self, db_path: Path) -> list[AnkiNote]:
        """
        Parse notes from Anki database.

        Args:
            db_path: Path to extracted database

        Returns:
            List of parsed AnkiNote objects
        """
        notes = []
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Query notes table
        # flds contains fields separated by \x1f
        cursor.execute("SELECT id, flds, tags FROM notes")

        for row in cursor.fetchall():
            note_id, fields_str, tags_str = row
            fields = fields_str.split("\x1f") if fields_str else []
            tags = tags_str.strip().split(" ") if tags_str else []

            notes.append(AnkiNote(
                note_id=note_id,
                fields=fields,
                tags=tags,
            ))

        conn.close()
        return notes

    def parse_review_logs(self, db_path: Path) -> dict[int, list[AnkiReviewLog]]:
        """
        Parse review logs from Anki database.

        Args:
            db_path: Path to extracted database

        Returns:
            Dict mapping card_id to list of review logs
        """
        reviews: dict[int, list[AnkiReviewLog]] = {}
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Query revlog table
        # id is timestamp in milliseconds, ease is button pressed
        cursor.execute("""
            SELECT cid, id, ease, ivl, type
            FROM revlog
            ORDER BY id
        """)

        for row in cursor.fetchall():
            card_id, timestamp_ms, ease, interval, review_type = row

            review = AnkiReviewLog(
                card_id=card_id,
                timestamp=datetime.fromtimestamp(timestamp_ms / 1000),
                ease=ease,
                interval=interval,
                type=review_type,
            )

            if card_id not in reviews:
                reviews[card_id] = []
            reviews[card_id].append(review)

        conn.close()
        return reviews

    def get_card_to_note_mapping(self, db_path: Path) -> dict[int, int]:
        """Get mapping from card IDs to note IDs."""
        mapping = {}
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT id, nid FROM cards")
        for card_id, note_id in cursor.fetchall():
            mapping[card_id] = note_id

        conn.close()
        return mapping

    def calculate_sm2_from_history(
        self,
        reviews: list[AnkiReviewLog],
    ) -> tuple[int, float, int, date | None]:
        """
        Calculate SM-2 state from review history.

        Args:
            reviews: List of review logs sorted by time

        Returns:
            Tuple of (repetitions, ease_factor, interval, next_review)
        """
        if not reviews:
            return (0, 2.5, 0, None)

        repetitions = 0
        ease_factor = 2.5
        interval = 0

        for review in reviews:
            quality = self.EASE_TO_QUALITY.get(review.ease, 3)

            if quality >= 3:
                # Successful review
                if repetitions == 0:
                    interval = 1
                elif repetitions == 1:
                    interval = 6
                else:
                    interval = round(interval * ease_factor)
                repetitions += 1
            else:
                # Failed review - reset
                repetitions = 0
                interval = 1

            # Update ease factor
            ease_factor = ease_factor + (
                0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
            )
            ease_factor = max(1.3, ease_factor)

        # Calculate next review from last review
        last_review = reviews[-1].timestamp.date()
        next_review = last_review + timedelta(days=interval)

        return (repetitions, round(ease_factor, 2), interval, next_review)

    async def import_deck(
        self,
        apkg_path: Path,
        user_id: int,
        language: str = "eu",
        import_reviews: bool = True,
    ) -> ImportResult:
        """
        Import an Anki deck.

        Args:
            apkg_path: Path to .apkg file
            user_id: User to import for
            language: Language code for imported words
            import_reviews: Whether to import review history

        Returns:
            ImportResult with statistics
        """
        result = ImportResult(
            words_imported=0,
            words_updated=0,
            words_skipped=0,
            reviews_imported=0,
            errors=[],
        )

        try:
            # Extract and parse
            db_path = self.extract_apkg(apkg_path)
            notes = self.parse_notes(db_path)

            if import_reviews:
                review_logs = self.parse_review_logs(db_path)
                card_to_note = self.get_card_to_note_mapping(db_path)
            else:
                review_logs = {}
                card_to_note = {}

            # Group reviews by note_id
            note_reviews: dict[int, list[AnkiReviewLog]] = {}
            for card_id, reviews in review_logs.items():
                note_id = card_to_note.get(card_id)
                if note_id:
                    if note_id not in note_reviews:
                        note_reviews[note_id] = []
                    note_reviews[note_id].extend(reviews)

            # Sort reviews by time for each note
            for note_id in note_reviews:
                note_reviews[note_id].sort(key=lambda r: r.timestamp)

            # Process each note
            for note in notes:
                try:
                    await self._process_note(
                        note=note,
                        user_id=user_id,
                        language=language,
                        reviews=note_reviews.get(note.note_id, []),
                        result=result,
                    )
                except Exception as e:
                    result.errors.append(f"Note {note.note_id}: {str(e)}")

            await self.session.flush()

        except Exception as e:
            result.errors.append(f"Import error: {str(e)}")

        return result

    async def _process_note(
        self,
        note: AnkiNote,
        user_id: int,
        language: str,
        reviews: list[AnkiReviewLog],
        result: ImportResult,
    ) -> None:
        """Process a single note."""
        # Extract word and translation from fields
        word_idx = self.field_mapping.get("word", 0)
        trans_idx = self.field_mapping.get("translation", 1)

        if len(note.fields) <= word_idx:
            result.words_skipped += 1
            return

        word_text = note.fields[word_idx].strip()
        if not word_text:
            result.words_skipped += 1
            return

        # Clean HTML tags if present
        word_text = self._strip_html(word_text)

        translation = None
        if len(note.fields) > trans_idx:
            translation = self._strip_html(note.fields[trans_idx].strip())

        # Check if word already exists
        existing = await self.session.execute(
            select(Word).where(
                Word.anki_note_id == note.note_id,
            )
        )
        word = existing.scalar_one_or_none()

        if word:
            # Update existing word
            word.word = word_text
            word.translation = translation
            result.words_updated += 1
        else:
            # Check by word text
            existing = await self.session.execute(
                select(Word).where(
                    Word.word == word_text,
                    Word.language == language,
                )
            )
            word = existing.scalar_one_or_none()

            if word:
                word.anki_note_id = note.note_id
                word.translation = translation or word.translation
                result.words_updated += 1
            else:
                # Create new word
                word = Word(
                    word=word_text,
                    language=language,
                    translation=translation,
                    anki_note_id=note.note_id,
                )
                self.session.add(word)
                result.words_imported += 1

        await self.session.flush()

        # Process review history
        if reviews:
            repetitions, ease_factor, interval, next_review = \
                self.calculate_sm2_from_history(reviews)

            # Get or create user word state
            state_result = await self.session.execute(
                select(UserWordState).where(
                    UserWordState.user_id == user_id,
                    UserWordState.word_id == word.id,
                )
            )
            state = state_result.scalar_one_or_none()

            if state is None:
                state = UserWordState(
                    user_id=user_id,
                    word_id=word.id,
                )
                self.session.add(state)

            state.repetitions = repetitions
            state.ease_factor = ease_factor
            state.interval = interval
            state.next_review = next_review
            state.total_reviews = len(reviews)
            state.successful_reviews = sum(
                1 for r in reviews if r.ease >= 3
            )
            if reviews:
                state.last_review = reviews[-1].timestamp
            state.update_mastery_level()

            result.reviews_imported += len(reviews)

    def _strip_html(self, text: str) -> str:
        """Remove HTML tags from text."""
        import re
        clean = re.sub(r"<[^>]+>", "", text)
        return clean.strip()
