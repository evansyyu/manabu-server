import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import func, select

from app.auth import oidc
from app.models import Identity

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


def apple_token(sub: str = "000123.abc.456", **overrides) -> str:
    claims = {
        "iss": "https://appleid.apple.com",
        "aud": AUDIENCE,
        "sub": sub,
        "email": "evans@example.com",
        "exp": int(time.time()) + 600,
    }
    claims.update(overrides)
    return jwt.encode(claims, PRIVATE_KEY, algorithm="RS256")


@pytest.mark.asyncio
async def test_apple_login_creates_user(client, session):
    response = await client.post(
        "/auth/apple", json={"identity_token": apple_token()}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]

    count = await session.scalar(
        select(func.count())
        .select_from(Identity)
        .where(Identity.provider_sub == "000123.abc.456")
    )
    assert count == 1


@pytest.mark.asyncio
async def test_second_login_reuses_same_user(client, session):
    first = await client.post(
        "/auth/apple", json={"identity_token": apple_token()}
    )
    second = await client.post(
        "/auth/apple", json={"identity_token": apple_token()}
    )

    assert first.status_code == 200
    assert second.status_code == 200

    identities = await session.scalar(
        select(func.count())
        .select_from(Identity)
        .where(Identity.provider_sub == "000123.abc.456")
    )
    assert identities == 1


@pytest.mark.asyncio
async def test_different_subject_creates_second_user(client, session):
    await client.post("/auth/apple", json={"identity_token": apple_token()})
    await client.post(
        "/auth/apple", json={"identity_token": apple_token(sub="000999.xyz.111")}
    )

    subs = (
        await session.scalars(
            select(Identity.user_id).where(
                Identity.provider_sub.in_(["000123.abc.456", "000999.xyz.111"])
            )
        )
    ).all()
    assert len(subs) == 2
    assert len(set(subs)) == 2


@pytest.mark.asyncio
async def test_bad_token_rejected(client):
    response = await client.post(
        "/auth/apple", json={"identity_token": "garbage"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_access_token_works_on_me(client):
    login = await client.post(
        "/auth/apple", json={"identity_token": apple_token()}
    )
    access = login.json()["access_token"]

    response = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {access}"}
    )
    assert response.status_code == 200