"""SM-2 Spaced Repetition Algorithm implementation."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from literal.models.sentence import Review
from literal.models.user import MasteryLevel, UserWordState
from literal.models.word import Word


@dataclass
class SM2Result:
    """Result of SM-2 calculation after a review."""

    repetitions: int
    ease_factor: float
    interval: int
    next_review: date
    mastery_level: MasteryLevel


class SM2Service:
    """
    SM-2 Spaced Repetition Algorithm Service.

    Implements the SuperMemo 2 algorithm for scheduling reviews
    and calculating word mastery levels.
    """

    # SM-2 constants
    MIN_EASE_FACTOR = 1.3
    DEFAULT_EASE_FACTOR = 2.5
    INITIAL_INTERVAL_1 = 1  # First successful review: 1 day
    INITIAL_INTERVAL_2 = 6  # Second successful review: 6 days

    def __init__(self, session: AsyncSession):
        self.session = session

    def calculate_sm2(
        self,
        quality: int,
        repetitions: int,
        ease_factor: float,
        interval: int,
    ) -> SM2Result:
        """
        Calculate new SM-2 state after a review.

        Args:
            quality: Review quality (0-5 scale)
            repetitions: Current successful repetition count
            ease_factor: Current ease factor
            interval: Current interval in days

        Returns:
            SM2Result with new state values
        """
        # Validate quality
        quality = max(0, min(5, quality))

        if quality >= 3:
            # Successful recall
            if repetitions == 0:
                new_interval = self.INITIAL_INTERVAL_1
            elif repetitions == 1:
                new_interval = self.INITIAL_INTERVAL_2
            else:
                new_interval = round(interval * ease_factor)

            new_repetitions = repetitions + 1
        else:
            # Failed recall - reset to beginning
            new_repetitions = 0
            new_interval = 1

        # Update ease factor based on quality
        # Formula: EF' = EF + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
        new_ease_factor = ease_factor + (
            0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
        )
        new_ease_factor = max(self.MIN_EASE_FACTOR, new_ease_factor)

        # Calculate next review date
        next_review = date.today() + timedelta(days=new_interval)

        # Calculate mastery level
        mastery_level = self._calculate_mastery(
            new_repetitions, new_interval, new_ease_factor
        )

        return SM2Result(
            repetitions=new_repetitions,
            ease_factor=round(new_ease_factor, 2),
            interval=new_interval,
            next_review=next_review,
            mastery_level=mastery_level,
        )

    def _calculate_mastery(
        self, repetitions: int, interval: int, ease_factor: float
    ) -> MasteryLevel:
        """Calculate mastery level from SM-2 state."""
        if repetitions == 0 or interval == 0:
            return MasteryLevel.NEW

        if interval >= 60 and ease_factor >= 2.3:
            return MasteryLevel.MATURE

        if interval >= 21 and ease_factor >= 2.0:
            return MasteryLevel.KNOWN

        if interval >= 7:
            return MasteryLevel.FAMILIAR

        return MasteryLevel.LEARNING

    async def record_review(
        self,
        user_id: int,
        word_id: int,
        quality: int,
        sentence_id: int | None = None,
        session_id: str | None = None,
        response_time_ms: int | None = None,
    ) -> UserWordState:
        """
        Record a review and update word state.

        Args:
            user_id: User performing the review
            word_id: Word being reviewed
            quality: Review quality (0-5)
            sentence_id: Optional sentence context
            session_id: Optional session identifier
            response_time_ms: Optional response time

        Returns:
            Updated UserWordState
        """
        # Get or create word state
        result = await self.session.execute(
            select(UserWordState).where(
                UserWordState.user_id == user_id,
                UserWordState.word_id == word_id,
            )
        )
        state = result.scalar_one_or_none()

        if state is None:
            state = UserWordState(
                user_id=user_id,
                word_id=word_id,
                repetitions=0,
                ease_factor=self.DEFAULT_EASE_FACTOR,
                interval=0,
                total_reviews=0,
                successful_reviews=0,
                mastery_level=0,
            )
            self.session.add(state)

        # Store previous state for review record
        ease_before = state.ease_factor
        interval_before = state.interval

        # Calculate new state
        sm2_result = self.calculate_sm2(
            quality=quality,
            repetitions=state.repetitions,
            ease_factor=state.ease_factor,
            interval=state.interval,
        )

        # Update word state
        state.repetitions = sm2_result.repetitions
        state.ease_factor = sm2_result.ease_factor
        state.interval = sm2_result.interval
        state.next_review = sm2_result.next_review
        state.last_review = datetime.now(UTC)
        state.total_reviews += 1
        if quality >= 3:
            state.successful_reviews += 1
        state.mastery_level = sm2_result.mastery_level.value

        # Create review record
        review = Review(
            user_id=user_id,
            word_id=word_id,
            sentence_id=sentence_id,
            quality=quality,
            reviewed_at=datetime.now(UTC),
            ease_factor_before=ease_before,
            interval_before=interval_before,
            ease_factor_after=state.ease_factor,
            interval_after=state.interval,
            session_id=session_id,
            response_time_ms=response_time_ms,
        )
        self.session.add(review)

        await self.session.flush()
        return state

    async def get_due_words(
        self,
        user_id: int,
        limit: int = 20,
        include_new: bool = True,
    ) -> list[UserWordState]:
        """
        Get words due for review.

        Args:
            user_id: User to get words for
            limit: Maximum number of words
            include_new: Whether to include new (unseen) words

        Returns:
            List of UserWordState objects due for review
        """
        # Get overdue and due words
        query = (
            select(UserWordState)
            .where(
                UserWordState.user_id == user_id,
                UserWordState.next_review <= date.today(),
            )
            .order_by(UserWordState.next_review)
            .limit(limit)
        )
        result = await self.session.execute(query)
        due_words = list(result.scalars().all())

        # If we need more words and include_new is True,
        # find words without any state (never reviewed)
        if len(due_words) < limit and include_new:
            remaining = limit - len(due_words)
            # Get word IDs that already have state for this user
            existing_word_ids_query = select(UserWordState.word_id).where(
                UserWordState.user_id == user_id
            )
            existing_result = await self.session.execute(existing_word_ids_query)
            existing_ids = {row[0] for row in existing_result.all()}

            # Get new words (not in user's vocabulary yet)
            new_words_query = (
                select(Word)
                .where(Word.id.notin_(existing_ids) if existing_ids else True)
                .order_by(Word.frequency_rank.asc().nullslast())
                .limit(remaining)
            )
            new_words_result = await self.session.execute(new_words_query)
            new_words = list(new_words_result.scalars().all())

            # Create states for new words
            for word in new_words:
                state = UserWordState(
                    user_id=user_id,
                    word_id=word.id,
                    repetitions=0,
                    ease_factor=self.DEFAULT_EASE_FACTOR,
                    interval=0,
                    next_review=date.today(),
                    total_reviews=0,
                    successful_reviews=0,
                    mastery_level=0,
                )
                self.session.add(state)
                due_words.append(state)

            if new_words:
                await self.session.flush()

        return due_words

    async def get_context_words(
        self,
        user_id: int,
        language: str,
        count: int = 10,
        exclude_word_ids: list[int] | None = None,
    ) -> list[Word]:
        """
        Get words suitable for use as context in i+1 sentences.

        Args:
            user_id: User to get words for
            language: Target language
            count: Number of context words needed
            exclude_word_ids: Word IDs to exclude

        Returns:
            List of Word objects suitable for context
        """
        exclude_ids = exclude_word_ids or []

        # Get words with FAMILIAR or higher mastery
        query = (
            select(Word)
            .join(UserWordState, UserWordState.word_id == Word.id)
            .where(
                UserWordState.user_id == user_id,
                UserWordState.mastery_level >= MasteryLevel.FAMILIAR.value,
                Word.language == language,
                Word.id.notin_(exclude_ids) if exclude_ids else True,
            )
            .order_by(Word.frequency_rank.asc().nullslast())
            .limit(count)
        )

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_target_word(
        self,
        user_id: int,
        language: str,
    ) -> Word | None:
        """
        Get the next word to learn (the '+1' in i+1).

        Prioritizes:
        1. Due words in LEARNING state
        2. New words (never seen)
        3. Words sorted by frequency (most common first)

        Args:
            user_id: User to get word for
            language: Target language

        Returns:
            Word to use as target, or None if no suitable word
        """
        # First try: due words in learning state
        query = (
            select(Word)
            .join(UserWordState, UserWordState.word_id == Word.id)
            .where(
                UserWordState.user_id == user_id,
                UserWordState.mastery_level <= MasteryLevel.LEARNING.value,
                UserWordState.next_review <= date.today(),
                Word.language == language,
            )
            .order_by(UserWordState.next_review.asc())
            .limit(1)
        )
        result = await self.session.execute(query)
        word = result.scalar_one_or_none()
        if word:
            return word

        # Second try: new words (no state yet)
        existing_word_ids_query = select(UserWordState.word_id).where(
            UserWordState.user_id == user_id
        )
        existing_result = await self.session.execute(existing_word_ids_query)
        existing_ids = {row[0] for row in existing_result.all()}

        query = (
            select(Word)
            .where(
                Word.language == language,
                Word.id.notin_(existing_ids) if existing_ids else True,
            )
            .order_by(Word.frequency_rank.asc().nullslast())
            .limit(1)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
