"""FastAPI dependencies."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from literal.config import Settings, get_settings
from literal.models.base import get_async_session
from literal.services.anki import AnkiImporter
from literal.services.generator import SentenceGenerator
from literal.services.sm2 import SM2Service

# Type aliases for dependency injection
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session dependency."""
    async for session in get_async_session():
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_db)]


def get_openai_client(settings: SettingsDep) -> AsyncOpenAI:
    """Get OpenAI client dependency."""
    return AsyncOpenAI(api_key=settings.openai_api_key)


OpenAIDep = Annotated[AsyncOpenAI, Depends(get_openai_client)]


def get_sm2_service(session: SessionDep) -> SM2Service:
    """Get SM2 service dependency."""
    return SM2Service(session)


SM2Dep = Annotated[SM2Service, Depends(get_sm2_service)]


def get_anki_importer(session: SessionDep) -> AnkiImporter:
    """Get Anki importer dependency."""
    return AnkiImporter(session)


AnkiDep = Annotated[AnkiImporter, Depends(get_anki_importer)]


def get_sentence_generator(
    session: SessionDep,
    client: OpenAIDep,
) -> SentenceGenerator:
    """Get sentence generator dependency."""
    return SentenceGenerator(session, client)


GeneratorDep = Annotated[SentenceGenerator, Depends(get_sentence_generator)]
