"""FastAPI routes for Literal application."""

import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, UploadFile
from sqlalchemy import func, select

from literal.api.deps import AnkiDep, GeneratorDep, SessionDep, SM2Dep
from literal.api.schemas import (
    ImportRequest,
    ImportResponse,
    PaginatedResponse,
    ReviewRequest,
    ReviewResponse,
    SentenceResponse,
    SessionResponse,
    StatsResponse,
    UserCreate,
    UserResponse,
    WordCreate,
    WordResponse,
    WordWithMastery,
)
from literal.models.sentence import Review, Sentence
from literal.models.user import MasteryLevel, User, UserWordState
from literal.models.word import Word
from literal.services.progression import ProgressionService

router = APIRouter()

MASTERY_NAMES = {
    0: "new",
    1: "learning",
    2: "familiar",
    3: "known",
    4: "mature",
}


# User endpoints
@router.post("/users", response_model=UserResponse, tags=["users"])
async def create_user(
    user_data: UserCreate,
    session: SessionDep,
) -> User:
    """Create a new user."""
    # Check if username exists
    existing = await session.execute(
        select(User).where(User.username == user_data.username)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")

    user = User(**user_data.model_dump())
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.get("/users/{user_id}", response_model=UserResponse, tags=["users"])
async def get_user(
    user_id: int,
    session: SessionDep,
) -> User:
    """Get user by ID."""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# Word endpoints
@router.get("/words", response_model=PaginatedResponse, tags=["words"])
async def list_words(
    session: SessionDep,
    user_id: int = Query(..., description="User ID for mastery info"),
    language: str = Query("eu", description="Language filter"),
    mastery_level: int | None = Query(None, description="Filter by mastery level"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> dict:
    """List words with user mastery info."""
    # Base query with user state
    query = (
        select(Word, UserWordState)
        .outerjoin(
            UserWordState,
            (UserWordState.word_id == Word.id) & (UserWordState.user_id == user_id),
        )
        .where(Word.language == language)
    )

    if mastery_level is not None:
        if mastery_level == 0:
            # NEW = no state or mastery_level = 0
            query = query.where(
                (UserWordState.id == None) | (UserWordState.mastery_level == 0)  # noqa: E711
            )
        else:
            query = query.where(UserWordState.mastery_level == mastery_level)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Paginate
    query = query.order_by(Word.frequency_rank.asc().nullslast())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(query)
    rows = result.all()

    # Build response
    items = []
    for word, state in rows:
        mastery = state.mastery_level if state else 0
        item = WordWithMastery(
            id=word.id,
            word=word.word,
            language=word.language,
            translation=word.translation,
            definition=word.definition,
            part_of_speech=word.part_of_speech,
            frequency_rank=word.frequency_rank,
            frequency_tier=word.frequency_tier,
            created_at=word.created_at,
            mastery_level=mastery,
            mastery_name=MASTERY_NAMES.get(mastery, "unknown"),
            next_review=state.next_review if state else None,
            interval=state.interval if state else 0,
            ease_factor=state.ease_factor if state else 2.5,
            is_due=(state.is_due if state else True),
        )
        items.append(item.model_dump())

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.post("/words", response_model=WordResponse, tags=["words"])
async def create_word(
    word_data: WordCreate,
    session: SessionDep,
) -> Word:
    """Create a new word."""
    word = Word(**word_data.model_dump())
    session.add(word)
    await session.commit()
    await session.refresh(word)
    return word


@router.get("/words/{word_id}", response_model=WordWithMastery, tags=["words"])
async def get_word(
    word_id: int,
    user_id: int,
    session: SessionDep,
) -> dict:
    """Get word with user mastery info."""
    result = await session.execute(
        select(Word, UserWordState)
        .outerjoin(
            UserWordState,
            (UserWordState.word_id == Word.id) & (UserWordState.user_id == user_id),
        )
        .where(Word.id == word_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Word not found")

    word, state = row
    mastery = state.mastery_level if state else 0

    return {
        "id": word.id,
        "word": word.word,
        "language": word.language,
        "translation": word.translation,
        "definition": word.definition,
        "part_of_speech": word.part_of_speech,
        "frequency_rank": word.frequency_rank,
        "frequency_tier": word.frequency_tier,
        "created_at": word.created_at,
        "mastery_level": mastery,
        "mastery_name": MASTERY_NAMES.get(mastery, "unknown"),
        "next_review": state.next_review if state else None,
        "interval": state.interval if state else 0,
        "ease_factor": state.ease_factor if state else 2.5,
        "is_due": state.is_due if state else True,
    }


# Review endpoints
@router.post("/reviews", response_model=ReviewResponse, tags=["reviews"])
async def record_review(
    review: ReviewRequest,
    user_id: int,
    sm2: SM2Dep,
) -> dict:
    """Record a word review."""
    state = await sm2.record_review(
        user_id=user_id,
        word_id=review.word_id,
        quality=review.quality,
        sentence_id=review.sentence_id,
        session_id=review.session_id,
        response_time_ms=review.response_time_ms,
    )

    return {
        "word_id": review.word_id,
        "new_interval": state.interval,
        "new_ease_factor": state.ease_factor,
        "next_review": state.next_review,
        "mastery_level": state.mastery_level,
        "mastery_name": MASTERY_NAMES.get(state.mastery_level, "unknown"),
    }


# Session endpoints
@router.get("/session", response_model=SessionResponse, tags=["session"])
async def get_session(
    user_id: int,
    session: SessionDep,
    generator: GeneratorDep,
    sm2: SM2Dep,
) -> dict:
    """Get next sentence for learning session."""
    # Get next case to practice from progression service
    progression = ProgressionService(session)
    case_and_number = await progression.get_next_case_to_practice(user_id)
    if not case_and_number:
        raise HTTPException(
            status_code=404,
            detail="No cases available. Seed grammatical cases first.",
        )

    target_case, target_number = case_and_number

    # Generate a new sentence using the case-aware flow
    sentence = await generator.generate_and_save_for_case(
        user_id=user_id,
        target_case=target_case,
        target_number=target_number,
        progression_service=progression,
    )

    if not sentence:
        raise HTTPException(
            status_code=404,
            detail="No words available for practice. Import an Anki deck first.",
        )

    # Get target word with mastery
    target_result = await session.execute(
        select(Word, UserWordState)
        .outerjoin(
            UserWordState,
            (UserWordState.word_id == Word.id) & (UserWordState.user_id == user_id),
        )
        .where(Word.id == sentence.target_word_id)
    )
    target_row = target_result.one()
    target_word, target_state = target_row
    target_mastery = target_state.mastery_level if target_state else 0

    # Get context words
    context_ids = sentence.context_word_ids
    context_words = []
    if context_ids:
        context_result = await session.execute(
            select(Word).where(Word.id.in_(context_ids))
        )
        context_words = list(context_result.scalars().all())

    return {
        "sentence": {
            "id": sentence.id,
            "sentence_text": sentence.sentence_text,
            "translation": sentence.translation,
            "target_word_id": sentence.target_word_id,
            "target_word": target_word.word,
            "target_word_translation": target_word.translation,
            "language": sentence.language,
            "word_count": sentence.word_count,
            "created_at": sentence.created_at,
        },
        "target_word": {
            "id": target_word.id,
            "word": target_word.word,
            "language": target_word.language,
            "translation": target_word.translation,
            "definition": target_word.definition,
            "part_of_speech": target_word.part_of_speech,
            "frequency_rank": target_word.frequency_rank,
            "frequency_tier": target_word.frequency_tier,
            "created_at": target_word.created_at,
            "mastery_level": target_mastery,
            "mastery_name": MASTERY_NAMES.get(target_mastery, "unknown"),
            "next_review": target_state.next_review if target_state else None,
            "interval": target_state.interval if target_state else 0,
            "ease_factor": target_state.ease_factor if target_state else 2.5,
            "is_due": target_state.is_due if target_state else True,
        },
        "context_words": [
            {
                "id": w.id,
                "word": w.word,
                "language": w.language,
                "translation": w.translation,
                "definition": w.definition,
                "part_of_speech": w.part_of_speech,
                "frequency_rank": w.frequency_rank,
                "frequency_tier": w.frequency_tier,
                "created_at": w.created_at,
            }
            for w in context_words
        ],
    }


# Import endpoints
@router.post("/import", response_model=ImportResponse, tags=["import"])
async def import_anki_deck(
    file: UploadFile,
    user_id: int,
    anki: AnkiDep,
    language: str = Query("eu"),
    import_reviews: bool = Query(True),
) -> dict:
    """Import an Anki deck (.apkg file)."""
    if not file.filename or not file.filename.endswith(".apkg"):
        raise HTTPException(
            status_code=400,
            detail="File must be an Anki deck (.apkg)",
        )

    # Save uploaded file to temp location
    with tempfile.NamedTemporaryFile(delete=False, suffix=".apkg") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        result = await anki.import_deck(
            apkg_path=tmp_path,
            user_id=user_id,
            language=language,
            import_reviews=import_reviews,
        )

        return {
            "words_imported": result.words_imported,
            "words_updated": result.words_updated,
            "words_skipped": result.words_skipped,
            "reviews_imported": result.reviews_imported,
            "errors": result.errors,
        }
    finally:
        tmp_path.unlink(missing_ok=True)


# Statistics endpoints
@router.get("/stats", response_model=StatsResponse, tags=["stats"])
async def get_stats(
    user_id: int,
    session: SessionDep,
) -> dict:
    """Get user learning statistics."""
    # Total words
    total_result = await session.execute(
        select(func.count(UserWordState.id)).where(UserWordState.user_id == user_id)
    )
    total_words = total_result.scalar() or 0

    # Words by mastery
    mastery_result = await session.execute(
        select(UserWordState.mastery_level, func.count(UserWordState.id))
        .where(UserWordState.user_id == user_id)
        .group_by(UserWordState.mastery_level)
    )
    words_by_mastery = {
        MASTERY_NAMES.get(level, "unknown"): count
        for level, count in mastery_result.all()
    }

    # Words due today
    due_result = await session.execute(
        select(func.count(UserWordState.id)).where(
            UserWordState.user_id == user_id,
            UserWordState.next_review <= date.today(),
        )
    )
    words_due_today = due_result.scalar() or 0

    # Reviews today
    today_start = datetime.combine(date.today(), datetime.min.time())
    reviews_today_result = await session.execute(
        select(func.count(Review.id)).where(
            Review.user_id == user_id,
            Review.reviewed_at >= today_start,
        )
    )
    reviews_today = reviews_today_result.scalar() or 0

    # Reviews this week
    week_start = today_start - timedelta(days=7)
    reviews_week_result = await session.execute(
        select(func.count(Review.id)).where(
            Review.user_id == user_id,
            Review.reviewed_at >= week_start,
        )
    )
    reviews_this_week = reviews_week_result.scalar() or 0

    # Average retention
    retention_result = await session.execute(
        select(
            func.sum(UserWordState.successful_reviews),
            func.sum(UserWordState.total_reviews),
        ).where(UserWordState.user_id == user_id)
    )
    success, total = retention_result.one()
    average_retention = (success / total * 100) if total and total > 0 else 0.0

    # Streak (simplified - count consecutive days with reviews)
    # This is a simplified version; a real implementation would be more complex
    streak_days = 0
    check_date = date.today()
    for _ in range(365):  # Max check 1 year
        day_start = datetime.combine(check_date, datetime.min.time())
        day_end = day_start + timedelta(days=1)
        day_reviews = await session.execute(
            select(func.count(Review.id)).where(
                Review.user_id == user_id,
                Review.reviewed_at >= day_start,
                Review.reviewed_at < day_end,
            )
        )
        if day_reviews.scalar() or 0 > 0:
            streak_days += 1
            check_date -= timedelta(days=1)
        else:
            break

    # Anki-synced vocabulary stats from Word table
    vocab_total_result = await session.execute(select(func.count(Word.id)))
    vocabulary_total = vocab_total_result.scalar() or 0

    vocab_known_result = await session.execute(
        select(func.count(Word.id)).where(Word.is_known == True)  # noqa: E712
    )
    vocabulary_known = vocab_known_result.scalar() or 0

    vocab_learning_result = await session.execute(
        select(func.count(Word.id)).where(
            Word.anki_interval > 0,
            Word.anki_interval < 14,
        )
    )
    vocabulary_learning = vocab_learning_result.scalar() or 0

    vocabulary_new = vocabulary_total - vocabulary_known - vocabulary_learning

    avg_interval_result = await session.execute(
        select(func.avg(Word.anki_interval)).where(Word.anki_interval > 0)
    )
    anki_avg_interval = avg_interval_result.scalar() or 0.0

    return {
        "total_words": total_words,
        "words_by_mastery": words_by_mastery,
        "words_due_today": words_due_today,
        "reviews_today": reviews_today,
        "reviews_this_week": reviews_this_week,
        "average_retention": round(average_retention, 1),
        "streak_days": streak_days,
        "vocabulary_total": vocabulary_total,
        "vocabulary_known": vocabulary_known,
        "vocabulary_learning": vocabulary_learning,
        "vocabulary_new": vocabulary_new,
        "anki_avg_interval": round(anki_avg_interval, 1),
    }
