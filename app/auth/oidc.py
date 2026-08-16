import hashlib
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


async def verify_identity_token(
    provider: str, token: str, raw_nonce: str | None = None
) -> VerifiedIdentity:
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

    # Replay binding (Apple flow): the client mints a random nonce per
    # sign-in, hands its sha256 to the provider (which stamps it into the
    # token), and sends the raw value here. A token stolen from a log or the
    # wire can't be replayed without the raw nonce that never travels with
    # it. Enforced whenever *either* side carries a nonce, so a legitimate
    # client can't be downgraded by simply omitting the field.
    #
    # Google is exempt when the request carries no nonce: its native SDK
    # mints an internal nonce straight into the token and never exposes the
    # raw value, so every Google token arrives nonce-stamped with nothing to
    # echo back — the "both sides" rule rejected every Google sign-in
    # outright. A Google request that does supply a nonce is still checked
    # in full, and Apple keeps the strict rule (our client always sends it).
    token_nonce = claims.get("nonce")
    google_sdk_nonce = provider == "google" and raw_nonce is None
    if not google_sdk_nonce and (raw_nonce is not None or token_nonce is not None):
        if raw_nonce is None or token_nonce is None:
            raise InvalidIdentityToken("Nonce present on only one side")
        hashed = hashlib.sha256(raw_nonce.encode()).hexdigest()
        if hashed != token_nonce:
            raise InvalidIdentityToken("Nonce mismatch")

    return VerifiedIdentity(
        provider=provider,
        subject=subject,
        email=claims.get("email"),
    )