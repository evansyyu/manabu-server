from dataclasses import dataclass

import jwt
from jwt import PyJWKClient
from starlette.concurrency import run_in_threadpool

from app.config import settings

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_JWKS = "https://appleid.apple.com/auth/keys"

GOOGLE_ISSUERS = ["https://accounts.google.com", "accounts.google.com"]
GOOGLE_JWKS = "https://www.googleapis.com/oauth2/v3/certs"

_apple_jwks = PyJWKClient(APPLE_JWKS, cache_keys=True)
_google_jwks = PyJWKClient(GOOGLE_JWKS, cache_keys=True)


class InvalidIdentityToken(Exception):
    pass


@dataclass
class VerifiedIdentity:
    provider: str
    subject: str
    email: str | None


async def verify_identity_token(provider: str, token: str) -> VerifiedIdentity:
    if provider == "apple":
        client, audience, issuer = _apple_jwks, settings.apple_bundle_id, APPLE_ISSUER
    elif provider == "google":
        client = _google_jwks
        audience = settings.google_audiences
        issuer = GOOGLE_ISSUERS
    else:
        raise InvalidIdentityToken(f"Unknown provider: {provider}")

    if not audience:
        raise InvalidIdentityToken(f"No audience configured for {provider}")

    try:
        signing_key = await run_in_threadpool(
            client.get_signing_key_from_jwt, token
        )
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
        )
    except jwt.PyJWTError as exc:
        raise InvalidIdentityToken(str(exc)) from exc

    subject = claims.get("sub")
    if not subject:
        raise InvalidIdentityToken("Token has no subject")

    return VerifiedIdentity(
        provider=provider,
        subject=subject,
        email=claims.get("email"),
    )