"""Services for Literal application."""

from literal.services.anki import AnkiImporter
from literal.services.anki_sync import AnkiConnectError, AnkiSync, SyncResult
from literal.services.csv_importer import CSVImporter, ImportResult, import_csv
from literal.services.french_builder import FrenchSentenceBuilder, FrenchSentenceResult
from literal.services.generator import (
    CaseGenerationResult,
    SentenceGenerator,
)
from literal.services.mintzaira import (
    MintzairaError,
    MintzairaRateLimitError,
    MintzairaTranslator,
    MintzairaUnavailableError,
    TranslationResult,
)
from literal.services.seed import (
    BASQUE_CASES,
    create_default_user,
    seed_all,
    seed_grammatical_cases,
    seed_user_case_progress,
)
from literal.services.progression import ProgressionConfig, ProgressionService
from literal.services.sm2 import SM2Service
from literal.services.tts import MockTTSService, TTSError, TTSService

__all__ = [
    # Legacy
    "AnkiImporter",
    "SM2Service",
    # Generator
    "SentenceGenerator",
    "CaseGenerationResult",
    # Mintzaira translation
    "MintzairaTranslator",
    "MintzairaError",
    "MintzairaRateLimitError",
    "MintzairaUnavailableError",
    "TranslationResult",
    # French sentence builder
    "FrenchSentenceBuilder",
    "FrenchSentenceResult",
    # New services
    "AnkiSync",
    "AnkiConnectError",
    "SyncResult",
    "CSVImporter",
    "ImportResult",
    "import_csv",
    # Seed functions
    "seed_all",
    "seed_grammatical_cases",
    "seed_user_case_progress",
    "create_default_user",
    "BASQUE_CASES",
    # Progression
    "ProgressionService",
    "ProgressionConfig",
    # TTS
    "TTSService",
    "TTSError",
    "MockTTSService",
]
