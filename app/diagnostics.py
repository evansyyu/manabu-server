"""Crash/error report intake — POST /diagnostics/crash.

Unauthenticated on purpose: a crash can happen signed-out, and the report
must not depend on a live token. The compensating controls are the rate
limit (per client IP, same slowapi setup as auth), a hard batch cap, and
per-field truncation — an abuser can waste a few rows, not disk.

Reports arrive in batches because the client queues them on disk and flushes
on the *next* launch: a dying process can't reliably complete a POST, so
"write locally, send later" is the only delivery that works for fatal
errors. Duplicate delivery is possible (flush succeeded, delete didn't);
`client_id` — the client's own UUID for the report — dedupes via ON CONFLICT
DO NOTHING on the primary key.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import CrashReport
from app.rate_limit import CRASH_REPORT_LIMIT, limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])

MAX_REPORTS_PER_BATCH = 20
MAX_MESSAGE_CHARS = 2_000
MAX_STACK_CHARS = 32_000


class CrashReportIn(BaseModel):
    # The client's UUID for this report — becomes the row's primary key so a
    # re-delivered batch inserts nothing twice.
    client_id: str = Field(min_length=1, max_length=64)
    install_id: str = Field(min_length=1, max_length=64)
    platform: str = Field(min_length=1, max_length=16)
    os_version: str = Field(default="", max_length=32)
    app_version: str = Field(default="", max_length=32)
    kind: str = Field(min_length=1, max_length=16)
    is_fatal: bool
    message: str = Field(default="")
    stack: str = Field(default="")
    occurred_at: int


class CrashBatch(BaseModel):
    reports: list[CrashReportIn] = Field(max_length=MAX_REPORTS_PER_BATCH)


@router.post("/crash", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(CRASH_REPORT_LIMIT)
async def report_crash(
    request: Request,
    body: CrashBatch,
    session: AsyncSession = Depends(get_session),
) -> None:
    if not body.reports:
        return
    rows = [
        {
            "id": report.client_id,
            "install_id": report.install_id,
            "platform": report.platform,
            "os_version": report.os_version,
            "app_version": report.app_version,
            "kind": report.kind,
            "is_fatal": report.is_fatal,
            "message": report.message[:MAX_MESSAGE_CHARS],
            "stack": report.stack[:MAX_STACK_CHARS],
            "occurred_at": report.occurred_at,
        }
        for report in body.reports
    ]
    # A malformed client_id (not a UUID) would fault the whole batch on the
    # UUID column; drop such rows rather than reject honest neighbours.
    valid_rows = []
    for row in rows:
        try:
            row["id"] = uuid.UUID(str(row["id"]))
            valid_rows.append(row)
        except ValueError:
            logger.warning("crash report with non-UUID client_id dropped")
    if not valid_rows:
        return
    statement = pg_insert(CrashReport).values(valid_rows).on_conflict_do_nothing(
        index_elements=["id"]
    )
    await session.execute(statement)
    await session.commit()
