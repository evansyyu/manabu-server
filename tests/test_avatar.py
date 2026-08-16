"""The avatar endpoints: one image per user, byte-capped, last-writer-wins.

The LWW cases mirror the synced tables' convention (ties go to the writer),
because the client treats the avatar exactly like any other synced fact —
whichever device wrote last is the account's picture everywhere.
"""

import base64

import pytest

from app.auth.routes import MAX_AVATAR_BYTES


def payload(updated_at: int, data: bytes = b"jpegbytes", content_type: str = "image/jpeg"):
    return {
        "updated_at": updated_at,
        "content_type": content_type,
        "data_base64": base64.b64encode(data).decode("ascii"),
    }


@pytest.mark.asyncio
async def test_put_then_get_round_trips(auth_client):
    client, _user = auth_client

    put = await client.put("/auth/avatar", json=payload(100, b"first"))
    assert put.status_code == 200
    assert put.json() == {"accepted": True, "updated_at": 100}

    got = await client.get("/auth/avatar")
    assert got.status_code == 200
    body = got.json()
    assert body["updated_at"] == 100
    assert body["content_type"] == "image/jpeg"
    assert base64.b64decode(body["data_base64"]) == b"first"


@pytest.mark.asyncio
async def test_get_without_avatar_is_404(auth_client):
    client, _user = auth_client
    assert (await client.get("/auth/avatar")).status_code == 404


@pytest.mark.asyncio
async def test_last_writer_wins_and_ties_go_to_the_writer(auth_client):
    client, _user = auth_client
    await client.put("/auth/avatar", json=payload(200, b"newer"))

    # An older write loses and is told who won.
    stale = await client.put("/auth/avatar", json=payload(150, b"older"))
    assert stale.json() == {"accepted": False, "updated_at": 200}
    got = await client.get("/auth/avatar")
    assert base64.b64decode(got.json()["data_base64"]) == b"newer"

    # An equal-clock write is accepted — the writer acts on the state it read.
    tie = await client.put("/auth/avatar", json=payload(200, b"tie"))
    assert tie.json() == {"accepted": True, "updated_at": 200}

    # A newer write replaces outright.
    newer = await client.put("/auth/avatar", json=payload(300, b"newest"))
    assert newer.json() == {"accepted": True, "updated_at": 300}
    got = await client.get("/auth/avatar")
    assert base64.b64decode(got.json()["data_base64"]) == b"newest"


@pytest.mark.asyncio
async def test_delete_follows_the_same_lww_rule(auth_client):
    client, _user = auth_client
    await client.put("/auth/avatar", json=payload(200))

    # A removal older than the stored image loses to it.
    stale = await client.request("DELETE", "/auth/avatar", json={"updated_at": 100})
    assert stale.json() == {"accepted": False, "updated_at": 200}
    assert (await client.get("/auth/avatar")).status_code == 200

    # A removal at/after the stored clock wins; deleting nothing is fine.
    ok = await client.request("DELETE", "/auth/avatar", json={"updated_at": 200})
    assert ok.json() == {"accepted": True, "updated_at": None}
    assert (await client.get("/auth/avatar")).status_code == 404
    again = await client.request("DELETE", "/auth/avatar", json={"updated_at": 300})
    assert again.json() == {"accepted": True, "updated_at": None}


@pytest.mark.asyncio
async def test_upload_limits(auth_client):
    client, _user = auth_client

    too_big = await client.put(
        "/auth/avatar", json=payload(100, b"x" * (MAX_AVATAR_BYTES + 1))
    )
    assert too_big.status_code == 413

    wrong_type = await client.put(
        "/auth/avatar", json=payload(100, content_type="image/gif")
    )
    assert wrong_type.status_code == 415

    not_base64 = await client.put(
        "/auth/avatar",
        json={"updated_at": 100, "content_type": "image/jpeg", "data_base64": "!!!"},
    )
    assert not_base64.status_code == 400


@pytest.mark.asyncio
async def test_avatar_requires_auth(client):
    assert (await client.get("/auth/avatar")).status_code == 401
    assert (await client.put("/auth/avatar", json=payload(1))).status_code == 401
