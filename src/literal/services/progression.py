"""Progression service for managing case level advancement and word selection."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from literal.models import (
    GrammaticalCase,
    Sentence,
    SentenceWord,
    UserCaseProgress,
    Word,
)


@dataclass
class ProgressionConfig:
    """Configuration for progression thresholds."""

    # Number of sentences required per case for Level 1
    level_1_sentences_per_case: int = 30
    # Minimum avg interval (days) needed to unlock next level
    level_unlock_avg_interval: int = 21
    # Minimum interval (days) for a word to be considered "known"
    known_word_interval_days: int = 14
    # Minimum number of sentences each word should appear in
    min_sentences_per_word: int = 3
    # Threshold to introduce next case within Level 1 (50% mastery)
    # Next case unlocks when current case has this % of sentences with good intervals
    case_introduction_threshold: float = 0.5


class ProgressionService:
    """
    Manage case level progression and word selection for sentence generation.

    Handles:
    - Tracking which level the user has unlocked (1-4)
    - Selecting the next case to practice
    - Selecting target words for sentences
    - Checking level unlock conditions
    """

    def __init__(
        self,
        session: AsyncSession,
        config: ProgressionConfig | None = None,
    ):
        self.session = session
        self.config = config or ProgressionConfig()

    # ==================== Level Management ====================

    async def get_current_level(self, user_id: int) -> int:
        """
        Return the highest unlocked level for the user (1-4).

        Level 1 is always unlocked by default.
        """
        result = await self.session.execute(
            select(func.max(GrammaticalCase.level))
            .join(UserCaseProgress, UserCaseProgress.case_id == GrammaticalCase.id)
            .where(
                UserCaseProgress.user_id == user_id,
                UserCaseProgress.unlocked == True,  # noqa: E712
            )
        )
        max_level = result.scalar_one_or_none()
        return max_level if max_level is not None else 1

    async def get_available_cases(self, user_id: int) -> list[GrammaticalCase]:
        """
        Return cases available for practice at current level.

        A case is available if:
        1. It's unlocked for this user
        2. It hasn't reached the sentence quota yet
        """
        current_level = await self.get_current_level(user_id)

        # Get all cases at current level with their progress
        result = await self.session.execute(
            select(GrammaticalCase, UserCaseProgress)
            .join(UserCaseProgress, UserCaseProgress.case_id == GrammaticalCase.id)
            .where(
                UserCaseProgress.user_id == user_id,
                UserCaseProgress.unlocked == True,  # noqa: E712
                GrammaticalCase.level == current_level,
            )
            .order_by(GrammaticalCase.id)
        )
        rows = result.all()

        available = []
        for case, progress in rows:
            # Check if case still needs sentences
            quota = self._get_sentence_quota(case.level)
            if progress.sentences_generated < quota:
                available.append(case)

        return available

    async def get_next_case_to_practice(
        self, user_id: int
    ) -> tuple[GrammaticalCase, str] | None:
        """
        Select next case and number to generate a sentence for.

        Returns (case, number) tuple where number is "singular" or "plural".

        For Level 1 (Core cases: absolutive, ergative, dative):
        - Sequential mastery: focus on one case at a time
        - Absolutive first, until quota reached
        - Ergative unlocks when 50% of absolutive sentences have good intervals
        - Dative unlocks when 50% of ergative sentences have good intervals
        - Keep building incomplete cases even after introducing new ones

        For other levels: balance across available cases.
        """
        current_level = await self.get_current_level(user_id)

        if current_level == 1:
            return await self._get_next_level_1_case(user_id)
        else:
            return await self._get_next_higher_level_case(user_id, current_level)

    async def _get_next_level_1_case(
        self, user_id: int
    ) -> tuple[GrammaticalCase, str] | None:
        """
        Level 1 sequential progression: absolutive → ergative → dative.
        
        Logic:
        1. Focus on current case until quota OR next case is unlocked
        2. Next case unlocks at 50% mastery of current case
        3. Continue building incomplete cases
        """
        # Get Level 1 cases in order (absolutive, ergative, dative)
        result = await self.session.execute(
            select(GrammaticalCase, UserCaseProgress)
            .join(UserCaseProgress, UserCaseProgress.case_id == GrammaticalCase.id)
            .where(
                UserCaseProgress.user_id == user_id,
                GrammaticalCase.level == 1,
            )
            .order_by(GrammaticalCase.id)  # Order: absolutive, ergative, dative
        )
        rows = result.all()

        if not rows:
            return None

        quota = self._get_sentence_quota(1)
        threshold = self.config.case_introduction_threshold

        # Determine which cases are "active" (can receive new sentences)
        active_cases: list[tuple[GrammaticalCase, UserCaseProgress]] = []
        
        for i, (case, progress) in enumerate(rows):
            # Case is active if it's unlocked and hasn't reached quota
            if not progress.unlocked:
                continue
            if progress.sentences_generated >= quota:
                continue
            
            # Check if this case should be active based on previous case mastery
            if i == 0:
                # First case (absolutive) is always active if unlocked
                active_cases.append((case, progress))
            else:
                # Later cases need previous case to have 50% mastery
                prev_case, prev_progress = rows[i - 1]
                prev_mastery = await self._calculate_case_mastery(user_id, prev_case.id)
                
                if prev_mastery >= threshold or prev_progress.sentences_generated >= quota:
                    active_cases.append((case, progress))

        if not active_cases:
            return None

        # Among active cases, prioritize the one with least sentences
        # This ensures we keep building earlier cases while introducing new ones
        active_cases.sort(key=lambda x: x[1].sentences_generated)
        case, progress = active_cases[0]

        # Determine singular vs plural
        singular_count = await self._count_sentences_by_number(user_id, case.id, "singular")
        plural_count = await self._count_sentences_by_number(user_id, case.id, "plural")
        number = "singular" if singular_count <= plural_count else "plural"

        return (case, number)

    async def _get_next_higher_level_case(
        self, user_id: int, level: int
    ) -> tuple[GrammaticalCase, str] | None:
        """For levels 2-4: balance across available cases."""
        result = await self.session.execute(
            select(GrammaticalCase, UserCaseProgress)
            .join(UserCaseProgress, UserCaseProgress.case_id == GrammaticalCase.id)
            .where(
                UserCaseProgress.user_id == user_id,
                UserCaseProgress.unlocked == True,  # noqa: E712
                GrammaticalCase.level == level,
            )
            .order_by(UserCaseProgress.sentences_generated, GrammaticalCase.id)
        )
        rows = result.all()

        for case, progress in rows:
            quota = self._get_sentence_quota(case.level)
            if progress.sentences_generated >= quota:
                continue

            singular_count = await self._count_sentences_by_number(user_id, case.id, "singular")
            plural_count = await self._count_sentences_by_number(user_id, case.id, "plural")
            number = "singular" if singular_count <= plural_count else "plural"
            return (case, number)

        return None

    async def _calculate_case_mastery(self, user_id: int, case_id: int) -> float:
        """
        Calculate mastery percentage for a case.
        
        Mastery = (sentences with interval >= threshold) / (total sentences)
        Returns 0.0 to 1.0
        """
        # Count total sentences for this case
        total = await self.session.scalar(
            select(func.count(Sentence.id)).where(
                Sentence.user_id == user_id,
                Sentence.target_case_id == case_id,
            )
        )
        
        if not total or total == 0:
            return 0.0

        # Count sentences with good interval (>= known threshold, e.g., 14 days)
        mastered = await self.session.scalar(
            select(func.count(Sentence.id)).where(
                Sentence.user_id == user_id,
                Sentence.target_case_id == case_id,
                Sentence.anki_interval >= self.config.known_word_interval_days,
            )
        )
        
        return (mastered or 0) / total

    async def _count_sentences_by_number(
        self, user_id: int, case_id: int, number: str
    ) -> int:
        """Count sentences for a specific case and grammatical number."""
        result = await self.session.scalar(
            select(func.count(Sentence.id)).where(
                Sentence.user_id == user_id,
                Sentence.target_case_id == case_id,
                Sentence.target_number == number,
            )
        )
        return result or 0

    def _get_sentence_quota(self, level: int) -> int:
        """Get sentence quota for a given level."""
        if level == 1:
            return self.config.level_1_sentences_per_case
        # For higher levels, use same quota (can be configured differently later)
        return self.config.level_1_sentences_per_case

    # ==================== Level Unlock ====================

    async def check_level_unlock(self, user_id: int) -> int | None:
        """
        Check if user should unlock the next level.

        Criteria: All cases at current level have:
        1. Reached sentence quota
        2. avg_interval > threshold

        Returns: The newly unlocked level number, or None if no unlock.
        """
        current_level = await self.get_current_level(user_id)

        if current_level >= 4:
            return None  # Already at max level

        # Check all cases at current level
        result = await self.session.execute(
            select(GrammaticalCase, UserCaseProgress)
            .join(UserCaseProgress, UserCaseProgress.case_id == GrammaticalCase.id)
            .where(
                UserCaseProgress.user_id == user_id,
                GrammaticalCase.level == current_level,
            )
        )
        rows = result.all()

        if not rows:
            return None

        all_mastered = True
        for case, progress in rows:
            quota = self._get_sentence_quota(case.level)

            # Check sentence quota
            if progress.sentences_generated < quota:
                all_mastered = False
                break

            # Check avg interval threshold
            if progress.avg_interval < self.config.level_unlock_avg_interval:
                all_mastered = False
                break

        if not all_mastered:
            return None

        # Unlock next level
        next_level = current_level + 1
        await self._unlock_level(user_id, next_level)
        return next_level

    async def _unlock_level(self, user_id: int, level: int) -> None:
        """Unlock all cases at the specified level for the user."""
        # Get cases at this level
        result = await self.session.execute(
            select(UserCaseProgress)
            .join(GrammaticalCase, GrammaticalCase.id == UserCaseProgress.case_id)
            .where(
                UserCaseProgress.user_id == user_id,
                GrammaticalCase.level == level,
            )
        )
        progress_records = result.scalars().all()

        for progress in progress_records:
            progress.unlocked = True
            progress.unlocked_at = datetime.now(UTC)

        await self.session.commit()

    # ==================== Word Selection ====================

    async def select_target_word(
        self,
        user_id: int,
        case: GrammaticalCase,
        number: str,
    ) -> Word | None:
        """
        Select a word to use as the target in a sentence.

        Priority:
        1. Known words (is_known=True) - required
        2. Lower usage_count (prioritize less-used words)
        3. Higher frequency_rank (more common words first)
        4. Not yet used in this specific case (novel practice)
        """
        # Get IDs of words already used in this case
        used_in_case_subq = (
            select(SentenceWord.word_id)
            .where(SentenceWord.case_used == case.name)
            .distinct()
        )

        # First try: known words not yet used in this case
        result = await self.session.execute(
            select(Word)
            .where(
                Word.is_known == True,  # noqa: E712
                ~Word.id.in_(used_in_case_subq),
            )
            .order_by(
                Word.usage_count.asc(),
                Word.frequency_rank.asc().nullsfirst(),
            )
            .limit(1)
        )
        word = result.scalar_one_or_none()

        if word:
            return word

        # Second try: known words with lowest usage (even if used in this case)
        result = await self.session.execute(
            select(Word)
            .where(
                Word.is_known == True,  # noqa: E712
                Word.usage_count < self.config.min_sentences_per_word,
            )
            .order_by(
                Word.usage_count.asc(),
                Word.frequency_rank.asc().nullsfirst(),
            )
            .limit(1)
        )
        word = result.scalar_one_or_none()

        if word:
            return word

        # Third try: any known word (for variety, pick random-ish)
        result = await self.session.execute(
            select(Word)
            .where(Word.is_known == True)  # noqa: E712
            .order_by(func.random())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def select_context_words(
        self,
        user_id: int,
        exclude_word_id: int | None = None,
        count: int = 6,
    ) -> list[Word]:
        """
        Select known words to use as context in a sentence.

        These are words the user already knows, used to construct
        comprehensible sentences with i+1 complexity.
        """
        query = select(Word).where(Word.is_known == True)  # noqa: E712

        if exclude_word_id:
            query = query.where(Word.id != exclude_word_id)

        # Mix of frequently used and less used for variety
        result = await self.session.execute(
            query.order_by(func.random()).limit(count)
        )
        return list(result.scalars().all())

    # ==================== Progress Updates ====================

    async def record_sentence_generated(
        self,
        user_id: int,
        case_id: int,
        sentence: Sentence,
        words_used: list[tuple[Word, str, str, bool]],
    ) -> None:
        """
        Record that a sentence was generated.

        Args:
            user_id: User ID
            case_id: Target case ID
            sentence: The generated sentence
            words_used: List of (word, case_used, form_used, is_target) tuples
        """
        # Update UserCaseProgress
        result = await self.session.execute(
            select(UserCaseProgress).where(
                UserCaseProgress.user_id == user_id,
                UserCaseProgress.case_id == case_id,
            )
        )
        progress = result.scalar_one_or_none()

        if progress:
            progress.sentences_generated += 1

        # Create SentenceWord records
        for position, (word, case_used, form_used, is_target) in enumerate(words_used):
            sw = SentenceWord(
                sentence_id=sentence.id,
                word_id=word.id,
                position=position,
                case_used=case_used,
                form_used=form_used,
                is_target=is_target,
                number=sentence.target_number if is_target else "singular",
            )
            self.session.add(sw)

            # Update word usage_count
            word.usage_count += 1

        await self.session.commit()

    async def get_known_word_count(self) -> int:
        """Get total count of known words."""
        result = await self.session.scalar(
            select(func.count(Word.id)).where(Word.is_known == True)  # noqa: E712
        )
        return result or 0

    async def get_words_needing_practice(self) -> list[Word]:
        """Get known words that have been used in fewer than min_sentences_per_word."""
        result = await self.session.execute(
            select(Word).where(
                Word.is_known == True,  # noqa: E712
                Word.usage_count < self.config.min_sentences_per_word,
            )
        )
        return list(result.scalars().all())
