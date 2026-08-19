"""POST /diagnostics/crash — the crash-report intake.

The contract under test: unauthenticated intake, client_id-keyed dedupe
(re-delivered batches insert nothing twice), per-field truncation, the batch
cap, and non-UUID client_ids being dropped without rejecting their honest
batch-mates.
"""

import uuid

import pytest
from sqlalchemy import select

from app.diagnostics import MAX_MESSAGE_CHARS, MAX_REPORTS_PER_BATCH, MAX_STACK_CHARS
from app.models import CrashReport


def make_report(**overrides):
    report = {
        "client_id": str(uuid.uuid4()),
        "install_id": "install-abc",
        "platform": "ios",
        "os_version": "26.0",
        "app_version": "2.0.0",
        "kind": "error",
        "is_fatal": True,
        "message": "TypeError: undefined is not a function",
        "stack": "TypeError: undefined is not a function\n    at foo (index.js:1:1)",
        "occurred_at": 1_755_500_000_000,
    }
    report.update(overrides)
    return report


@pytest.mark.asyncio
async def test_accepts_a_batch_without_auth(client, session):
    reports = [make_report(), make_report(kind="rejection", is_fatal=False)]
    response = await client.post("/diagnostics/crash", json={"reports": reports})
    assert response.status_code == 204

    rows = (await session.execute(select(CrashReport))).scalars().all()
    assert {str(r.id) for r in rows} == {r["client_id"] for r in reports}
    by_kind = {r.kind for r in rows}
    assert by_kind == {"error", "rejection"}


@pytest.mark.asyncio
async def test_redelivery_dedupes_on_client_id(client, session):
    report = make_report()
    for _ in range(2):
        response = await client.post("/diagnostics/crash", json={"reports": [report]})
        assert response.status_code == 204

    rows = (await session.execute(select(CrashReport))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_truncates_oversized_text_fields(client, session):
    report = make_report(message="m" * (MAX_MESSAGE_CHARS + 500), stack="s" * (MAX_STACK_CHARS + 500))
    response = await client.post("/diagnostics/crash", json={"reports": [report]})
    assert response.status_code == 204

    row = (await session.execute(select(CrashReport))).scalars().one()
    assert len(row.message) == MAX_MESSAGE_CHARS
    assert len(row.stack) == MAX_STACK_CHARS


@pytest.mark.asyncio
async def test_rejects_oversized_batches(client, session):
    reports = [make_report() for _ in range(MAX_REPORTS_PER_BATCH + 1)]
    response = await client.post("/diagnostics/crash", json={"reports": reports})
    assert response.status_code == 422

    rows = (await session.execute(select(CrashReport))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_drops_non_uuid_client_ids_but_keeps_the_rest(client, session):
    good = make_report()
    bad = make_report(client_id="not-a-uuid")
    response = await client.post("/diagnostics/crash", json={"reports": [bad, good]})
    assert response.status_code == 204

    rows = (await session.execute(select(CrashReport))).scalars().all()
    assert [str(r.id) for r in rows] == [good["client_id"]]


@pytest.mark.asyncio
async def test_empty_batch_is_a_no_op(client, session):
    response = await client.post("/diagnostics/crash", json={"reports": []})
    assert response.status_code == 204
    rows = (await session.execute(select(CrashReport))).scalars().all()
    assert rows == []
