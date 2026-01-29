"""Tests for API endpoints."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from literal.api.routes import router
from literal.models.base import Base
from literal.models.sentence import Sentence
from literal.models.user import MasteryLevel, User, UserWordState
from literal.models.word import Word


@pytest.fixture
async def test_app(async_engine):
    """Create test FastAPI application."""
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


@pytest.fixture
async def test_client(test_app, async_session):
    """Create test client with database session override."""
    from literal.api.deps import get_db

    async def override_get_db():
        yield async_session

    test_app.dependency_overrides[get_db] = override_get_db

    # Create sync test client
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as client:
        yield client


class TestUserEndpoints:
    """Tests for user endpoints."""

    @pytest.mark.asyncio
    async def test_create_user(self, test_client):
        """Test creating a user."""
        response = await test_client.post(
            "/api/users",
            json={
                "username": "testuser",
                "email": "test@example.com",
                "source_language": "eu",
                "target_language": "en",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"
        assert data["email"] == "test@example.com"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_create_duplicate_user(self, test_client):
        """Test creating duplicate user fails."""
        user_data = {"username": "duplicateuser"}

        # Create first user
        await test_client.post("/api/users", json=user_data)

        # Try to create duplicate
        response = await test_client.post("/api/users", json=user_data)
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_get_user(self, test_client):
        """Test getting a user."""
        # Create user
        create_response = await test_client.post(
            "/api/users",
            json={"username": "getuser"},
        )
        user_id = create_response.json()["id"]

        # Get user
        response = await test_client.get(f"/api/users/{user_id}")
        assert response.status_code == 200
        assert response.json()["username"] == "getuser"

    @pytest.mark.asyncio
    async def test_get_nonexistent_user(self, test_client):
        """Test getting nonexistent user returns 404."""
        response = await test_client.get("/api/users/99999")
        assert response.status_code == 404


class TestWordEndpoints:
    """Tests for word endpoints."""

    @pytest.mark.asyncio
    async def test_create_word(self, test_client):
        """Test creating a word."""
        response = await test_client.post(
            "/api/words",
            json={
                "word": "etxe",
                "language": "eu",
                "translation": "house",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["word"] == "etxe"
        assert data["translation"] == "house"

    @pytest.mark.asyncio
    async def test_list_words(self, test_client, async_session):
        """Test listing words."""
        # Create user and word
        user = User(username="listwordsuser")
        word = Word(word="kaixo", language="eu", translation="hello")
        async_session.add_all([user, word])
        await async_session.commit()

        response = await test_client.get(
            f"/api/words?user_id={user.id}&language=eu"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert any(w["word"] == "kaixo" for w in data["items"])

    @pytest.mark.asyncio
    async def test_list_words_by_mastery(self, test_client, async_session):
        """Test filtering words by mastery level."""
        # Create user, word, and state
        user = User(username="masteryuser")
        word = Word(word="agur", language="eu", translation="goodbye")
        async_session.add_all([user, word])
        await async_session.commit()

        state = UserWordState(
            user_id=user.id,
            word_id=word.id,
            mastery_level=MasteryLevel.FAMILIAR.value,
        )
        async_session.add(state)
        await async_session.commit()

        # Filter by familiar
        response = await test_client.get(
            f"/api/words?user_id={user.id}&language=eu&mastery_level=2"
        )

        assert response.status_code == 200
        data = response.json()
        assert all(w["mastery_level"] == 2 for w in data["items"])

    @pytest.mark.asyncio
    async def test_get_word_with_mastery(self, test_client, async_session):
        """Test getting a single word with mastery info."""
        # Create user and word
        user = User(username="getworduser")
        word = Word(word="liburu", language="eu", translation="book")
        async_session.add_all([user, word])
        await async_session.commit()

        response = await test_client.get(
            f"/api/words/{word.id}?user_id={user.id}"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["word"] == "liburu"
        assert data["mastery_level"] == 0  # New word


class TestReviewEndpoints:
    """Tests for review endpoints."""

    @pytest.mark.asyncio
    async def test_record_review(self, test_client, async_session):
        """Test recording a review."""
        # Create user and word
        user = User(username="reviewuser")
        word = Word(word="ura", language="eu", translation="water")
        async_session.add_all([user, word])
        await async_session.commit()

        response = await test_client.post(
            f"/api/reviews?user_id={user.id}",
            json={
                "word_id": word.id,
                "quality": 3,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["word_id"] == word.id
        assert data["new_interval"] == 1
        assert data["mastery_level"] == 1  # Learning

    @pytest.mark.asyncio
    async def test_record_review_progression(self, test_client, async_session):
        """Test review progression through mastery levels."""
        user = User(username="progressuser")
        word = Word(word="ogia", language="eu", translation="bread")
        async_session.add_all([user, word])
        await async_session.commit()

        # First review
        response1 = await test_client.post(
            f"/api/reviews?user_id={user.id}",
            json={"word_id": word.id, "quality": 3},
        )
        assert response1.json()["new_interval"] == 1

        # Second review
        response2 = await test_client.post(
            f"/api/reviews?user_id={user.id}",
            json={"word_id": word.id, "quality": 3},
        )
        assert response2.json()["new_interval"] == 6


class TestStatsEndpoints:
    """Tests for statistics endpoints."""

    @pytest.mark.asyncio
    async def test_get_stats_empty(self, test_client, async_session):
        """Test getting stats for user with no data."""
        user = User(username="statsuser")
        async_session.add(user)
        await async_session.commit()

        response = await test_client.get(f"/api/stats?user_id={user.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["total_words"] == 0
        assert data["reviews_today"] == 0

    @pytest.mark.asyncio
    async def test_get_stats_with_data(self, test_client, async_session):
        """Test getting stats with some data."""
        user = User(username="statsdatauser")
        word = Word(word="mahaia", language="eu", translation="table")
        async_session.add_all([user, word])
        await async_session.commit()

        state = UserWordState(
            user_id=user.id,
            word_id=word.id,
            mastery_level=MasteryLevel.LEARNING.value,
            total_reviews=5,
            successful_reviews=4,
        )
        async_session.add(state)
        await async_session.commit()

        response = await test_client.get(f"/api/stats?user_id={user.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["total_words"] == 1
        assert "learning" in data["words_by_mastery"]


class TestSessionEndpoints:
    """Tests for session/learning endpoints."""

    @pytest.mark.asyncio
    async def test_get_session_no_words(self, test_client, async_session):
        """Test getting session when no words available."""
        user = User(username="sessionuser")
        async_session.add(user)
        await async_session.commit()

        # Mock the generator's generate_and_save to return None
        with patch(
            "literal.services.generator.SentenceGenerator.generate_and_save",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await test_client.get(f"/api/session?user_id={user.id}")
            assert response.status_code == 404


class TestImportEndpoints:
    """Tests for import endpoints."""

    @pytest.mark.asyncio
    async def test_import_invalid_file_type(self, test_client, async_session):
        """Test importing non-apkg file fails."""
        user = User(username="importuser")
        async_session.add(user)
        await async_session.commit()

        # Create a fake file
        from io import BytesIO

        file_content = BytesIO(b"not an anki file")

        response = await test_client.post(
            f"/api/import?user_id={user.id}&language=eu",
            files={"file": ("test.txt", file_content, "text/plain")},
        )

        assert response.status_code == 400
        assert "apkg" in response.json()["detail"].lower()
