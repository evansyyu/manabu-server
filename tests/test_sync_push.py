import pytest
from sqlalchemy import select

from app.models import Favorite, Setting

BASE = 1786468000000


def fav(item_id: str, updated_at: int = BASE, **extra) -> dict:
    return {
        "item_type": "kana",
        "item_id": item_id,
        "created_at": BASE,
        "updated_at": updated_at,
        **extra,
    }


async def push(client, **changes):
    return await client.post(
        "/sync/push", json={"device_id": "device-a", **changes}
    )


@pytest.mark.asyncio
async def test_push_creates_row(auth_client, session):
    client, user = auth_client

    response = await push(client, favorites=[fav("あ")])

    assert response.status_code == 200
    assert response.json()["accepted"]["favorites"] == [["kana", "あ"]]

    row = await session.scalar(
        select(Favorite).where(Favorite.user_id == user.id)
    )
    assert row.item_id == "あ"
    assert row.server_seq == 1
    assert row.last_device_id == "device-a"


@pytest.mark.asyncio
async def test_push_is_idempotent(auth_client, session):
    client, user = auth_client

    await push(client, favorites=[fav("あ")])
    second = await push(client, favorites=[fav("あ")])

    assert second.json()["accepted"]["favorites"] == []

    row = await session.scalar(
        select(Favorite).where(Favorite.user_id == user.id)
    )
    assert row.server_seq == 1


@pytest.mark.asyncio
async def test_newer_row_wins(auth_client, session):
    client, user = auth_client

    await push(client, favorites=[fav("あ", updated_at=BASE + 1000)])
    response = await push(client, favorites=[fav("あ", updated_at=BASE + 2000)])

    assert response.json()["accepted"]["favorites"] == [["kana", "あ"]]

    row = await session.scalar(
        select(Favorite).where(Favorite.user_id == user.id)
    )
    assert row.updated_at == BASE + 2000


@pytest.mark.asyncio
async def test_older_row_loses(auth_client, session):
    client, user = auth_client

    await push(client, favorites=[fav("あ", updated_at=BASE + 2000)])
    response = await push(client, favorites=[fav("あ", updated_at=BASE + 1000)])

    assert response.json()["accepted"]["favorites"] == []

    row = await session.scalar(
        select(Favorite).where(Favorite.user_id == user.id)
    )
    assert row.updated_at == BASE + 2000


@pytest.mark.asyncio
async def test_equal_timestamp_loses(auth_client, session):
    client, user = auth_client

    await push(client, favorites=[fav("あ")])
    response = await push(client, favorites=[fav("あ", **{"created_at": 1})])

    assert response.json()["accepted"]["favorites"] == []

    row = await session.scalar(
        select(Favorite).where(Favorite.user_id == user.id)
    )
    assert row.created_at == BASE


@pytest.mark.asyncio
async def test_duplicate_pks_in_one_batch(auth_client, session):
    client, user = auth_client

    response = await push(
        client,
        favorites=[
            fav("あ", updated_at=BASE + 1000),
            fav("あ", updated_at=BASE + 5000),
            fav("あ", updated_at=BASE + 3000),
        ],
    )

    assert response.status_code == 200

    row = await session.scalar(
        select(Favorite).where(Favorite.user_id == user.id)
    )
    assert row.updated_at == BASE + 5000


@pytest.mark.asyncio
async def test_denied_settings_key_dropped(auth_client, session):
    client, user = auth_client

    response = await push(
        client,
        settings=[
            {"key": "kanji_level_jlpt", "value": '"n5"', "updated_at": BASE},
            {
                "key": "session_undo_boundary_abc-123",
                "value": "0",
                "updated_at": BASE,
            },
        ],
    )

    assert response.status_code == 200

    keys = (
        await session.scalars(
            select(Setting.key).where(Setting.user_id == user.id)
        )
    ).all()
    assert keys == ["kanji_level_jlpt"]


@pytest.mark.asyncio
async def test_batch_cap_enforced(auth_client):
    client, _ = auth_client

    response = await push(
        client, favorites=[fav(f"k{i}") for i in range(501)]
    )

    assert response.status_code == 413


@pytest.mark.asyncio
async def test_unknown_field_rejected(auth_client):
    client, _ = auth_client

    response = await client.post(
        "/sync/push",
        json={
            "device_id": "device-a",
            "favorites": [fav("あ", nonsense=True)],
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_bad_item_type_rejected(auth_client):
    client, _ = auth_client

    response = await client.post(
        "/sync/push",
        json={
            "device_id": "device-a",
            "favorites": [{**fav("あ"), "item_type": "verb"}],
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_push_requires_auth(client):
    response = await client.post(
        "/sync/push", json={"device_id": "device-a", "favorites": []}
    )

    assert response.status_code == 401