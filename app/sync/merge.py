import uuid
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.sync.tables import SyncedTable


async def upsert_rows(
    session: AsyncSession,
    table: SyncedTable,
    user_id: uuid.UUID,
    device_id: str,
    rows: list[BaseModel],
    first_seq: int,
) -> list[list[str]]:
    """Conditionally upsert rows, newest-wins. Returns accepted PKs.

    Uses strictly `>` on updated_at, so a re-pushed identical batch accepts
    nothing and ties go to whichever push arrived first. See
    docs/SYNC_PROTOCOL.md §5.
    """
    if not rows:
        return []

    model = table.model
    now = datetime.now(UTC)
    conflict_cols = ["user_id", *table.pk]

    values = [
        {
            **row.model_dump(),
            "updated_at": getattr(row, table.watermark_field),
            "user_id": user_id,
            "server_seq": first_seq + i,
            "server_updated_at": now,
            "last_device_id": device_id,
        }
        for i, row in enumerate(rows)
    ]

    stmt = insert(model).values(values)
    update_cols = {
        c.name: stmt.excluded[c.name]
        for c in model.__table__.columns
        if c.name not in conflict_cols
    }

    stmt = stmt.on_conflict_do_update(
        index_elements=conflict_cols,
        set_=update_cols,
        where=stmt.excluded.updated_at > model.updated_at,
    ).returning(*(getattr(model, col) for col in table.pk))

    result = await session.execute(stmt)
    return [[str(v) for v in row] for row in result.all()]