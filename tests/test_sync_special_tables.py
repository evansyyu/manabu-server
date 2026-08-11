import pytest
from sqlalchemy import select

from app.models import SrsDailyCounter, SrsItemTombstone

BASE = 1786468000000
DAY = "2026-08-11"


async def push(client, device_id="device-a", **changes):
    return await client.post(
        "/sync/push", json={"device_id": device_id, **changes}
    )


def counter(device_id: str, new_count: int = 5, **extra) -> dict:
    return {
        "category": "kana",
        "day": DAY,
        "device_id": device_id,
        "new_count": new_count,
        "review_count": 10,
        "updated_at": BASE,
        **extra,
    }


def activity(device_id: str, **extra) -> dict:
    return {
        "day": DAY,
        "device_id": device_id,
        "active_ms": 82466,
        "cards": 23,
        "updated_at": BASE,
        **extra,
    }


def tombstone(item_id: str, deleted_at: int = BASE) -> dict:
    return {
        "category": "kana",
        "item_id": item_id,
        "card_type": "default",
        "deleted_at": deleted_at,
    }


@pytest.mark.asyncio
async def test_device_can_push_own_rollup(auth_client, session):
    client, user = auth_client

    response = await push(
        client, srs_daily_counter=[counter("device-a")]
    )

    assert response.status_code == 200
    row = await session.scalar(
        select(SrsDailyCounter).where(SrsDailyCounter.user_id == user.id)
    )
    assert row.new_count == 5
    assert row.device_id == "device-a"


@pytest.mark.asyncio
async def test_foreign_device_rollup_rejected(auth_client):
    client, _ = auth_client

    response = await push(
        client, device_id="device-a", srs_daily_counter=[counter("device-b")]
    )

    assert response.status_code == 422
    assert "device-b" in response.json()["detail"]


@pytest.mark.asyncio
async def test_foreign_device_activity_rejected(auth_client):
    client, _ = auth_client

    response = await push(
        client, device_id="device-a", study_activity=[activity("device-b")]
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_two_devices_rollups_coexist(auth_client, session):
    client, user = auth_client

    await push(
        client,
        device_id="device-a",
        srs_daily_counter=[counter("device-a", new_count=5)],
    )
    await push(
        client,
        device_id="device-b",
        srs_daily_counter=[counter("device-b", new_count=3)],
    )

    rows = (
        await session.scalars(
            select(SrsDailyCounter).where(SrsDailyCounter.user_id == user.id)
        )
    ).all()

    assert len(rows) == 2
    assert sum(r.new_count for r in rows) == 8


@pytest.mark.asyncio
async def test_tombstone_round_trips(auth_client, session):
    client, user = auth_client

    response = await push(client, srs_item_tombstone=[tombstone("あ")])

    assert response.status_code == 200
    assert response.json()["accepted"]["srs_item_tombstone"] == [
        ["kana", "あ", "default"]
    ]

    row = await session.scalar(
        select(SrsItemTombstone).where(SrsItemTombstone.user_id == user.id)
    )
    assert row.deleted_at == BASE
    assert row.updated_at == BASE


@pytest.mark.asyncio
async def test_tombstone_merges_on_deleted_at(auth_client, session):
    client, user = auth_client

    await push(client, srs_item_tombstone=[tombstone("あ", BASE + 5000)])
    response = await push(
        client, srs_item_tombstone=[tombstone("あ", BASE + 1000)]
    )

    assert response.json()["accepted"]["srs_item_tombstone"] == []

    row = await session.scalar(
        select(SrsItemTombstone).where(SrsItemTombstone.user_id == user.id)
    )
    assert row.deleted_at == BASE + 5000


@pytest.mark.asyncio
async def test_tombstone_pull_shape(auth_client):
    client, _ = auth_client
    await push(client, srs_item_tombstone=[tombstone("あ")])

    body = (await client.get("/sync/pull?since=0")).json()
    row = next(r for r in body["rows"] if r["table"] == "srs_item_tombstone")

    assert set(row["row"]) == {"category", "item_id", "card_type", "deleted_at"}


@pytest.mark.asyncio
async def test_all_tables_in_one_push(auth_client):
    client, _ = auth_client

    response = await push(
        client,
        favorites=[
            {
                "item_type": "kana",
                "item_id": "あ",
                "created_at": BASE,
                "updated_at": BASE,
            }
        ],
        settings=[{"key": "theme", "value": '"dark"', "updated_at": BASE}],
        srs_daily_counter=[counter("device-a")],
        study_activity=[activity("device-a")],
        srs_item_tombstone=[tombstone("い")],
    )

    assert response.status_code == 200
    assert response.json()["highest_reserved_seq"] == 5

    body = (await client.get("/sync/pull?since=0")).json()
    assert len(body["rows"]) == 5
    assert [r["server_seq"] for r in body["rows"]] == [1, 2, 3, 4, 5]