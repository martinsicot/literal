"""Grammatical case models for Basque language learning."""

from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from literal.models.base import Base


class GrammaticalCase(Base):
    """
    Basque grammatical case definition.

    Basque has 13+ cases organized into 4 levels of difficulty:
    - Level 1 (Core): Absolutive, Ergative, Dative
    - Level 2 (Location): Inessive, Adlative, Ablative
    - Level 3 (Relation): Genitive, Comitative, Benefactive
    - Level 4 (Advanced): Instrumental, Motivative, Prolative, Partitive
    """

    __tablename__ = "grammatical_cases"

    # Case identification
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name_basque: Mapped[str] = mapped_column(String(50), nullable=False)

    # Morphological info
    suffix: Mapped[str] = mapped_column(String(30), nullable=False)  # e.g., "-n/-an/-etan"

    # Learning progression
    level: Mapped[int] = mapped_column(Integer, nullable=False, index=True)  # 1, 2, 3, or 4

    # Educational content
    description: Mapped[str] = mapped_column(Text, nullable=False)
    example_singular: Mapped[str] = mapped_column(String(100), nullable=False)
    example_plural: Mapped[str] = mapped_column(String(100), nullable=False)

    # Relationships
    user_progress: Mapped[list["UserCaseProgress"]] = relationship(
        "UserCaseProgress",
        back_populates="case",
        cascade="all, delete-orphan",
    )

    __table_args__ = (Index("ix_grammatical_cases_level", "level"),)

    def __repr__(self) -> str:
        return f"<GrammaticalCase(name='{self.name}', level={self.level})>"


class UserCaseProgress(Base):
    """
    Track user's progress learning each grammatical case.

    Tracks how many sentences have been generated/reviewed for each case,
    and determines when the user can unlock the next level.
    """

    __tablename__ = "user_case_progress"

    # Foreign keys
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    case_id: Mapped[int] = mapped_column(ForeignKey("grammatical_cases.id"), nullable=False)

    # Progress tracking
    sentences_generated: Mapped[int] = mapped_column(Integer, default=0)
    sentences_reviewed: Mapped[int] = mapped_column(Integer, default=0)

    # Anki-synced metrics
    avg_interval: Mapped[float] = mapped_column(Float, default=0.0)  # Average days for sentences
    total_reviews: Mapped[int] = mapped_column(Integer, default=0)
    successful_reviews: Mapped[int] = mapped_column(Integer, default=0)

    # Level unlock state
    unlocked: Mapped[bool] = mapped_column(Boolean, default=False)
    unlocked_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="case_progress")  # noqa: F821
    case: Mapped["GrammaticalCase"] = relationship(
        "GrammaticalCase",
        back_populates="user_progress",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "case_id", name="uq_user_case"),
        Index("ix_user_case_progress_user", "user_id"),
        Index("ix_user_case_progress_user_unlocked", "user_id", "unlocked"),
    )

    def __repr__(self) -> str:
        return (
            f"<UserCaseProgress(user_id={self.user_id}, case='{self.case.name if self.case else self.case_id}', "
            f"generated={self.sentences_generated})>"
        )

    @property
    def completion_percentage(self) -> float:
        """Calculate completion percentage for this case (based on 30 sentences target)."""
        target = 30  # Configurable later
        return min(100.0, (self.sentences_generated / target) * 100)

    @property
    def is_mastered(self) -> bool:
        """Check if case is mastered (enough sentences with good average interval)."""
        from literal.config import get_settings

        settings = get_settings()
        min_sentences = getattr(settings, "level_1_sentences_per_case", 30)
        min_interval = getattr(settings, "level_unlock_avg_interval", 21)

        return self.sentences_generated >= min_sentences and self.avg_interval >= min_interval
