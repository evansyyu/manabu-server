import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth import oidc
from app.auth.oidc import InvalidIdentityToken, verify_identity_token

PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_KEY = PRIVATE_KEY.public_key()

AUDIENCE = "com.test.manabu"
ISSUER = "https://appleid.apple.com"


@pytest.fixture(autouse=True)
def patch_jwks_and_audience(monkeypatch):
    class FakeKey:
        key = PUBLIC_KEY

    monkeypatch.setattr(
        oidc._apple_jwks, "get_signing_key_from_jwt", lambda token: FakeKey()
    )
    monkeypatch.setattr(oidc.settings, "apple_bundle_id", AUDIENCE)


def make_token(**overrides) -> str:
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "000123.abcdef.4567",
        "email": "evans@example.com",
        "iat": int(time.time()),
        "exp": int(time.time()) + 600,
    }
    claims.update(overrides)
    return jwt.encode(claims, PRIVATE_KEY, algorithm="RS256")


@pytest.mark.asyncio
async def test_accepts_valid_token():
    identity = await verify_identity_token("apple", make_token())

    assert identity.provider == "apple"
    assert identity.subject == "000123.abcdef.4567"
    assert identity.email == "evans@example.com"


@pytest.mark.asyncio
async def test_rejects_wrong_audience():
    token = make_token(aud="com.someone-else.app")
    with pytest.raises(InvalidIdentityToken):
        await verify_identity_token("apple", token)


@pytest.mark.asyncio
async def test_rejects_wrong_issuer():
    token = make_token(iss="https://evil.example.com")
    with pytest.raises(InvalidIdentityToken):
        await verify_identity_token("apple", token)


@pytest.mark.asyncio
async def test_rejects_expired_token():
    token = make_token(exp=int(time.time()) - 60)
    with pytest.raises(InvalidIdentityToken):
        await verify_identity_token("apple", token)


@pytest.mark.asyncio
async def test_rejects_token_signed_by_other_key():
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "000123.abcdef.4567",
            "exp": int(time.time()) + 600,
        },
        other_key,
        algorithm="RS256",
    )
    with pytest.raises(InvalidIdentityToken):
        await verify_identity_token("apple", token)


@pytest.mark.asyncio
async def test_rejects_unknown_provider():
    with pytest.raises(InvalidIdentityToken):
        await verify_identity_token("facebook", make_token())