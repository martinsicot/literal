"""Tests for database models."""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from literal.models.sentence import Review, ReviewQuality, Sentence
from literal.models.user import MasteryLevel, User, UserWordState
from literal.models.word import Word


class TestWordModel:
    """Tests for Word model."""

    @pytest.mark.asyncio
    async def test_create_word(self, async_session, sample_word_data):
        """Test creating a word."""
        word = Word(**sample_word_data)
        async_session.add(word)
        await async_session.commit()

        assert word.id is not None
        assert word.word == "etxe"
        assert word.language == "eu"
        assert word.translation == "house"

    @pytest.mark.asyncio
    async def test_word_frequency_tier(self, async_session, sample_word_data):
        """Test frequency tier calculation."""
        word = Word(**sample_word_data)
        async_session.add(word)
        await async_session.commit()

        assert word.frequency_tier == "very_common"
        assert word.is_common is True

        # Test other tiers
        word.frequency_rank = 1500
        assert word.frequency_tier == "common"

        word.frequency_rank = 3000
        assert word.frequency_tier == "moderate"

        word.frequency_rank = 10000
        assert word.frequency_tier == "rare"

        word.frequency_rank = None
        assert word.frequency_tier == "unknown"

    @pytest.mark.asyncio
    async def test_word_repr(self, async_session, sample_word_data):
        """Test word string representation."""
        word = Word(**sample_word_data)
        async_session.add(word)
        await async_session.commit()

        repr_str = repr(word)
        assert "etxe" in repr_str
        assert "eu" in repr_str


class TestUserModel:
    """Tests for User model."""

    @pytest.mark.asyncio
    async def test_create_user(self, async_session, sample_user_data):
        """Test creating a user."""
        user = User(**sample_user_data)
        async_session.add(user)
        await async_session.commit()

        assert user.id is not None
        assert user.username == "testuser"
        assert user.email == "test@example.com"

    @pytest.mark.asyncio
    async def test_user_language_defaults(self, async_session):
        """Test user language defaults."""
        user = User(username="defaultuser")
        async_session.add(user)
        await async_session.commit()

        assert user.source_language == "eu"
        assert user.target_language == "en"


class TestUserWordStateModel:
    """Tests for UserWordState model."""

    @pytest.mark.asyncio
    async def test_create_user_word_state(self, async_session, sample_word_data, sample_user_data):
        """Test creating a user word state."""
        user = User(**sample_user_data)
        word = Word(**sample_word_data)
        async_session.add_all([user, word])
        await async_session.commit()

        state = UserWordState(user_id=user.id, word_id=word.id)
        async_session.add(state)
        await async_session.commit()

        assert state.id is not None
        assert state.repetitions == 0
        assert state.ease_factor == 2.5
        assert state.interval == 0
        assert state.mastery_level == 0

    @pytest.mark.asyncio
    async def test_mastery_level_new(self, async_session, sample_word_data, sample_user_data):
        """Test NEW mastery level for unreviewed words."""
        user = User(**sample_user_data)
        word = Word(**sample_word_data)
        async_session.add_all([user, word])
        await async_session.commit()

        state = UserWordState(user_id=user.id, word_id=word.id)
        async_session.add(state)
        await async_session.commit()

        assert state.calculate_mastery_level() == MasteryLevel.NEW
        assert state.is_target_candidate is True
        assert state.is_suitable_for_context is False

    @pytest.mark.asyncio
    async def test_mastery_level_learning(self, async_session, sample_word_data, sample_user_data):
        """Test LEARNING mastery level."""
        user = User(**sample_user_data)
        word = Word(**sample_word_data)
        async_session.add_all([user, word])
        await async_session.commit()

        state = UserWordState(
            user_id=user.id,
            word_id=word.id,
            repetitions=2,
            interval=3,
            ease_factor=2.5,
        )
        async_session.add(state)
        await async_session.commit()

        assert state.calculate_mastery_level() == MasteryLevel.LEARNING

    @pytest.mark.asyncio
    async def test_mastery_level_familiar(self, async_session, sample_word_data, sample_user_data):
        """Test FAMILIAR mastery level."""
        user = User(**sample_user_data)
        word = Word(**sample_word_data)
        async_session.add_all([user, word])
        await async_session.commit()

        state = UserWordState(
            user_id=user.id,
            word_id=word.id,
            repetitions=5,
            interval=14,
            ease_factor=2.2,
            mastery_level=MasteryLevel.FAMILIAR.value,
        )
        async_session.add(state)
        await async_session.commit()

        assert state.calculate_mastery_level() == MasteryLevel.FAMILIAR
        assert state.is_suitable_for_context is True

    @pytest.mark.asyncio
    async def test_mastery_level_known(self, async_session, sample_word_data, sample_user_data):
        """Test KNOWN mastery level."""
        user = User(**sample_user_data)
        word = Word(**sample_word_data)
        async_session.add_all([user, word])
        await async_session.commit()

        state = UserWordState(
            user_id=user.id,
            word_id=word.id,
            repetitions=10,
            interval=30,
            ease_factor=2.3,
        )
        async_session.add(state)
        await async_session.commit()

        assert state.calculate_mastery_level() == MasteryLevel.KNOWN

    @pytest.mark.asyncio
    async def test_mastery_level_mature(self, async_session, sample_word_data, sample_user_data):
        """Test MATURE mastery level."""
        user = User(**sample_user_data)
        word = Word(**sample_word_data)
        async_session.add_all([user, word])
        await async_session.commit()

        state = UserWordState(
            user_id=user.id,
            word_id=word.id,
            repetitions=20,
            interval=90,
            ease_factor=2.5,
        )
        async_session.add(state)
        await async_session.commit()

        assert state.calculate_mastery_level() == MasteryLevel.MATURE

    @pytest.mark.asyncio
    async def test_is_due(self, async_session, sample_word_data, sample_user_data):
        """Test is_due property."""
        user = User(**sample_user_data)
        word = Word(**sample_word_data)
        async_session.add_all([user, word])
        await async_session.commit()

        state = UserWordState(user_id=user.id, word_id=word.id)
        async_session.add(state)
        await async_session.commit()

        # No next_review set = due
        assert state.is_due is True

        # Future date = not due
        state.next_review = date.today() + timedelta(days=5)
        assert state.is_due is False

        # Past date = due
        state.next_review = date.today() - timedelta(days=2)
        assert state.is_due is True
        assert state.days_overdue == 2

    @pytest.mark.asyncio
    async def test_retention_rate(self, async_session, sample_word_data, sample_user_data):
        """Test retention rate calculation."""
        user = User(**sample_user_data)
        word = Word(**sample_word_data)
        async_session.add_all([user, word])
        await async_session.commit()

        state = UserWordState(
            user_id=user.id,
            word_id=word.id,
            total_reviews=10,
            successful_reviews=8,
        )
        async_session.add(state)
        await async_session.commit()

        assert state.retention_rate == 80.0

        # Zero reviews
        state.total_reviews = 0
        assert state.retention_rate == 0.0


class TestSentenceModel:
    """Tests for Sentence model."""

    @pytest.mark.asyncio
    async def test_create_sentence(self, async_session, sample_word_data, sample_user_data):
        """Test creating a sentence."""
        user = User(**sample_user_data)
        word = Word(**sample_word_data)
        async_session.add_all([user, word])
        await async_session.commit()

        sentence = Sentence(
            user_id=user.id,
            target_word_id=word.id,
            sentence_text="Etxe handia da.",
            translation="It is a big house.",
            language="eu",
        )
        async_session.add(sentence)
        await async_session.commit()

        assert sentence.id is not None
        assert sentence.sentence_text == "Etxe handia da."
        assert sentence.word_count == 3

    @pytest.mark.asyncio
    async def test_context_word_ids(self, async_session, sample_word_data, sample_user_data):
        """Test context word IDs JSON handling."""
        user = User(**sample_user_data)
        word = Word(**sample_word_data)
        async_session.add_all([user, word])
        await async_session.commit()

        sentence = Sentence(
            user_id=user.id,
            target_word_id=word.id,
            sentence_text="Test sentence",
            language="eu",
        )
        sentence.context_word_ids = [1, 2, 3]
        async_session.add(sentence)
        await async_session.commit()

        # Retrieve and verify
        result = await async_session.execute(
            select(Sentence).where(Sentence.id == sentence.id)
        )
        fetched = result.scalar_one()
        assert fetched.context_word_ids == [1, 2, 3]


class TestReviewModel:
    """Tests for Review model."""

    @pytest.mark.asyncio
    async def test_create_review(self, async_session, sample_word_data, sample_user_data):
        """Test creating a review."""
        user = User(**sample_user_data)
        word = Word(**sample_word_data)
        async_session.add_all([user, word])
        await async_session.commit()

        review = Review(
            user_id=user.id,
            word_id=word.id,
            quality=ReviewQuality.GOOD.value,
        )
        async_session.add(review)
        await async_session.commit()

        assert review.id is not None
        assert review.quality == 3
        assert review.is_successful is True
        assert review.quality_label == "Good"

    @pytest.mark.asyncio
    async def test_review_quality_labels(self, async_session, sample_word_data, sample_user_data):
        """Test review quality labels."""
        user = User(**sample_user_data)
        word = Word(**sample_word_data)
        async_session.add_all([user, word])
        await async_session.commit()

        # Test each quality level
        qualities = [
            (ReviewQuality.AGAIN.value, "Again", False),
            (ReviewQuality.HARD.value, "Hard", False),
            (ReviewQuality.GOOD.value, "Good", True),
            (ReviewQuality.EASY.value, "Easy", True),
        ]

        for quality, expected_label, expected_success in qualities:
            review = Review(
                user_id=user.id,
                word_id=word.id,
                quality=quality,
            )
            async_session.add(review)
            await async_session.commit()

            assert review.quality_label == expected_label
            assert review.is_successful == expected_success
