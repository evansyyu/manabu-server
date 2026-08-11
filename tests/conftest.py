import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db import get_session
from app.main import app


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.begin()
        async with AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as s:
            yield s
        await connection.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session):
    app.dependency_overrides[get_session] = lambda: session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()