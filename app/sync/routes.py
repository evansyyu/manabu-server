import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_session
from app.models import User
from app.sync.merge import upsert_rows
from app.sync.schemas import PushRequest, PushResponse
from app.sync.seq import reserve_sequences
from app.sync.tables import TABLES, is_denied_setting_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sync", tags=["sync"])

MAX_BATCH_ROWS = 500


def _dedupe(rows: list, pk: tuple[str, ...]) -> list:
    """Keep only the newest row per primary key.

    A single INSERT cannot touch the same conflict key twice; Postgres raises
    "cannot affect row a second time". Clients shouldn't send duplicates, but
    the server must not 500 if they do.
    """
    newest: dict[tuple, object] = {}
    for row in rows:
        key = tuple(getattr(row, col) for col in pk)
        existing = newest.get(key)
        if existing is None or row.updated_at > existing.updated_at:
            newest[key] = row
    return list(newest.values())


@router.post("/push", response_model=PushResponse)
async def push(
    body: PushRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PushResponse:
    batches = {t.name: list(getattr(body, t.name)) for t in TABLES}

    batches["settings"] = [
        r for r in batches["settings"] if not is_denied_setting_key(r.key)
    ]

    for table in TABLES:
        batches[table.name] = _dedupe(batches[table.name], table.pk)

    total = sum(len(rows) for rows in batches.values())
    if total > MAX_BATCH_ROWS:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Batch of {total} rows exceeds the {MAX_BATCH_ROWS} row limit",
        )

    accepted: dict[str, list[list[str]]] = {t.name: [] for t in TABLES}

    if total == 0:
        state_seq = await reserve_sequences(session, user.id, 0, peek=True)
        await session.commit()
        return PushResponse(accepted=accepted, server_seq_high=state_seq)

    first_seq = await reserve_sequences(session, user.id, total)

    next_seq = first_seq
    for table in TABLES:
        rows = batches[table.name]
        if not rows:
            continue
        accepted[table.name] = await upsert_rows(
            session, table, user.id, body.device_id, rows, next_seq
        )
        next_seq += len(rows)

    await session.commit()

    logger.info(
        "push user=%s device=%s sent=%d accepted=%d",
        user.id,
        body.device_id,
        total,
        sum(len(v) for v in accepted.values()),
    )

    return PushResponse(
        accepted=accepted, server_seq_high=first_seq + total - 1
    )