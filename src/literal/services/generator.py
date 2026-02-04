"""Sentence generation service using OpenAI and Mintzaira translation."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from literal.config import get_settings
from literal.models.case import GrammaticalCase
from literal.models.sentence import Sentence
from literal.models.word import Word
from literal.services.french_builder import FrenchSentenceBuilder
from literal.services.mintzaira import MintzairaError, MintzairaTranslator

if TYPE_CHECKING:
    from literal.services.progression import ProgressionService
    from literal.services.tts import TTSService


@dataclass
class CaseGenerationResult:
    """Result of case-aware sentence generation for Basque."""

    basque_text: str
    french_text: str
    target_word: Word
    target_case: GrammaticalCase
    target_number: str  # "singular" or "plural"
    target_form: str  # The inflected form used in the sentence
    context_words: list[Word]
    words_used: list[dict] = field(default_factory=list)  # [{lemma, form, case}, ...]
    model_used: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


class SentenceGenerator:
    """
    Generate i+1 sentences using French→Mintzaira translation flow.

    Creates sentences that:
    - Use mostly known words as context
    - Introduce exactly one new/learning word
    - Make the target word's meaning clear from context
    - Produce grammatically correct Basque via Mintzaira
    """

    def __init__(self, session: AsyncSession, client: AsyncOpenAI | None = None):
        """
        Initialize generator.

        Args:
            session: Database session
            client: OpenAI client (created if not provided)
        """
        self.session = session
        self.settings = get_settings()
        self.client = client or AsyncOpenAI(api_key=self.settings.openai_api_key)

        # Mintzaira translation flow components
        self.mintzaira = MintzairaTranslator()
        self.french_builder = FrenchSentenceBuilder(
            client=self.client,
            model=self.settings.openai_model,
        )

    async def generate_for_case(
        self,
        user_id: int,
        target_case: GrammaticalCase,
        target_number: str,
        target_word: Word | None = None,
        context_words: list[Word] | None = None,
        progression_service: "ProgressionService | None" = None,
    ) -> CaseGenerationResult | None:
        """
        Generate a Basque sentence with a specific grammatical case.

        Args:
            user_id: User ID
            target_case: The grammatical case to practice
            target_number: "singular" or "plural"
            target_word: Optional target word (auto-selected if not provided)
            context_words: Optional context words (auto-selected if not provided)
            progression_service: Optional ProgressionService for word selection

        Returns:
            CaseGenerationResult or None if generation failed
        """
        # Get target word if not provided
        if target_word is None:
            if progression_service:
                target_word = await progression_service.select_target_word(
                    user_id, target_case, target_number
                )
            else:
                # Fallback: select any known word
                result = await self.session.execute(
                    select(Word)
                    .where(Word.is_known == True)  # noqa: E712
                    .order_by(Word.usage_count.asc())
                    .limit(1)
                )
                target_word = result.scalar_one_or_none()

            if target_word is None:
                return None

        # Get context words if not provided
        if context_words is None:
            if progression_service:
                context_words = await progression_service.select_context_words(
                    user_id,
                    exclude_word_id=target_word.id,
                    count=6,
                )
            else:
                result = await self.session.execute(
                    select(Word)
                    .where(
                        Word.is_known == True,  # noqa: E712
                        Word.id != target_word.id,
                    )
                    .limit(6)
                )
                context_words = list(result.scalars().all())

        # New flow: French sentence → Mintzaira translation
        # This produces grammatically correct Basque (unlike direct OpenAI Basque)
        try:
            # Step 1: Build French sentence using OpenAI
            french_result = await self.french_builder.build_sentence(
                target_word=target_word,
                context_words=context_words,
                target_case=target_case,
            )

            if not french_result or not french_result.sentence:
                print("French sentence generation failed")
                return None

            french_text = french_result.sentence

            # Step 2: Translate French to Basque using Mintzaira
            basque_text = await self.mintzaira.translate_fr_to_eu(french_text)

            if not basque_text:
                print("Mintzaira translation returned empty result")
                return None

            # Build words_used list from the French result
            words_used = [
                {"lemma": w, "form": w, "case": "unknown", "is_target": w == french_result.target_word_used}
                for w in french_result.words_used
            ]

            return CaseGenerationResult(
                basque_text=basque_text,
                french_text=french_text,
                target_word=target_word,
                target_case=target_case,
                target_number=target_number,
                target_form="",  # Mintzaira handles inflection automatically
                context_words=context_words,
                words_used=words_used,
                model_used=f"{self.settings.openai_model}+mintzaira",
                prompt_tokens=0,  # Not tracked in new flow
                completion_tokens=0,
            )

        except MintzairaError as e:
            print(f"Mintzaira translation error: {e}")
            return None
        except Exception as e:
            print(f"Case generation error: {e}")
            return None

    async def generate_and_save_for_case(
        self,
        user_id: int,
        target_case: GrammaticalCase,
        target_number: str,
        target_word: Word | None = None,
        progression_service: "ProgressionService | None" = None,
        tts_service: "TTSService | None" = None,
    ) -> Sentence | None:
        """
        Generate a case-specific sentence, save it, and optionally generate audio.

        Args:
            user_id: User ID
            target_case: Grammatical case to practice
            target_number: "singular" or "plural"
            target_word: Optional target word
            progression_service: Optional ProgressionService
            tts_service: Optional TTSService for audio generation

        Returns:
            Saved Sentence or None
        """
        result = await self.generate_for_case(
            user_id=user_id,
            target_case=target_case,
            target_number=target_number,
            target_word=target_word,
            progression_service=progression_service,
        )

        if not result or not result.basque_text:
            return None

        # Create sentence record
        sentence = Sentence(
            user_id=user_id,
            target_word_id=result.target_word.id,
            sentence_text=result.basque_text,
            french_text=result.french_text,
            translation=result.french_text,  # For compatibility
            language="eu",
            target_case_id=target_case.id,
            target_number=target_number,
            target_form=result.target_form,
            model_used=result.model_used,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )
        sentence.context_word_ids = [w.id for w in result.context_words]

        self.session.add(sentence)
        await self.session.flush()

        # Generate TTS audio if service provided
        if tts_service:
            try:
                basque_path, french_path = tts_service.generate_sentence_audio(
                    basque_text=result.basque_text,
                    french_text=result.french_text,
                    sentence_id=sentence.id,
                )
                sentence.audio_basque_path = str(basque_path)
                sentence.audio_french_path = str(french_path)
            except Exception as e:
                print(f"TTS generation failed: {e}")
                # Continue without audio

        # Record sentence generation in progression service
        if progression_service:
            # Build words_used list for tracking
            words_to_track = []
            for word_info in result.words_used:
                # Try to find matching word in our context
                lemma = word_info.get("lemma", "")
                matching_word = None

                if lemma == (result.target_word.basque_lemma or result.target_word.word):
                    matching_word = result.target_word
                else:
                    for w in result.context_words:
                        if (w.basque_lemma or w.word) == lemma:
                            matching_word = w
                            break

                if matching_word:
                    words_to_track.append((
                        matching_word,
                        word_info.get("case"),
                        word_info.get("form", lemma),
                        word_info.get("is_target", False),
                    ))

            await progression_service.record_sentence_generated(
                user_id=user_id,
                case_id=target_case.id,
                sentence=sentence,
                words_used=words_to_track,
            )

        await self.session.commit()
        return sentence
