"""Sentence generation service using OpenAI."""

import json
import random
from dataclasses import dataclass

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from literal.config import get_settings
from literal.models.sentence import Sentence
from literal.models.user import MasteryLevel, User, UserWordState
from literal.models.word import Word


@dataclass
class GenerationResult:
    """Result of sentence generation."""

    sentence: str
    translation: str
    target_word: Word
    context_words: list[Word]
    model_used: str
    prompt_tokens: int
    completion_tokens: int


class SentenceGenerator:
    """
    Generate i+1 sentences using OpenAI.

    Creates sentences that:
    - Use mostly known words as context
    - Introduce exactly one new/learning word
    - Make the target word's meaning clear from context
    """

    LANGUAGE_NAMES = {
        "eu": "Basque",
        "en": "English",
        "es": "Spanish",
        "fr": "French",
        "de": "German",
    }

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

    def _get_language_name(self, code: str) -> str:
        """Get full language name from code."""
        return self.LANGUAGE_NAMES.get(code, code.upper())

    async def get_context_words(
        self,
        user_id: int,
        language: str,
        count: int,
        exclude_ids: list[int] | None = None,
    ) -> list[Word]:
        """
        Get words suitable for use as context.

        Args:
            user_id: User ID
            language: Language code
            count: Number of words needed
            exclude_ids: Word IDs to exclude

        Returns:
            List of context words
        """
        exclude_ids = exclude_ids or []

        query = (
            select(Word)
            .join(UserWordState, UserWordState.word_id == Word.id)
            .where(
                UserWordState.user_id == user_id,
                UserWordState.mastery_level >= MasteryLevel.FAMILIAR.value,
                Word.language == language,
            )
        )

        if exclude_ids:
            query = query.where(Word.id.notin_(exclude_ids))

        # Add some randomization but prefer common words
        query = query.order_by(
            Word.frequency_rank.asc().nullslast()
        ).limit(count * 2)

        result = await self.session.execute(query)
        words = list(result.scalars().all())

        # Randomly select from top candidates
        if len(words) > count:
            words = random.sample(words, count)

        return words

    async def get_target_word(
        self,
        user_id: int,
        language: str,
    ) -> Word | None:
        """
        Get the next word to learn (the '+1').

        Args:
            user_id: User ID
            language: Language code

        Returns:
            Target word or None
        """
        # First: due words in learning state
        query = (
            select(Word)
            .join(UserWordState, UserWordState.word_id == Word.id)
            .where(
                UserWordState.user_id == user_id,
                UserWordState.mastery_level <= MasteryLevel.LEARNING.value,
                Word.language == language,
            )
            .order_by(Word.frequency_rank.asc().nullslast())
            .limit(1)
        )
        result = await self.session.execute(query)
        word = result.scalar_one_or_none()
        if word:
            return word

        # Second: new words without state
        subquery = select(UserWordState.word_id).where(
            UserWordState.user_id == user_id
        )
        result_sub = await self.session.execute(subquery)
        existing_ids = {row[0] for row in result_sub.all()}

        query = (
            select(Word)
            .where(
                Word.language == language,
            )
        )
        if existing_ids:
            query = query.where(Word.id.notin_(existing_ids))

        query = query.order_by(
            Word.frequency_rank.asc().nullslast()
        ).limit(1)

        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    def build_prompt(
        self,
        target_word: Word,
        context_words: list[Word],
        source_language: str,
        target_language: str,
    ) -> str:
        """
        Build the generation prompt.

        Args:
            target_word: Word to learn (the +1)
            context_words: Known words to use as context
            source_language: Language code of the sentence
            target_language: Translation language

        Returns:
            Formatted prompt string
        """
        lang_name = self._get_language_name(source_language)
        trans_lang = self._get_language_name(target_language)

        context_list = ", ".join([
            f"{w.word} ({w.translation or 'no translation'})"
            for w in context_words
        ])

        prompt = f"""Generate a natural {lang_name} sentence for language learning.

TARGET WORD (the word being learned):
- Word: {target_word.word}
- Translation: {target_word.translation or 'unknown'}
- Part of speech: {target_word.part_of_speech or 'unknown'}

KNOWN WORDS (use some of these as context):
{context_list}

REQUIREMENTS:
1. The sentence MUST include the target word "{target_word.word}"
2. Use 2-4 of the known words naturally in the sentence
3. The sentence should be {self.settings.min_sentence_length}-{self.settings.max_sentence_length} words
4. The meaning of "{target_word.word}" should be inferrable from context
5. Use natural, everyday language (not textbook-style)
6. The sentence should be grammatically correct in {lang_name}

RESPONSE FORMAT (JSON):
{{
    "sentence": "The {lang_name} sentence",
    "translation": "The {trans_lang} translation",
    "explanation": "Brief note on why this sentence helps learn the word"
}}

Generate the sentence:"""

        return prompt

    async def generate(
        self,
        user_id: int,
        target_word: Word | None = None,
        context_words: list[Word] | None = None,
    ) -> GenerationResult | None:
        """
        Generate an i+1 sentence.

        Args:
            user_id: User to generate for
            target_word: Optional target word (auto-selected if not provided)
            context_words: Optional context words (auto-selected if not provided)

        Returns:
            GenerationResult or None if generation failed
        """
        # Get user for language preferences
        user_result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            return None

        source_lang = user.source_language
        target_lang = user.target_language

        # Get target word if not provided
        if target_word is None:
            target_word = await self.get_target_word(user_id, source_lang)
            if target_word is None:
                return None

        # Get context words if not provided
        if context_words is None:
            context_words = await self.get_context_words(
                user_id=user_id,
                language=source_lang,
                count=8,
                exclude_ids=[target_word.id],
            )

        # Build prompt and call OpenAI
        prompt = self.build_prompt(
            target_word=target_word,
            context_words=context_words,
            source_language=source_lang,
            target_language=target_lang,
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a language learning assistant that generates "
                        "natural, contextual sentences for vocabulary practice. "
                        "Always respond with valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=500,
                response_format={"type": "json_object"},
            )

            # Parse response
            content = response.choices[0].message.content
            if not content:
                return None

            data = json.loads(content)

            return GenerationResult(
                sentence=data.get("sentence", ""),
                translation=data.get("translation", ""),
                target_word=target_word,
                context_words=context_words,
                model_used=self.settings.openai_model,
                prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                completion_tokens=response.usage.completion_tokens if response.usage else 0,
            )

        except Exception as e:
            # Log error and return None
            print(f"Generation error: {e}")
            return None

    async def generate_and_save(
        self,
        user_id: int,
        target_word: Word | None = None,
    ) -> Sentence | None:
        """
        Generate a sentence and save it to the database.

        Args:
            user_id: User to generate for
            target_word: Optional target word

        Returns:
            Saved Sentence or None
        """
        # Get user for language
        user_result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            return None

        result = await self.generate(user_id, target_word)
        if not result or not result.sentence:
            return None

        # Create sentence record
        sentence = Sentence(
            user_id=user_id,
            target_word_id=result.target_word.id,
            sentence_text=result.sentence,
            translation=result.translation,
            language=user.source_language,
            model_used=result.model_used,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )
        sentence.context_word_ids = [w.id for w in result.context_words]

        self.session.add(sentence)
        await self.session.flush()

        return sentence
