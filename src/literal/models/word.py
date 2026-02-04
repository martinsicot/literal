"""Word model for vocabulary storage."""

from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, Boolean, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from literal.models.base import Base


class PartOfSpeech(str, Enum):
    """Parts of speech for vocabulary words."""

    NOUN = "noun"
    VERB = "verb"
    ADJECTIVE = "adjective"
    ADVERB = "adverb"
    PRONOUN = "pronoun"
    PREPOSITION = "preposition"
    CONJUNCTION = "conjunction"
    INTERJECTION = "interjection"
    DETERMINER = "determiner"
    OTHER = "other"


class Word(Base):
    """
    Vocabulary word with translation and frequency data.

    For Basque learning, stores French→Basque word pairs imported from CSV,
    with Anki sync fields to track learning progress.
    """

    __tablename__ = "words"

    # Core word data (original fields, repurposed)
    word: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    language: Mapped[str] = mapped_column(
        String(10), nullable=False, default="eu"
    )  # ISO 639-1 code

    # French→Basque vocabulary pair (new fields for CSV import)
    french_word: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    basque_lemma: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # Translation and meaning
    translation: Mapped[str | None] = mapped_column(Text, nullable=True)
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Linguistic metadata
    part_of_speech: Mapped[str | None] = mapped_column(String(50), nullable=True)
    part_of_speech_fr: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # French grammatical category from CSV
    lemma: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # Base form for inflected words

    # Frequency data (from corpus/CSV)
    frequency_rank: Mapped[int | None] = mapped_column(
        nullable=True, index=True
    )  # Higher = more common (from CSV 'frequence')
    frequency_count: Mapped[int | None] = mapped_column(nullable=True)  # Raw count in corpus

    # Source tracking - Anki note ID (BigInteger for large Anki IDs)
    anki_note_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)

    # Anki sync fields (updated via AnkiConnect)
    anki_interval: Mapped[int] = mapped_column(Integer, default=0)  # Days since last review
    anki_ease: Mapped[float] = mapped_column(Float, default=2.5)  # Ease factor (2.5 = default)
    anki_last_review: Mapped[datetime | None] = mapped_column(nullable=True)
    is_known: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True
    )  # True when interval > threshold
    last_synced: Mapped[datetime | None] = mapped_column(nullable=True)  # Last AnkiConnect sync

    # Usage tracking (denormalized, source of truth is SentenceWord M2M)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)  # How many sentences use this word

    # Relationships
    user_states: Mapped[list["UserWordState"]] = relationship(  # noqa: F821
        "UserWordState",
        back_populates="word",
        cascade="all, delete-orphan",
    )
    sentences: Mapped[list["Sentence"]] = relationship(  # noqa: F821
        "Sentence",
        back_populates="target_word",
        foreign_keys="Sentence.target_word_id",
    )
    sentence_usages: Mapped[list["SentenceWord"]] = relationship(  # noqa: F821
        "SentenceWord",
        back_populates="word",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_words_language_word", "language", "word"),
        Index("ix_words_language_frequency", "language", "frequency_rank"),
        Index("ix_words_french_basque", "french_word", "basque_lemma"),
        Index("ix_words_is_known", "is_known"),
    )

    def __repr__(self) -> str:
        return f"<Word(id={self.id}, word='{self.word}', lang='{self.language}')>"

    @property
    def is_common(self) -> bool:
        """Check if word is in the most common 1000 words."""
        return self.frequency_rank is not None and self.frequency_rank <= 1000

    @property
    def frequency_tier(self) -> str:
        """Get frequency tier for display."""
        if self.frequency_rank is None:
            return "unknown"
        if self.frequency_rank <= 500:
            return "very_common"
        if self.frequency_rank <= 2000:
            return "common"
        if self.frequency_rank <= 5000:
            return "moderate"
        return "rare"

    @property
    def is_available_for_sentences(self) -> bool:
        """Check if word is known enough to use in sentence generation."""
        return self.is_known

    @property
    def needs_more_usage(self) -> bool:
        """Check if word needs to appear in more sentences (min 3)."""
        return self.usage_count < 3

    def update_known_status(self, threshold_days: int = 14) -> bool:
        """
        Update is_known based on Anki interval.

        Args:
            threshold_days: Minimum interval to consider word "known"

        Returns:
            True if status changed, False otherwise
        """
        was_known = self.is_known
        self.is_known = self.anki_interval >= threshold_days
        return self.is_known != was_known
