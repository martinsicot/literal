"""Mintzaira/Itzuli French↔Basque translation service client."""

import asyncio
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

TranslationDirection = Literal["fr2eu", "eu2fr"]


class MintzairaError(Exception):
    """Error from Mintzaira translation service."""

    pass


class MintzairaRateLimitError(MintzairaError):
    """Rate limit exceeded."""

    pass


class MintzairaUnavailableError(MintzairaError):
    """Service temporarily unavailable."""

    pass


@dataclass
class TranslationResult:
    """Result of a translation request."""

    source_text: str
    translated_text: str
    direction: TranslationDirection


class MintzairaTranslator:
    """
    Client for Mintzaira/Itzuli French↔Basque translation service.

    Uses the Itzuli machine translation system hosted at mintzaira.fr.
    This is a professional Basque translation service that produces
    grammatically correct Basque output.

    Example:
        translator = MintzairaTranslator()
        result = await translator.translate_fr_to_eu("Nous mangeons de la viande.")
        print(result)  # "Haragia jaten dugu."
    """

    BASE_URL = "https://www.mintzaira.fr/fr/ressources/traducteur-francais-basque-itzuli.html"

    # Default headers mimicking browser request
    DEFAULT_HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://www.mintzaira.fr",
        "Referer": "https://www.mintzaira.fr/fr/ressources/traducteur-francais-basque-itzuli.html",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }

    def __init__(
        self,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """
        Initialize the Mintzaira translator.

        Args:
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            retry_delay: Base delay between retries (exponential backoff)
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=self.DEFAULT_HEADERS,
                timeout=self.timeout,
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "MintzairaTranslator":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()

    def _build_form_data(self, text: str, direction: TranslationDirection) -> str:
        """Build form data for the translation request."""
        data = {
            "tx_itzuli_pi1[lang]": direction,
            "tx_itzuli_pi1[input_field]": text,
            "tx_itzuli_pi1[submit_button]": "Traduire",
        }
        return urlencode(data)

    def _parse_translation(self, html: str) -> str:
        """
        Parse the translation result from HTML response.

        Args:
            html: HTML response from Mintzaira

        Returns:
            Translated text

        Raises:
            MintzairaError: If translation cannot be extracted
        """
        soup = BeautifulSoup(html, "html.parser")

        # Primary method: look for resultItzuli element (current site structure)
        # Translation appears in <p id="resultItzuli" class="alert alert-success">
        result_elem = soup.find(id="resultItzuli")
        if result_elem:
            text = result_elem.get_text(strip=True)
            if text:
                return text

        # Fallback: look for alert-success class
        alert_elem = soup.find(class_="alert-success")
        if alert_elem:
            text = alert_elem.get_text(strip=True)
            if text:
                return text

        # Legacy fallback: textarea with output_field name
        output_field = soup.find("textarea", {"name": "tx_itzuli_pi1[output_field]"})
        if output_field and output_field.string:
            return output_field.string.strip()

        # Alternative: look for output div
        output_div = soup.find("div", class_="output")
        if output_div:
            return output_div.get_text(strip=True)

        # Try finding by ID pattern
        for textarea in soup.find_all("textarea"):
            name = textarea.get("name", "")
            if "output" in name.lower():
                text = textarea.string or textarea.get_text()
                if text:
                    return text.strip()

        # Last resort: look for any element with translated content
        result_pattern = re.compile(r"tx_itzuli_pi1\[output", re.IGNORECASE)
        for elem in soup.find_all(attrs={"name": result_pattern}):
            text = elem.string or elem.get_text()
            if text:
                return text.strip()

        raise MintzairaError("Could not extract translation from response")

    async def _translate(
        self,
        text: str,
        direction: TranslationDirection,
    ) -> TranslationResult:
        """
        Perform translation with retry logic.

        Args:
            text: Text to translate
            direction: Translation direction ("fr2eu" or "eu2fr")

        Returns:
            TranslationResult with source and translated text

        Raises:
            MintzairaError: If translation fails after all retries
        """
        if not text.strip():
            return TranslationResult(
                source_text=text,
                translated_text="",
                direction=direction,
            )

        client = await self._get_client()
        form_data = self._build_form_data(text, direction)

        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                response = await client.post(
                    self.BASE_URL,
                    content=form_data,
                )

                if response.status_code == 429:
                    raise MintzairaRateLimitError("Rate limit exceeded")

                if response.status_code >= 500:
                    raise MintzairaUnavailableError(
                        f"Service error: {response.status_code}"
                    )

                response.raise_for_status()

                translated_text = self._parse_translation(response.text)

                return TranslationResult(
                    source_text=text,
                    translated_text=translated_text,
                    direction=direction,
                )

            except (MintzairaRateLimitError, MintzairaUnavailableError) as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2**attempt)
                    await asyncio.sleep(delay)
                continue

            except httpx.TimeoutException as e:
                last_error = MintzairaError(f"Request timeout: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
                continue

            except httpx.RequestError as e:
                last_error = MintzairaError(f"Request failed: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
                continue

        raise last_error or MintzairaError("Translation failed after all retries")

    async def translate_fr_to_eu(self, french_text: str) -> str:
        """
        Translate French text to Basque.

        Args:
            french_text: French text to translate

        Returns:
            Basque translation

        Raises:
            MintzairaError: If translation fails

        Example:
            basque = await translator.translate_fr_to_eu("Nous mangeons de la viande.")
            # Returns: "Haragia jaten dugu."
        """
        result = await self._translate(french_text, "fr2eu")
        return result.translated_text

    async def translate_eu_to_fr(self, basque_text: str) -> str:
        """
        Translate Basque text to French.

        Args:
            basque_text: Basque text to translate

        Returns:
            French translation

        Raises:
            MintzairaError: If translation fails

        Example:
            french = await translator.translate_eu_to_fr("Haragia jaten dugu.")
            # Returns: "Nous mangeons de la viande."
        """
        result = await self._translate(basque_text, "eu2fr")
        return result.translated_text

    async def translate(
        self,
        text: str,
        direction: TranslationDirection,
    ) -> TranslationResult:
        """
        Translate text in the specified direction.

        Args:
            text: Text to translate
            direction: "fr2eu" for French→Basque, "eu2fr" for Basque→French

        Returns:
            TranslationResult with full details

        Raises:
            MintzairaError: If translation fails
        """
        return await self._translate(text, direction)
