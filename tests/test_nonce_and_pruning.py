import hashlib
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import func, select

from app.auth import oidc
from app.models import Favorite, SrsItemTombstone, User
from app.sync.pruning import _GRACE_MS, prune_tombstones

PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
AUDIENCE = "com.test.manabu"


@pytest.fixture(autouse=True)
def patch_apple(monkeypatch):
    class FakeKey:
        key = PRIVATE_KEY.public_key()

    monkeypatch.setattr(
        oidc._apple_jwks, "get_signing_key_from_jwt", lambda token: FakeKey()
    )
    monkeypatch.setattr(oidc.settings, "apple_bundle_id", AUDIENCE)


def apple_token(nonce: str | None = None) -> str:
    claims = {
        "iss": "https://appleid.apple.com",
        "aud": AUDIENCE,
        "sub": "000123.abc.456",
        "exp": int(time.time()) + 600,
    }
    if nonce is not None:
        claims["nonce"] = nonce
    return jwt.encode(claims, PRIVATE_KEY, algorithm="RS256")


RAW = "raw-nonce-value"
HASHED = hashlib.sha256(RAW.encode()).hexdigest()


@pytest.mark.asyncio
async def test_matching_nonce_accepted(client):
    response = await client.post(
        "/auth/apple", json={"identity_token": apple_token(nonce=HASHED), "nonce": RAW}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token_nonce,request_nonce",
    [
        (HASHED, "wrong-raw"),  # mismatch
        (HASHED, None),  # token bound, request silent — no downgrade
        (None, RAW),  # request bound, token silent
    ],
)
async def test_nonce_violations_rejected(client, token_nonce, request_nonce):
    body: dict = {"identity_token": apple_token(nonce=token_nonce)}
    if request_nonce is not None:
        body["nonce"] = request_nonce
    response = await client.post("/auth/apple", json=body)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_no_nonce_anywhere_still_works(client):
    # A token without a nonce claim and a request without one verify fine.
    response = await client.post("/auth/apple", json={"identity_token": apple_token()})
    assert response.status_code == 200


GOOGLE_AUDIENCE = "38615096949-test.apps.googleusercontent.com"


@pytest.fixture
def patch_google(monkeypatch):
    class FakeKey:
        key = PRIVATE_KEY.public_key()

    monkeypatch.setattr(
        oidc._google_jwks, "get_signing_key_from_jwt", lambda token: FakeKey()
    )
    monkeypatch.setattr(oidc.settings, "google_client_ids", GOOGLE_AUDIENCE)


def google_token(nonce: str | None = None) -> str:
    claims = {
        "iss": "https://accounts.google.com",
        "aud": GOOGLE_AUDIENCE,
        "sub": "10769150350006150715113082367",
        "exp": int(time.time()) + 600,
    }
    if nonce is not None:
        claims["nonce"] = nonce
    return jwt.encode(claims, PRIVATE_KEY, algorithm="RS256")


@pytest.mark.asyncio
async def test_google_sdk_nonce_without_request_nonce_accepted(client, patch_google):
    # Google's native SDK stamps its own nonce into every token and never
    # exposes the raw value, so the request legitimately carries none — the
    # both-sides rule must not fire (it used to 401 every Google sign-in).
    response = await client.post(
        "/auth/google", json={"identity_token": google_token(nonce="sdk-internal-nonce")}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_google_request_nonce_still_enforced(client, patch_google):
    # A Google request that DOES bind a nonce gets the full check.
    response = await client.post(
        "/auth/google",
        json={"identity_token": google_token(nonce=HASHED), "nonce": "wrong-raw"},
    )
    assert response.status_code == 401

    response = await client.post(
        "/auth/google",
        json={"identity_token": google_token(nonce=HASHED), "nonce": RAW},
    )
    assert response.status_code == 200


NOW = 1_800_000_000_000


async def _user(session) -> User:
    user = User()
    session.add(user)
    await session.flush()
    return user


def _favorite(user_id, item_id: str, deleted_at: int | None):
    return Favorite(
        user_id=user_id,
        item_type="kanji",
        item_id=item_id,
        created_at=1,
        updated_at=1,
        deleted_at=deleted_at,
        server_seq=1,
        last_device_id="dev-a",
    )


@pytest.mark.asyncio
async def test_pruning_expires_old_tombstones_only(session):
    user = await _user(session)
    old = NOW - _GRACE_MS - 1
    fresh = NOW - 1000

    session.add(
        SrsItemTombstone(
            user_id=user.id,
            category="kanji",
            item_id="時",
            card_type="default",
            deleted_at=old,
            updated_at=old,
            server_seq=1,
            last_device_id="dev-a",
        )
    )
    session.add(
        SrsItemTombstone(
            user_id=user.id,
            category="kanji",
            item_id="間",
            card_type="default",
            deleted_at=fresh,
            updated_at=fresh,
            server_seq=2,
            last_device_id="dev-a",
        )
    )
    session.add(_favorite(user.id, "古", deleted_at=old))
    session.add(_favorite(user.id, "新", deleted_at=fresh))
    session.add(_favorite(user.id, "生", deleted_at=None))  # live — untouchable
    await session.flush()

    await prune_tombstones(session, user.id, now_ms=NOW)

    remaining_tombstones = (
        await session.execute(select(SrsItemTombstone.item_id))
    ).scalars().all()
    assert remaining_tombstones == ["間"]

    remaining_favorites = (
        await session.execute(select(Favorite.item_id).order_by(Favorite.item_id))
    ).scalars().all()
    assert remaining_favorites == ["新", "生"]


@pytest.mark.asyncio
async def test_pruning_is_tenant_scoped(session):
    owner = await _user(session)
    bystander = await _user(session)
    old = NOW - _GRACE_MS - 1
    session.add(_favorite(owner.id, "古", deleted_at=old))
    session.add(_favorite(bystander.id, "古", deleted_at=old))
    await session.flush()

    await prune_tombstones(session, owner.id, now_ms=NOW)

    count = await session.scalar(select(func.count()).select_from(Favorite))
    assert count == 1  # the bystander's row survived