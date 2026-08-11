import pytest

from app.auth.tokens import create_access_token
from app.models import User

BASE = 1786468000000


def fav(item_id: str, updated_at: int = BASE) -> dict:
    return {
        "item_type": "kana",
        "item_id": item_id,
        "created_at": BASE,
        "updated_at": updated_at,
    }


async def push(client, **changes):
    return await client.post(
        "/sync/push", json={"device_id": "device-a", **changes}
    )


@pytest.mark.asyncio
async def test_pull_from_zero_returns_everything(auth_client):
    client, _ = auth_client
    await push(client, favorites=[fav("あ"), fav("い")])

    response = await client.get("/sync/pull?since=0")

    assert response.status_code == 200
    body = response.json()
    assert len(body["rows"]) == 2
    assert body["has_more"] is False
    assert body["next_since"] == 2
    assert {r["row"]["item_id"] for r in body["rows"]} == {"あ", "い"}


@pytest.mark.asyncio
async def test_pull_respects_cursor(auth_client):
    client, _ = auth_client
    await push(client, favorites=[fav("あ")])
    await push(client, favorites=[fav("い")])

    response = await client.get("/sync/pull?since=1")
    body = response.json()

    assert len(body["rows"]) == 1
    assert body["rows"][0]["row"]["item_id"] == "い"


@pytest.mark.asyncio
async def test_empty_pull_echoes_cursor(auth_client):
    client, _ = auth_client
    await push(client, favorites=[fav("あ")])

    response = await client.get("/sync/pull?since=1")
    body = response.json()

    assert body["rows"] == []
    assert body["next_since"] == 1
    assert body["has_more"] is False


@pytest.mark.asyncio
async def test_rows_are_ordered_by_seq(auth_client):
    client, _ = auth_client
    for ch in "あいうえお":
        await push(client, favorites=[fav(ch)])

    body = (await client.get("/sync/pull?since=0")).json()
    seqs = [r["server_seq"] for r in body["rows"]]

    assert seqs == sorted(seqs)
    assert seqs == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_paging_covers_everything_once(auth_client):
    client, _ = auth_client
    for i in range(12):
        await push(client, favorites=[fav(f"k{i}")])

    seen: list[str] = []
    since = 0
    pages = 0

    while True:
        body = (await client.get(f"/sync/pull?since={since}&limit=5")).json()
        seen.extend(r["row"]["item_id"] for r in body["rows"])
        since = body["next_since"]
        pages += 1
        if not body["has_more"]:
            break
        assert pages < 10

    assert pages == 3
    assert len(seen) == 12
    assert len(set(seen)) == 12


@pytest.mark.asyncio
async def test_mixed_tables_merge_by_seq(auth_client):
    client, _ = auth_client
    await push(
        client,
        favorites=[fav("あ")],
        settings=[{"key": "theme", "value": '"dark"', "updated_at": BASE}],
    )

    body = (await client.get("/sync/pull?since=0")).json()

    assert len(body["rows"]) == 2
    assert {r["table"] for r in body["rows"]} == {"favorites", "settings"}
    seqs = [r["server_seq"] for r in body["rows"]]
    assert seqs == sorted(seqs)


@pytest.mark.asyncio
async def test_server_columns_not_exposed(auth_client):
    client, _ = auth_client
    await push(client, favorites=[fav("あ")])

    body = (await client.get("/sync/pull?since=0")).json()
    row = body["rows"][0]["row"]

    assert set(row) == {
        "item_type",
        "item_id",
        "created_at",
        "updated_at",
        "deleted_at",
    }


@pytest.mark.asyncio
async def test_tenant_isolation(auth_client, client, session):
    a_client, _ = auth_client
    await push(a_client, favorites=[fav("あ")])

    other = User()
    session.add(other)
    await session.flush()
    token = create_access_token(other.id)

    response = await client.get(
        "/sync/pull?since=0", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.json()["rows"] == []


@pytest.mark.asyncio
async def test_pull_requires_auth(client):
    client.headers.pop("Authorization", None)
    response = await client.get("/sync/pull?since=0")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_params_rejected(auth_client):
    client, _ = auth_client

    assert (await client.get("/sync/pull?since=-1")).status_code == 422
    assert (await client.get("/sync/pull?limit=0")).status_code == 422
    assert (await client.get("/sync/pull?limit=99999")).status_code == 422