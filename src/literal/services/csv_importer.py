"""CSV importer service for French→Basque vocabulary."""

import csv
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from literal.models import User, UserWordState, Word


@dataclass
class ImportResult:
    """Result of a CSV import operation."""

    imported: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_processed(self) -> int:
        """Total rows processed."""
        return self.imported + self.updated + self.skipped

    def __str__(self) -> str:
        return (
            f"Imported: {self.imported}, Updated: {self.updated}, "
            f"Skipped: {self.skipped}, Errors: {len(self.errors)}"
        )


class CSVImporter:
    """
    Import French→Basque vocabulary from CSV file.

    Expected CSV columns (tab-separated):
    - index: Internal ID (not stored)
    - age: Age/cohort (not used)
    - mot: French word
    - frequence: Usage frequency (higher = more common)
    - GOOGLE TRANSLATE: Initial translation (not used)
    - LEMMA: Basque lemma
    - VERIFIED: Whether translation is verified (not used)
    - Anki Card ID: Note ID in Anki
    - AnkiStatus: Anki status (not used)
    - Categorie Grammaticale: French grammatical category
    """

    # Map CSV columns to Word model fields
    COLUMN_MAPPING = {
        "mot": "french_word",
        "LEMMA": "basque_lemma",
        "frequence": "frequency_rank",
        "Anki Card ID": "anki_note_id",
        "Categorie Grammaticale": "part_of_speech_fr",
    }

    def __init__(self, session: AsyncSession):
        self.session = session

    async def import_vocabulary(
        self,
        csv_path: str | Path,
        user_id: int,
        encoding: str = "utf-8",
        delimiter: str = "\t",
        create_user_states: bool = True,
    ) -> ImportResult:
        """
        Import vocabulary from CSV file.

        Args:
            csv_path: Path to the CSV file
            user_id: User ID to associate words with
            encoding: File encoding (default: utf-8)
            delimiter: CSV delimiter (default: tab)
            create_user_states: Whether to create UserWordState records

        Returns:
            ImportResult with counts and any errors
        """
        result = ImportResult()
        csv_path = Path(csv_path)

        if not csv_path.exists():
            result.errors.append(f"File not found: {csv_path}")
            return result

        # Verify user exists
        user = await self.session.get(User, user_id)
        if user is None:
            result.errors.append(f"User not found: {user_id}")
            return result

        # Read and process CSV
        with open(csv_path, encoding=encoding, newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)

            for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
                try:
                    word_result = await self._process_row(
                        row, user_id, create_user_states
                    )
                    if word_result == "imported":
                        result.imported += 1
                    elif word_result == "updated":
                        result.updated += 1
                    else:
                        result.skipped += 1
                except Exception as e:
                    result.errors.append(f"Row {row_num}: {e}")

        await self.session.commit()
        return result

    async def _process_row(
        self,
        row: dict,
        user_id: int,
        create_user_states: bool,
    ) -> str:
        """
        Process a single CSV row.

        Returns: "imported", "updated", or "skipped"
        """
        # Extract required fields
        french_word = row.get("mot", "").strip()
        basque_lemma = row.get("LEMMA", "").strip()

        if not french_word or not basque_lemma:
            return "skipped"

        # Parse optional fields
        frequency_rank = self._parse_int(row.get("frequence", ""))
        anki_note_id = self._parse_int(row.get("Anki Card ID", ""))
        part_of_speech_fr = row.get("Categorie Grammaticale", "").strip() or None

        # Check if word already exists (by french_word + basque_lemma combo)
        existing = await self._find_existing_word(french_word, basque_lemma)

        if existing:
            # Update existing word
            if frequency_rank is not None:
                existing.frequency_rank = frequency_rank
            if anki_note_id is not None:
                existing.anki_note_id = anki_note_id
            if part_of_speech_fr:
                existing.part_of_speech_fr = part_of_speech_fr
            return "updated"

        # Create new word
        word = Word(
            word=basque_lemma,  # Use basque lemma as primary word
            language="eu",
            french_word=french_word,
            basque_lemma=basque_lemma,
            translation=french_word,  # French as translation
            frequency_rank=frequency_rank,
            anki_note_id=anki_note_id,
            part_of_speech_fr=part_of_speech_fr,
            lemma=basque_lemma,  # Lemma is the basque form
        )
        self.session.add(word)
        await self.session.flush()  # Get the word ID

        # Create UserWordState if requested
        if create_user_states:
            state = UserWordState(
                user_id=user_id,
                word_id=word.id,
                repetitions=0,
                ease_factor=2.5,
                interval=0,
                total_reviews=0,
                successful_reviews=0,
                mastery_level=0,
            )
            self.session.add(state)

        return "imported"

    async def _find_existing_word(
        self, french_word: str, basque_lemma: str
    ) -> Word | None:
        """Find existing word by french_word and basque_lemma combination."""
        result = await self.session.execute(
            select(Word).where(
                Word.french_word == french_word,
                Word.basque_lemma == basque_lemma,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _parse_int(value: str) -> int | None:
        """Parse integer from string, returning None if invalid."""
        if not value:
            return None
        try:
            return int(float(value))  # Handle "123.0" format
        except (ValueError, TypeError):
            return None


async def import_csv(
    session: AsyncSession,
    csv_path: str | Path,
    user_id: int,
    **kwargs,
) -> ImportResult:
    """Convenience function for CSV import."""
    importer = CSVImporter(session)
    return await importer.import_vocabulary(csv_path, user_id, **kwargs)
