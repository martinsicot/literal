"""SentenceWord M2M model for tracking word usage in sentences."""

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from literal.models.base import Base


class SentenceWord(Base):
    """
    Many-to-Many linking sentences to words.

    Tracks EVERY word in a sentence, not just the target word.
    This enables comprehensive queries like:
    - "How many sentences use lemma X?"
    - "What forms of lemma X have been practiced?"
    - "Which lemmas have < 3 sentence usages?"
    - "Which cases has this word been used in?"

    Each record represents one word occurrence in one sentence,
    capturing the specific grammatical form and case used.
    """

    __tablename__ = "sentence_words"

    # Foreign keys
    sentence_id: Mapped[int] = mapped_column(ForeignKey("sentences.id"), nullable=False)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id"), nullable=False)

    # Position in sentence (0-indexed)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Grammatical information
    case_used: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # "absolutive", "ergative", etc.
    form_used: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # Actual surface form: "etxean" not "etxe"
    number: Mapped[str] = mapped_column(
        String(20), default="singular"
    )  # "singular" or "plural"

    # Role in sentence
    is_target: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # True if this is the i+1 word being taught

    # Relationships
    sentence: Mapped["Sentence"] = relationship(  # noqa: F821
        "Sentence",
        back_populates="word_usages",
    )
    word: Mapped["Word"] = relationship(  # noqa: F821
        "Word",
        back_populates="sentence_usages",
    )

    __table_args__ = (
        # Fast lookup by word
        Index("ix_sentence_word_word", "word_id"),
        # Fast lookup by sentence
        Index("ix_sentence_word_sentence", "sentence_id"),
        # Find all usages of a word in a specific case
        Index("ix_sentence_word_word_case", "word_id", "case_used"),
        # Find target words
        Index("ix_sentence_word_is_target", "is_target"),
        # Unique constraint: same word can't appear twice at same position
        Index("ix_sentence_word_unique", "sentence_id", "word_id", "position", unique=True),
    )

    def __repr__(self) -> str:
        return (
            f"<SentenceWord(sentence_id={self.sentence_id}, word_id={self.word_id}, "
            f"form='{self.form_used}', case='{self.case_used}')>"
        )

    @property
    def is_declined(self) -> bool:
        """Check if this word usage has a grammatical case."""
        return self.case_used is not None
