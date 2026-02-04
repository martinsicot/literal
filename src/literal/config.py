"""Application configuration using pydantic-settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = "sqlite+aiosqlite:///./literal.db"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Google Cloud
    google_cloud_api_key: str = ""

    # Application
    debug: bool = False
    sql_echo: bool = False  # Set to True to see SQL queries
    secret_key: str = "change-me-in-production"

    # Language defaults
    default_source_language: str = "eu"  # Basque
    default_target_language: str = "en"  # English

    # Sentence generation
    min_sentence_length: int = 5
    max_sentence_length: int = 15
    known_word_ratio: float = 0.8  # 80% known words in sentence

    # SM-2 mastery thresholds
    mastery_learning_interval: int = 7  # Days before "familiar"
    mastery_known_interval: int = 21  # Days before "known"
    mastery_mature_interval: int = 60  # Days before "mature"
    mastery_known_ease: float = 2.0  # Minimum ease for "known"
    mastery_mature_ease: float = 2.3  # Minimum ease for "mature"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
