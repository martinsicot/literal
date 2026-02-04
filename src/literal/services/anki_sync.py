"""AnkiConnect sync service for bidirectional Anki integration."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from literal.models import GrammaticalCase, Sentence, UserCaseProgress, Word


class AnkiConnectError(Exception):
    """AnkiConnect API error."""

    pass


@dataclass
class SyncResult:
    """Result of a sync operation."""

    synced: int = 0
    not_found: int = 0
    newly_known: int = 0  # Words that crossed the "known" threshold
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"Synced: {self.synced}, Not found: {self.not_found}, "
            f"Newly known: {self.newly_known}, Errors: {len(self.errors)}"
        )


class AnkiSync:
    """
    Bidirectional sync with Anki via AnkiConnect.

    Handles:
    - Syncing lemma learning progress from Anki
    - Syncing sentence review progress from Anki
    - Creating new sentence cards in Anki
    """

    # Anki queue codes
    QUEUE_NAMES = {
        -1: "suspended",
        0: "new",
        1: "learning",
        2: "review",
        3: "day-learn",
        4: "preview",
    }

    def __init__(
        self,
        session: AsyncSession,
        host: str = "localhost",
        port: int = 8765,
    ):
        self.session = session
        self.url = f"http://{host}:{port}"
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    async def request(self, action: str, **params: Any) -> Any:
        """Make AnkiConnect request."""
        payload: dict[str, Any] = {
            "action": action,
            "version": 6,
        }
        if params:
            payload["params"] = params

        try:
            response = await self.client.post(self.url, json=payload)
            response.raise_for_status()
        except httpx.ConnectError:
            raise AnkiConnectError(
                "Cannot connect to Anki. Make sure Anki is running "
                "and AnkiConnect addon is installed."
            )
        except httpx.HTTPError as e:
            raise AnkiConnectError(f"HTTP error: {e}")

        result = response.json()

        if result.get("error"):
            raise AnkiConnectError(result["error"])

        return result.get("result")

    # ==================== Lemma Progress Sync ====================

    async def sync_lemma_progress(
        self,
        deck_name: str,
        user_id: int,
        known_threshold_days: int = 14,
    ) -> SyncResult:
        """
        Pull learning progress from Anki lemma deck.

        Updates Word.anki_interval, anki_ease, is_known for all words
        that have matching anki_note_id.

        Args:
            deck_name: Name of the Anki deck containing lemmas
            user_id: User ID (for logging/filtering)
            known_threshold_days: Interval threshold for "known" status

        Returns:
            SyncResult with counts
        """
        result = SyncResult()

        # Get all cards in deck
        query = f'deck:"{deck_name}"'
        card_ids = await self.request("findCards", query=query)

        if not card_ids:
            result.errors.append(f"No cards found in deck: {deck_name}")
            return result

        # Get card info
        cards_info = await self.request("cardsInfo", cards=card_ids)

        # Group by note (average across cards of same note)
        note_data = self._group_cards_by_note(cards_info)

        # Update words in database
        for note_id, data in note_data.items():
            # Find word by anki_note_id
            word_result = await self.session.execute(
                select(Word).where(Word.anki_note_id == note_id)
            )
            word = word_result.scalar_one_or_none()

            if word is None:
                result.not_found += 1
                continue

            # Check if word is crossing the "known" threshold
            was_known = word.is_known
            new_is_known = data["interval"] >= known_threshold_days

            # Update word
            word.anki_interval = data["interval"]
            word.anki_ease = data["ease"]
            word.anki_last_review = data["last_review"]
            word.is_known = new_is_known
            word.last_synced = datetime.now(UTC)

            result.synced += 1
            if not was_known and new_is_known:
                result.newly_known += 1

        await self.session.commit()
        return result

    def _group_cards_by_note(
        self, cards_info: list[dict]
    ) -> dict[int, dict[str, Any]]:
        """Group cards by note ID and compute averages."""
        notes: dict[int, list[dict]] = {}

        for card in cards_info:
            note_id = card.get("note")
            if note_id is None:
                continue

            if note_id not in notes:
                notes[note_id] = []
            notes[note_id].append(card)

        result = {}
        for note_id, note_cards in notes.items():
            # Average interval and ease across all cards
            avg_interval = sum(c.get("interval", 0) for c in note_cards) / len(note_cards)
            avg_ease = sum(c.get("factor", 2500) for c in note_cards) / len(note_cards) / 1000

            # Find most recent review
            last_review = None
            for card in note_cards:
                due = card.get("due", 0)
                if due > 100000:  # Timestamp
                    card_review = datetime.fromtimestamp(due, tz=UTC)
                    if last_review is None or card_review > last_review:
                        last_review = card_review

            result[note_id] = {
                "interval": int(avg_interval),
                "ease": avg_ease,
                "last_review": last_review,
            }

        return result

    # ==================== Sentence Progress Sync ====================

    async def sync_sentence_progress(
        self,
        deck_name: str,
        user_id: int,
    ) -> SyncResult:
        """
        Pull learning progress for generated sentences.

        Updates Sentence.anki_interval and recalculates
        UserCaseProgress.avg_interval for each case.

        Args:
            deck_name: Name of the Anki deck containing sentences
            user_id: User ID for filtering

        Returns:
            SyncResult with counts
        """
        result = SyncResult()

        # Get all cards in deck
        query = f'deck:"{deck_name}"'
        card_ids = await self.request("findCards", query=query)

        if not card_ids:
            result.errors.append(f"No cards found in deck: {deck_name}")
            return result

        # Get card info
        cards_info = await self.request("cardsInfo", cards=card_ids)

        # Group by note
        note_data = self._group_cards_by_note(cards_info)

        # Track case intervals for averaging
        case_intervals: dict[int, list[int]] = {}

        # Update sentences in database
        for note_id, data in note_data.items():
            # Find sentence by anki_note_id
            sentence_result = await self.session.execute(
                select(Sentence).where(
                    Sentence.anki_note_id == note_id,
                    Sentence.user_id == user_id,
                )
            )
            sentence = sentence_result.scalar_one_or_none()

            if sentence is None:
                result.not_found += 1
                continue

            # Update sentence
            sentence.anki_interval = data["interval"]
            sentence.anki_last_review = data["last_review"]

            # Track for case averaging
            if sentence.target_case_id:
                if sentence.target_case_id not in case_intervals:
                    case_intervals[sentence.target_case_id] = []
                case_intervals[sentence.target_case_id].append(data["interval"])

            result.synced += 1

        # Update UserCaseProgress averages
        for case_id, intervals in case_intervals.items():
            avg = sum(intervals) / len(intervals)
            await self.session.execute(
                update(UserCaseProgress)
                .where(
                    UserCaseProgress.user_id == user_id,
                    UserCaseProgress.case_id == case_id,
                )
                .values(
                    avg_interval=avg,
                    sentences_reviewed=len(intervals),
                )
            )

        await self.session.commit()
        return result

    # ==================== Card Creation ====================

    async def create_sentence_card(
        self,
        sentence: Sentence,
        deck_name: str,
        model_name: str = "Literal-Sentence",
    ) -> int:
        """
        Create Anki note for a sentence.

        Card format:
        - Front: French text + French audio
        - Back: Basque text + Basque audio

        Args:
            sentence: Sentence to create card for
            deck_name: Target Anki deck
            model_name: Anki note type name

        Returns:
            Created note ID
        """
        # Ensure note type exists
        await self._ensure_note_type(model_name)

        # Prepare fields
        fields = {
            "FrenchText": sentence.french_text or "",
            "BasqueText": sentence.sentence_text,
        }

        # Add audio if available
        if sentence.audio_french_path:
            audio_filename = Path(sentence.audio_french_path).name
            # Store media in Anki
            await self._store_media(sentence.audio_french_path)
            fields["FrenchAudio"] = f"[sound:{audio_filename}]"
        else:
            fields["FrenchAudio"] = ""

        if sentence.audio_basque_path:
            audio_filename = Path(sentence.audio_basque_path).name
            await self._store_media(sentence.audio_basque_path)
            fields["BasqueAudio"] = f"[sound:{audio_filename}]"
        else:
            fields["BasqueAudio"] = ""

        # Create note
        note_id = await self.request(
            "addNote",
            note={
                "deckName": deck_name,
                "modelName": model_name,
                "fields": fields,
                "options": {"allowDuplicate": False},
                "tags": ["literal", "generated"],
            },
        )

        if note_id is None:
            raise AnkiConnectError("Failed to create note")

        # Update sentence with note ID
        sentence.anki_note_id = note_id
        await self.session.commit()

        return note_id

    async def _ensure_note_type(self, model_name: str) -> None:
        """Create note type if it doesn't exist."""
        existing = await self.request("modelNames")

        if model_name in existing:
            return

        # Create new model
        await self.request(
            "createModel",
            modelName=model_name,
            inOrderFields=["FrenchText", "FrenchAudio", "BasqueText", "BasqueAudio"],
            css="""
                .card {
                    font-family: Arial, sans-serif;
                    font-size: 20px;
                    text-align: center;
                    color: black;
                    background-color: white;
                }
                .french { color: #333; }
                .basque { color: #0066cc; font-weight: bold; }
            """,
            cardTemplates=[
                {
                    "Name": "FR → EU",
                    "Front": """
                        <div class="french">{{FrenchText}}</div>
                        {{FrenchAudio}}
                    """,
                    "Back": """
                        {{FrontSide}}
                        <hr id="answer">
                        <div class="basque">{{BasqueText}}</div>
                        {{BasqueAudio}}
                    """,
                }
            ],
        )

    async def _store_media(self, file_path: str | Path) -> str:
        """Store media file in Anki."""
        file_path = Path(file_path)

        if not file_path.exists():
            raise AnkiConnectError(f"Media file not found: {file_path}")

        # Read file as base64
        import base64

        with open(file_path, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")

        # Store in Anki
        await self.request(
            "storeMediaFile",
            filename=file_path.name,
            data=data,
        )

        return file_path.name

    # ==================== Deck Management ====================

    async def get_deck_names(self) -> list[str]:
        """Get all deck names."""
        return await self.request("deckNames")

    async def ensure_deck(self, deck_name: str) -> None:
        """Create deck if it doesn't exist."""
        await self.request("createDeck", deck=deck_name)
