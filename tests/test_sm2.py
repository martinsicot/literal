"""Tests for SM-2 algorithm service."""

from datetime import date, timedelta

import pytest

from literal.models.user import MasteryLevel, User, UserWordState
from literal.models.word import Word
from literal.services.sm2 import SM2Result, SM2Service


class TestSM2Algorithm:
    """Tests for SM-2 algorithm calculations."""

    @pytest.fixture
    def sm2_service(self, async_session):
        """Create SM2Service instance."""
        return SM2Service(async_session)

    def test_first_successful_review(self, sm2_service):
        """Test first successful review gives 1-day interval."""
        result = sm2_service.calculate_sm2(
            quality=3,
            repetitions=0,
            ease_factor=2.5,
            interval=0,
        )

        assert result.repetitions == 1
        assert result.interval == 1
        # SM-2 formula: EF' = EF + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
        # For q=3: EF' = 2.5 + (0.1 - 2 * (0.08 + 2 * 0.02)) = 2.5 + (0.1 - 0.24) = 2.36
        assert result.ease_factor == 2.36
        assert result.next_review == date.today() + timedelta(days=1)

    def test_second_successful_review(self, sm2_service):
        """Test second successful review gives 6-day interval."""
        result = sm2_service.calculate_sm2(
            quality=3,
            repetitions=1,
            ease_factor=2.5,
            interval=1,
        )

        assert result.repetitions == 2
        assert result.interval == 6
        assert result.next_review == date.today() + timedelta(days=6)

    def test_subsequent_review_uses_ease_factor(self, sm2_service):
        """Test subsequent reviews multiply interval by ease factor."""
        result = sm2_service.calculate_sm2(
            quality=3,
            repetitions=2,
            ease_factor=2.5,
            interval=6,
        )

        assert result.repetitions == 3
        assert result.interval == 15  # round(6 * 2.5)

    def test_failed_review_resets(self, sm2_service):
        """Test failed review resets repetitions and interval."""
        result = sm2_service.calculate_sm2(
            quality=1,  # Failed
            repetitions=5,
            ease_factor=2.5,
            interval=30,
        )

        assert result.repetitions == 0
        assert result.interval == 1

    def test_ease_factor_increases_on_easy(self, sm2_service):
        """Test ease factor increases for easy reviews."""
        result = sm2_service.calculate_sm2(
            quality=5,  # Easy
            repetitions=1,
            ease_factor=2.5,
            interval=1,
        )

        assert result.ease_factor > 2.5

    def test_ease_factor_decreases_on_hard(self, sm2_service):
        """Test ease factor decreases for hard reviews."""
        result = sm2_service.calculate_sm2(
            quality=2,  # Hard but passed
            repetitions=1,
            ease_factor=2.5,
            interval=1,
        )

        # Quality 2 is considered failed, so reps reset
        assert result.repetitions == 0
        # But ease factor should still decrease
        assert result.ease_factor < 2.5

    def test_ease_factor_minimum(self, sm2_service):
        """Test ease factor doesn't go below 1.3."""
        result = sm2_service.calculate_sm2(
            quality=0,  # Complete failure
            repetitions=1,
            ease_factor=1.4,
            interval=1,
        )

        assert result.ease_factor >= 1.3

    def test_mastery_level_new(self, sm2_service):
        """Test mastery level NEW for zero repetitions."""
        result = sm2_service.calculate_sm2(
            quality=0,
            repetitions=5,  # Reset to 0
            ease_factor=2.5,
            interval=30,
        )

        assert result.mastery_level == MasteryLevel.NEW

    def test_mastery_level_learning(self, sm2_service):
        """Test mastery level LEARNING for short intervals."""
        result = sm2_service.calculate_sm2(
            quality=3,
            repetitions=0,
            ease_factor=2.5,
            interval=0,
        )

        assert result.mastery_level == MasteryLevel.LEARNING

    def test_mastery_level_familiar(self, sm2_service):
        """Test mastery level FAMILIAR for 7+ day intervals."""
        result = sm2_service.calculate_sm2(
            quality=3,
            repetitions=2,
            ease_factor=2.2,
            interval=6,  # Will become ~13 days
        )

        # interval = round(6 * 2.2) = 13
        assert result.interval >= 7
        assert result.mastery_level == MasteryLevel.FAMILIAR

    def test_mastery_level_known(self, sm2_service):
        """Test mastery level KNOWN for 21+ day intervals with good ease."""
        result = sm2_service.calculate_sm2(
            quality=4,
            repetitions=5,
            ease_factor=2.3,
            interval=15,  # Will become ~35 days
        )

        # interval = round(15 * 2.3) = 35
        assert result.interval >= 21
        assert result.ease_factor >= 2.0
        assert result.mastery_level == MasteryLevel.KNOWN

    def test_mastery_level_mature(self, sm2_service):
        """Test mastery level MATURE for 60+ day intervals with high ease."""
        result = sm2_service.calculate_sm2(
            quality=5,  # Easy
            repetitions=10,
            ease_factor=2.5,
            interval=30,  # Will become 75 days
        )

        # interval = round(30 * 2.5) = 75
        assert result.interval >= 60
        assert result.ease_factor >= 2.3
        assert result.mastery_level == MasteryLevel.MATURE


class TestSM2ServiceIntegration:
    """Integration tests for SM2Service with database."""

    @pytest.fixture
    async def setup_data(self, async_session, sample_word_data, sample_user_data):
        """Set up test user and word."""
        user = User(**sample_user_data)
        word = Word(**sample_word_data)
        async_session.add_all([user, word])
        await async_session.commit()
        return user, word

    @pytest.mark.asyncio
    async def test_record_review_creates_state(self, async_session, setup_data):
        """Test recording review creates new word state."""
        user, word = setup_data
        service = SM2Service(async_session)

        state = await service.record_review(
            user_id=user.id,
            word_id=word.id,
            quality=3,
        )

        assert state is not None
        assert state.repetitions == 1
        assert state.interval == 1
        assert state.total_reviews == 1
        assert state.successful_reviews == 1

    @pytest.mark.asyncio
    async def test_record_review_updates_existing(self, async_session, setup_data):
        """Test recording review updates existing state."""
        user, word = setup_data
        service = SM2Service(async_session)

        # First review
        await service.record_review(user_id=user.id, word_id=word.id, quality=3)

        # Second review
        state = await service.record_review(
            user_id=user.id,
            word_id=word.id,
            quality=4,
        )

        assert state.repetitions == 2
        assert state.interval == 6
        assert state.total_reviews == 2

    @pytest.mark.asyncio
    async def test_record_review_failed_resets(self, async_session, setup_data):
        """Test failed review resets progress."""
        user, word = setup_data
        service = SM2Service(async_session)

        # Build up some progress
        await service.record_review(user_id=user.id, word_id=word.id, quality=3)
        await service.record_review(user_id=user.id, word_id=word.id, quality=3)
        await service.record_review(user_id=user.id, word_id=word.id, quality=3)

        # Fail
        state = await service.record_review(
            user_id=user.id,
            word_id=word.id,
            quality=1,  # Again
        )

        assert state.repetitions == 0
        assert state.interval == 1
        assert state.total_reviews == 4
        assert state.successful_reviews == 3

    @pytest.mark.asyncio
    async def test_get_due_words(self, async_session, setup_data):
        """Test getting due words."""
        user, word = setup_data
        service = SM2Service(async_session)

        # Create state with past due date
        state = UserWordState(
            user_id=user.id,
            word_id=word.id,
            next_review=date.today() - timedelta(days=1),
            repetitions=1,
            interval=1,
        )
        async_session.add(state)
        await async_session.commit()

        due_words = await service.get_due_words(user.id)

        assert len(due_words) >= 1
        assert any(s.word_id == word.id for s in due_words)

    @pytest.mark.asyncio
    async def test_get_context_words(self, async_session, setup_data):
        """Test getting context words."""
        user, word = setup_data
        service = SM2Service(async_session)

        # Create familiar word state
        state = UserWordState(
            user_id=user.id,
            word_id=word.id,
            mastery_level=MasteryLevel.FAMILIAR.value,
            repetitions=5,
            interval=14,
            ease_factor=2.2,
        )
        async_session.add(state)
        await async_session.commit()

        context = await service.get_context_words(
            user_id=user.id,
            language="eu",
            count=5,
        )

        assert len(context) >= 1
        assert word.id in [w.id for w in context]

    @pytest.mark.asyncio
    async def test_get_target_word(self, async_session, setup_data):
        """Test getting target word."""
        user, word = setup_data
        service = SM2Service(async_session)

        # Word has no state = new word = valid target
        target = await service.get_target_word(user.id, "eu")

        assert target is not None
        assert target.id == word.id
