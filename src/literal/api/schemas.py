"""Pydantic schemas for API requests and responses."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


# Word schemas
class WordBase(BaseModel):
    """Base word schema."""

    word: str
    language: str = "eu"
    translation: str | None = None
    definition: str | None = None
    part_of_speech: str | None = None
    frequency_rank: int | None = None


class WordCreate(WordBase):
    """Schema for creating a word."""

    pass


class WordResponse(WordBase):
    """Schema for word response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    frequency_tier: str
    created_at: datetime


class WordWithMastery(WordResponse):
    """Word response with user mastery info."""

    mastery_level: int = 0
    mastery_name: str = "new"
    next_review: date | None = None
    interval: int = 0
    ease_factor: float = 2.5
    is_due: bool = True


# User schemas
class UserCreate(BaseModel):
    """Schema for creating a user."""

    username: str
    email: str | None = None
    source_language: str = "eu"
    target_language: str = "en"


class UserResponse(BaseModel):
    """Schema for user response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None
    source_language: str
    target_language: str
    created_at: datetime


# Review schemas
class ReviewRequest(BaseModel):
    """Schema for recording a review."""

    word_id: int
    quality: int = Field(ge=0, le=5, description="Quality rating 0-5")
    sentence_id: int | None = None
    session_id: str | None = None
    response_time_ms: int | None = None


class ReviewResponse(BaseModel):
    """Schema for review response."""

    word_id: int
    new_interval: int
    new_ease_factor: float
    next_review: date
    mastery_level: int
    mastery_name: str


# Sentence schemas
class SentenceResponse(BaseModel):
    """Schema for sentence response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    sentence_text: str
    translation: str | None
    target_word_id: int
    target_word: str
    target_word_translation: str | None
    language: str
    word_count: int
    created_at: datetime


class SessionResponse(BaseModel):
    """Schema for a learning session."""

    sentence: SentenceResponse
    target_word: WordWithMastery
    context_words: list[WordResponse]


# Import schemas
class ImportRequest(BaseModel):
    """Schema for import configuration."""

    language: str = "eu"
    import_reviews: bool = True
    field_mapping: dict[str, int] | None = None


class ImportResponse(BaseModel):
    """Schema for import result."""

    words_imported: int
    words_updated: int
    words_skipped: int
    reviews_imported: int
    errors: list[str]


# Statistics schemas
class StatsResponse(BaseModel):
    """Schema for user statistics."""

    total_words: int
    words_by_mastery: dict[str, int]
    words_due_today: int
    reviews_today: int
    reviews_this_week: int
    average_retention: float
    streak_days: int
    # Anki-synced vocabulary stats
    vocabulary_total: int = 0
    vocabulary_known: int = 0  # interval >= 14 days
    vocabulary_learning: int = 0  # interval 1-13 days
    vocabulary_new: int = 0  # interval 0 or not synced
    anki_avg_interval: float = 0.0


# Pagination
class PaginatedResponse(BaseModel):
    """Generic paginated response."""

    items: list
    total: int
    page: int
    page_size: int
    total_pages: int
