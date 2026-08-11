import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.sync.tables import TABLES, SyncedTable


async def fetch_changes(
    session: AsyncSession, user_id: uuid.UUID, since: int, limit: int
) -> tuple[list[tuple[SyncedTable, int, dict]], bool]:
    """Fetch up to `limit` rows across all tables, ordered by server_seq.

    Returns (rows, has_more). Each table is queried for limit+1 rows so the
    merged result can be truncated correctly; see docs/SYNC_PROTOCOL.md §4.
    """
    merged: list[tuple[SyncedTable, int, dict]] = []

    for table in TABLES:
        model = table.model
        result = await session.execute(
            select(model)
            .where(model.user_id == user_id, model.server_seq > since)
            .order_by(model.server_seq)
            .limit(limit + 1)
        )
        for obj in result.scalars():
            payload = {col: getattr(obj, col) for col in table.wire_columns}
            merged.append((table, obj.server_seq, payload))

    merged.sort(key=lambda item: item[1])

    has_more = len(merged) > limit
    return merged[:limit], has_more