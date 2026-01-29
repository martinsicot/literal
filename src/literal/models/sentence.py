"""Sentence and Review models for generated content and review tracking."""

import json
from datetime import UTC, datetime
from enum import IntEnum

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from literal.models.base import Base


class ReviewQuality(IntEnum):
    """
    Review quality ratings mapped from user input.

    Based on SM-2 scale (0-5), but we use 4 buttons:
    - AGAIN (0): Complete failure, restart learning
    - HARD (2): Correct but with significant difficulty
    - GOOD (3): Correct with some effort (default)
    - EASY (5): Perfect recall, no hesitation
    """

    AGAIN = 0
    HARD = 2
    GOOD = 3
    EASY = 5


class Sentence(Base):
    """
    AI-generated sentence for vocabulary practice.

    Each sentence targets one "unknown" word (the +1) while using
    known words as context, following the i+1 comprehensible input method.
    """

    __tablename__ = "sentences"

    # Foreign keys
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    target_word_id: Mapped[int] = mapped_column(ForeignKey("words.id"), nullable=False)

    # Content
    sentence_text: Mapped[str] = mapped_column(Text, nullable=False)
    translation: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="eu")

    # Context tracking (JSON array of word IDs used as context)
    context_word_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Generation metadata
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Quality tracking
    times_shown: Mapped[int] = mapped_column(Integer, default=0)
    user_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5 stars
    flagged: Mapped[bool] = mapped_column(default=False)  # User flagged as bad

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="sentences")  # noqa: F821
    target_word: Mapped["Word"] = relationship(  # noqa: F821
        "Word",
        back_populates="sentences",
        foreign_keys=[target_word_id],
    )
    reviews: Mapped[list["Review"]] = relationship(
        "Review",
        back_populates="sentence",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_sentences_user_target", "user_id", "target_word_id"),
        Index("ix_sentences_user_language", "user_id", "language"),
    )

    def __repr__(self) -> str:
        preview = self.sentence_text[:30] + "..." if len(self.sentence_text) > 30 else self.sentence_text
        return f"<Sentence(id={self.id}, preview='{preview}')>"

    @property
    def context_word_ids(self) -> list[int]:
        """Get list of context word IDs."""
        if not self.context_word_ids_json:
            return []
        return json.loads(self.context_word_ids_json)

    @context_word_ids.setter
    def context_word_ids(self, word_ids: list[int]) -> None:
        """Set list of context word IDs."""
        self.context_word_ids_json = json.dumps(word_ids)

    @property
    def word_count(self) -> int:
        """Get approximate word count."""
        return len(self.sentence_text.split())

    @property
    def average_rating(self) -> float | None:
        """Get average review quality for this sentence."""
        if not self.reviews:
            return None
        return sum(r.quality for r in self.reviews) / len(self.reviews)


class Review(Base):
    """
    Single review event recording user's recall attempt.

    Links a user's review of a word within the context of a specific sentence.
    """

    __tablename__ = "reviews"

    # Foreign keys
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id"), nullable=False)
    sentence_id: Mapped[int | None] = mapped_column(ForeignKey("sentences.id"), nullable=True)

    # Review data
    quality: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-5 SM-2 scale
    reviewed_at: Mapped[datetime] = mapped_column(nullable=False, default=lambda: datetime.now(UTC))

    # State snapshot (for debugging/analysis)
    ease_factor_before: Mapped[float | None] = mapped_column(nullable=True)
    interval_before: Mapped[int | None] = mapped_column(nullable=True)
    ease_factor_after: Mapped[float | None] = mapped_column(nullable=True)
    interval_after: Mapped[int | None] = mapped_column(nullable=True)

    # Session tracking
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # UUID
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="reviews")  # noqa: F821
    word: Mapped["Word"] = relationship("Word")  # noqa: F821
    sentence: Mapped["Sentence"] = relationship("Sentence", back_populates="reviews")

    __table_args__ = (
        Index("ix_reviews_user_word", "user_id", "word_id"),
        Index("ix_reviews_user_reviewed_at", "user_id", "reviewed_at"),
    )

    def __repr__(self) -> str:
        return f"<Review(user_id={self.user_id}, word_id={self.word_id}, quality={self.quality})>"

    @property
    def is_successful(self) -> bool:
        """Check if review was successful (quality >= 3)."""
        return self.quality >= ReviewQuality.GOOD.value

    @property
    def quality_label(self) -> str:
        """Get human-readable quality label."""
        labels = {
            0: "Again",
            1: "Again",
            2: "Hard",
            3: "Good",
            4: "Good",
            5: "Easy",
        }
        return labels.get(self.quality, "Unknown")
