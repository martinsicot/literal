"""User and UserWordState models for tracking learning progress."""

from datetime import date, datetime
from enum import IntEnum

from sqlalchemy import Date, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from literal.config import get_settings
from literal.models.base import Base


class MasteryLevel(IntEnum):
    """
    Word mastery levels based on SM-2 state.

    Level 0: NEW - Never seen or just introduced
    Level 1: LEARNING - In early learning phase (interval < 7 days)
    Level 2: FAMILIAR - Progressing but not stable (interval 7-21 days)
    Level 3: KNOWN - Well-learned (interval > 21 days, ease > 2.0)
    Level 4: MATURE - Deeply ingrained (interval > 60 days, ease > 2.3)
    """

    NEW = 0
    LEARNING = 1
    FAMILIAR = 2
    KNOWN = 3
    MATURE = 4


class User(Base):
    """
    User account for tracking individual learning progress.

    Simple user model - can be extended with authentication later.
    """

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)

    # Default language preferences
    source_language: Mapped[str] = mapped_column(String(10), default="eu")  # Learning
    target_language: Mapped[str] = mapped_column(String(10), default="en")  # Native

    # Relationships
    word_states: Mapped[list["UserWordState"]] = relationship(
        "UserWordState",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    sentences: Mapped[list["Sentence"]] = relationship(  # noqa: F821
        "Sentence",
        back_populates="user",
    )
    reviews: Mapped[list["Review"]] = relationship(  # noqa: F821
        "Review",
        back_populates="user",
    )
    case_progress: Mapped[list["UserCaseProgress"]] = relationship(  # noqa: F821
        "UserCaseProgress",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}')>"


class UserWordState(Base):
    """
    SM-2 spaced repetition state for a user's knowledge of a word.

    Tracks review history and calculates when the word should be reviewed next.
    Used to determine which words are "known" vs "learning" for i+1 sentences.
    """

    __tablename__ = "user_word_states"

    # Foreign keys
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id"), nullable=False)

    # SM-2 algorithm state
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5)
    interval: Mapped[int] = mapped_column(Integer, default=0)  # Days until next review

    # Review tracking
    next_review: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_review: Mapped[datetime | None] = mapped_column(nullable=True)
    total_reviews: Mapped[int] = mapped_column(Integer, default=0)
    successful_reviews: Mapped[int] = mapped_column(Integer, default=0)

    # Calculated mastery (cached for performance)
    mastery_level: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="word_states")
    word: Mapped["Word"] = relationship("Word", back_populates="user_states")  # noqa: F821

    __table_args__ = (
        Index("ix_user_word_states_user_word", "user_id", "word_id", unique=True),
        Index("ix_user_word_states_user_next_review", "user_id", "next_review"),
        Index("ix_user_word_states_user_mastery", "user_id", "mastery_level"),
    )

    def __repr__(self) -> str:
        return (
            f"<UserWordState(user_id={self.user_id}, word_id={self.word_id}, "
            f"mastery={self.mastery_level})>"
        )

    def calculate_mastery_level(self) -> MasteryLevel:
        """
        Calculate mastery level based on SM-2 state.

        Returns:
            MasteryLevel enum value based on interval and ease factor.
        """
        settings = get_settings()

        # Never reviewed = NEW
        if self.repetitions == 0 or self.interval == 0:
            return MasteryLevel.NEW

        # Check MATURE first (most restrictive)
        if (
            self.interval >= settings.mastery_mature_interval
            and self.ease_factor >= settings.mastery_mature_ease
        ):
            return MasteryLevel.MATURE

        # Check KNOWN
        if (
            self.interval >= settings.mastery_known_interval
            and self.ease_factor >= settings.mastery_known_ease
        ):
            return MasteryLevel.KNOWN

        # Check FAMILIAR
        if self.interval >= settings.mastery_learning_interval:
            return MasteryLevel.FAMILIAR

        # Still in early learning
        return MasteryLevel.LEARNING

    def update_mastery_level(self) -> None:
        """Update cached mastery level based on current state."""
        self.mastery_level = self.calculate_mastery_level().value

    @property
    def is_due(self) -> bool:
        """Check if word is due for review."""
        if self.next_review is None:
            return True
        return date.today() >= self.next_review

    @property
    def days_overdue(self) -> int:
        """Get number of days overdue (0 if not overdue)."""
        if self.next_review is None:
            return 0
        delta = date.today() - self.next_review
        return max(0, delta.days)

    @property
    def retention_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.total_reviews == 0:
            return 0.0
        return (self.successful_reviews / self.total_reviews) * 100

    @property
    def is_suitable_for_context(self) -> bool:
        """Check if word is stable enough to use as context in i+1 sentences."""
        return self.mastery_level >= MasteryLevel.FAMILIAR.value

    @property
    def is_target_candidate(self) -> bool:
        """Check if word is suitable as the '+1' target in i+1 sentences."""
        return self.mastery_level <= MasteryLevel.LEARNING.value
