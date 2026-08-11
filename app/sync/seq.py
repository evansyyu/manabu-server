import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserSyncState


async def reserve_sequences(
    session: AsyncSession, user_id: uuid.UUID, count: int, peek: bool = False
) -> int:
    """Reserve `count` consecutive sequence numbers for a user.

    Returns the first reserved number; the caller may use
    [first, first + count). With peek=True, returns the current high-water
    mark without reserving anything.

    Takes a row lock held until the enclosing transaction commits, which is
    what makes sequence order equal commit order. See
    docs/SYNC_PROTOCOL.md §3.
    """
    if count < 1 and not peek:
        raise ValueError("count must be at least 1")

    await session.execute(
        insert(UserSyncState)
        .values(user_id=user_id, seq_high=0)
        .on_conflict_do_nothing(index_elements=["user_id"])
    )

    result = await session.execute(
        select(UserSyncState)
        .where(UserSyncState.user_id == user_id)
        .with_for_update()
    )
    state = result.scalar_one()

    if peek:
        return state.seq_high

    first = state.seq_high + 1
    state.seq_high = state.seq_high + count
    await session.flush()

    return first