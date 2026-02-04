"""Text-to-Speech service using Google Cloud TTS."""

import base64
import hashlib
from pathlib import Path
from typing import Literal

import httpx

from literal.config import get_settings

Language = Literal["fr", "eu"]


class TTSError(Exception):
    """TTS service error."""

    pass


class TTSService:
    """
    Generate audio via Google Cloud Text-to-Speech REST API.

    Supports:
    - French (fr-FR) with Neural2 voice
    - Basque (eu-ES) with Standard voice

    Uses GOOGLE_CLOUD_API_KEY from settings.
    """

    # Voice configuration for each language
    VOICE_CONFIG = {
        "fr": {
            "languageCode": "fr-FR",
            "name": "fr-FR-Neural2-A",
            "ssmlGender": "FEMALE",
        },
        "eu": {
            "languageCode": "eu-ES",
            "name": "eu-ES-Standard-A",
            "ssmlGender": "FEMALE",
        },
    }

    API_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"

    def __init__(self, output_dir: str | Path = "data/audio", api_key: str | None = None):
        """
        Initialize TTS service.

        Args:
            output_dir: Directory to save generated audio files
            api_key: Google Cloud API key (defaults to settings)
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        settings = get_settings()
        self.api_key = api_key or getattr(settings, "google_cloud_api_key", "")

        if not self.api_key:
            raise TTSError(
                "Google Cloud API key not configured. "
                "Set GOOGLE_CLOUD_API_KEY in .env.local"
            )

    def generate_audio(
        self,
        text: str,
        language: Language,
        sentence_id: int | None = None,
    ) -> Path:
        """
        Generate audio file for text.

        Args:
            text: Text to synthesize
            language: Language code ("fr" or "eu")
            sentence_id: Optional sentence ID for filename

        Returns:
            Path to the generated audio file

        Raises:
            TTSError: If TTS fails or is not configured
        """
        if language not in self.VOICE_CONFIG:
            raise TTSError(f"Unsupported language: {language}")

        voice_config = self.VOICE_CONFIG[language]

        # Generate filename
        if sentence_id is not None:
            filename = f"{sentence_id}_{language}.mp3"
        else:
            # Use hash of text for unique filename
            text_hash = hashlib.md5(text.encode()).hexdigest()[:12]
            filename = f"{text_hash}_{language}.mp3"

        output_path = self.output_dir / filename

        # Skip if already exists
        if output_path.exists():
            return output_path

        # Build REST API request
        request_body = {
            "input": {"text": text},
            "voice": {
                "languageCode": voice_config["languageCode"],
                "name": voice_config["name"],
                "ssmlGender": voice_config["ssmlGender"],
            },
            "audioConfig": {
                "audioEncoding": "MP3",
                "speakingRate": 0.9,  # Slightly slower for language learning
                "pitch": 0.0,
            },
        }

        try:
            response = httpx.post(
                f"{self.API_URL}?key={self.api_key}",
                json=request_body,
                timeout=30.0,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            error_detail = e.response.text if e.response else str(e)
            raise TTSError(f"TTS API error: {error_detail}") from e
        except httpx.RequestError as e:
            raise TTSError(f"TTS request failed: {e}") from e

        result = response.json()

        if "audioContent" not in result:
            raise TTSError(f"No audio in response: {result}")

        # Decode base64 audio and write to file
        audio_content = base64.b64decode(result["audioContent"])
        with open(output_path, "wb") as f:
            f.write(audio_content)

        return output_path

    def generate_sentence_audio(
        self,
        basque_text: str,
        french_text: str,
        sentence_id: int,
    ) -> tuple[Path, Path]:
        """
        Generate audio for both Basque and French versions of a sentence.

        Args:
            basque_text: Basque sentence text
            french_text: French translation
            sentence_id: Sentence ID for filenames

        Returns:
            Tuple of (basque_audio_path, french_audio_path)
        """
        basque_path = self.generate_audio(basque_text, "eu", sentence_id)
        french_path = self.generate_audio(french_text, "fr", sentence_id)

        return (basque_path, french_path)

    def get_audio_path(self, sentence_id: int, language: Language) -> Path | None:
        """
        Get path to existing audio file if it exists.

        Args:
            sentence_id: Sentence ID
            language: Language code

        Returns:
            Path if file exists, None otherwise
        """
        path = self.output_dir / f"{sentence_id}_{language}.mp3"
        return path if path.exists() else None


class MockTTSService(TTSService):
    """
    Mock TTS service for testing without Google Cloud credentials.

    Creates empty placeholder files instead of real audio.
    """

    def __init__(self, output_dir: str | Path = "data/audio", api_key: str | None = None):
        """Initialize mock TTS (doesn't require API key)."""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = api_key or "mock"

    def generate_audio(
        self,
        text: str,
        language: Language,
        sentence_id: int | None = None,
    ) -> Path:
        """Generate mock audio file (empty placeholder)."""
        if language not in self.VOICE_CONFIG:
            raise TTSError(f"Unsupported language: {language}")

        if sentence_id is not None:
            filename = f"{sentence_id}_{language}.mp3"
        else:
            text_hash = hashlib.md5(text.encode()).hexdigest()[:12]
            filename = f"{text_hash}_{language}.mp3"

        output_path = self.output_dir / filename

        # Create empty file as placeholder
        output_path.touch()

        return output_path
