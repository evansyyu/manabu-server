import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models import User
from app.sync.seq import reserve_sequences


@pytest.mark.asyncio
async def test_reserves_consecutive_blocks(session: AsyncSession):
    user = User()
    session.add(user)
    await session.flush()

    first = await reserve_sequences(session, user.id, 3)
    second = await reserve_sequences(session, user.id, 2)

    assert first == 1
    assert second == 4


@pytest.mark.asyncio
async def test_users_have_independent_counters(session: AsyncSession):
    a, b = User(), User()
    session.add_all([a, b])
    await session.flush()

    await reserve_sequences(session, a.id, 5)
    first_for_b = await reserve_sequences(session, b.id, 1)

    assert first_for_b == 1


@pytest.mark.asyncio
async def test_rejects_zero_count(session: AsyncSession):
    user = User()
    session.add(user)
    await session.flush()

    with pytest.raises(ValueError):
        await reserve_sequences(session, user.id, 0)


@pytest.mark.asyncio
async def test_concurrent_reservations_do_not_overlap():
    """Two real concurrent transactions must not hand out the same numbers.

    Uses its own committing sessions: the shared `session` fixture wraps
    everything in one transaction, which cannot exhibit lock contention
    against itself.
    """
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as setup:
        user = User()
        setup.add(user)
        await setup.commit()
        user_id = user.id

    async def reserve(n: int) -> int:
        async with factory() as s:
            first = await reserve_sequences(s, user_id, n)
            await asyncio.sleep(0.05)
            await s.commit()
            return first

    results = await asyncio.gather(*(reserve(10) for _ in range(5)))

    assert sorted(results) == [1, 11, 21, 31, 41]

    async with factory() as cleanup:
        await cleanup.delete(await cleanup.get(User, user_id))
        await cleanup.commit()

    await engine.dispose()