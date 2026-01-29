"""Word model for vocabulary storage."""

from enum import Enum

from sqlalchemy import Index, String, Text
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

    Represents a single word in the target language (e.g., Basque)
    with its translation and corpus frequency ranking.
    """

    __tablename__ = "words"

    # Core word data
    word: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    language: Mapped[str] = mapped_column(
        String(10), nullable=False, default="eu"
    )  # ISO 639-1 code

    # Translation and meaning
    translation: Mapped[str | None] = mapped_column(Text, nullable=True)
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Linguistic metadata
    part_of_speech: Mapped[str | None] = mapped_column(String(50), nullable=True)
    lemma: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # Base form for inflected words

    # Frequency data (from corpus)
    frequency_rank: Mapped[int | None] = mapped_column(
        nullable=True, index=True
    )  # Lower = more common
    frequency_count: Mapped[int | None] = mapped_column(nullable=True)  # Raw count in corpus

    # Source tracking
    anki_note_id: Mapped[int | None] = mapped_column(nullable=True, unique=True)

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

    __table_args__ = (
        Index("ix_words_language_word", "language", "word"),
        Index("ix_words_language_frequency", "language", "frequency_rank"),
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
