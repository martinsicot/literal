"""Database models for Literal."""

from literal.models.base import Base, get_async_session, init_db
from literal.models.case import GrammaticalCase, UserCaseProgress
from literal.models.sentence import Review, ReviewQuality, Sentence
from literal.models.sentence_word import SentenceWord
from literal.models.user import MasteryLevel, User, UserWordState
from literal.models.word import PartOfSpeech, Word

__all__ = [
    # Base
    "Base",
    "get_async_session",
    "init_db",
    # Core models
    "Word",
    "User",
    "UserWordState",
    "Sentence",
    "Review",
    # New models for Basque case system
    "GrammaticalCase",
    "UserCaseProgress",
    "SentenceWord",
    # Enums
    "PartOfSpeech",
    "MasteryLevel",
    "ReviewQuality",
]
