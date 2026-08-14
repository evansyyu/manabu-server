import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from sqlalchemy import func, select

from app.auth import apple_revocation, oidc
from app.auth.tokens import create_access_token
from app.models import Favorite, Identity, RefreshToken, User, UserSyncState

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


def apple_token(sub: str = "000123.abc.456") -> str:
    return jwt.encode(
        {
            "iss": "https://appleid.apple.com",
            "aud": AUDIENCE,
            "sub": sub,
            "email": "evans@example.com",
            "exp": int(time.time()) + 600,
        },
        PRIVATE_KEY,
        algorithm="RS256",
    )


async def _seed_full_account(session) -> User:
    """A user with an identity, a refresh token, sync state and a synced row —
    one of everything the cascade has to reach."""
    user = User()
    session.add(user)
    await session.flush()
    session.add(
        Identity(
            user_id=user.id,
            provider="apple",
            provider_sub=f"sub-{uuid.uuid4()}",
            apple_refresh_token="apple-rt-1",
        )
    )
    session.add(
        RefreshToken(
            user_id=user.id, token_hash=f"h-{uuid.uuid4()}", expires_at=_far_future()
        )
    )
    session.add(UserSyncState(user_id=user.id, seq_high=7))
    session.add(
        Favorite(
            user_id=user.id,
            item_type="kanji",
            item_id="時",
            created_at=1,
            updated_at=1,
            server_seq=1,
            last_device_id="dev-a",
        )
    )
    await session.flush()
    return user


def _far_future():
    from datetime import UTC, datetime, timedelta

    return datetime.now(UTC) + timedelta(days=30)


@pytest.mark.asyncio
async def test_delete_account_cascades_everything(client, session, monkeypatch):
    revoked: list[str] = []

    async def fake_revoke(token: str) -> None:
        revoked.append(token)

    monkeypatch.setattr("app.auth.routes.revoke_apple_token", fake_revoke)

    user = await _seed_full_account(session)
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    response = await client.delete("/auth/account", headers=headers)
    assert response.status_code == 204

    for model in (User, Identity, RefreshToken, UserSyncState, Favorite):
        count = await session.scalar(select(func.count()).select_from(model))
        assert count == 0, f"{model.__name__} rows survived deletion"

    # The stored Apple token was revoked before the rows went.
    assert revoked == ["apple-rt-1"]

    # The session is dead: the same bearer token no longer resolves a user.
    me = await client.get("/auth/me", headers=headers)
    assert me.status_code == 401


@pytest.mark.asyncio
async def test_delete_account_requires_auth(client):
    response = await client.delete("/auth/account")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_stores_apple_refresh_token_when_configured(
    client, session, monkeypatch
):
    async def fake_exchange(code: str) -> str | None:
        assert code == "authcode-123"
        return "apple-rt-xyz"

    monkeypatch.setattr("app.auth.routes.exchange_authorization_code", fake_exchange)

    response = await client.post(
        "/auth/apple",
        json={"identity_token": apple_token(), "authorization_code": "authcode-123"},
    )
    assert response.status_code == 200

    stored = await session.scalar(select(Identity.apple_refresh_token))
    assert stored == "apple-rt-xyz"


@pytest.mark.asyncio
async def test_login_without_code_still_works(client, session):
    # No authorization_code (Google, or older app builds): login unchanged.
    response = await client.post("/auth/apple", json={"identity_token": apple_token()})
    assert response.status_code == 200
    stored = await session.scalar(select(Identity.apple_refresh_token))
    assert stored is None


def test_client_secret_is_es256_with_kid(monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    from cryptography.hazmat.primitives import serialization

    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()

    monkeypatch.setattr(apple_revocation.settings, "apple_team_id", "TEAM123456")
    monkeypatch.setattr(apple_revocation.settings, "apple_key_id", "KEY1234567")
    monkeypatch.setattr(apple_revocation.settings, "apple_private_key", pem)
    monkeypatch.setattr(apple_revocation.settings, "apple_bundle_id", AUDIENCE)

    secret = apple_revocation.make_client_secret()

    header = jwt.get_unverified_header(secret)
    assert header["alg"] == "ES256"
    assert header["kid"] == "KEY1234567"
    claims = jwt.decode(secret, key.public_key(), algorithms=["ES256"], audience="https://appleid.apple.com")
    assert claims["iss"] == "TEAM123456"
    assert claims["sub"] == AUDIENCE


@pytest.mark.asyncio
async def test_revocation_helpers_are_noops_when_unconfigured(monkeypatch):
    monkeypatch.setattr(apple_revocation.settings, "apple_team_id", "")
    # Would raise on any real network use — the no-op path must never get there.
    assert await apple_revocation.exchange_authorization_code("code") is None
    await apple_revocation.revoke_apple_token("token")
