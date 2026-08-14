"""Sign in with Apple server-to-server calls: code exchange and revocation.

Account deletion must revoke the user's Apple tokens (App Store guideline
5.1.1(v); Apple's added requirement since June 2022). That takes three steps
spread across the account's lifetime:

  1. At sign-in the app sends Apple's one-time ``authorizationCode`` along
     with the identity token.
  2. The server exchanges it (POST /auth/token) for an Apple *refresh token*
     and stores it on the identity row. This is the only moment the code is
     valid (five minutes, single use) — a refresh token obtained now is what
     makes revocation possible years later.
  3. At deletion the server revokes that token (POST /auth/revoke).

Both calls authenticate with a *client secret*: not a stored secret at all
but a short-lived ES256 JWT signed with a "Sign in with Apple" key from the
developer portal (``APPLE_TEAM_ID`` / ``APPLE_KEY_ID`` / ``APPLE_PRIVATE_KEY``).

Everything is config-gated and best-effort: without the key configured,
sign-in and deletion work exactly as before (nothing stored, nothing
revoked), so the feature degrades to "deletion without Apple revocation"
rather than blocking either flow. Failures are logged, never raised — an
Apple outage must not make an account undeletable.
"""

import logging
import time

import httpx
import jwt

from app.config import settings

APPLE_TOKEN_URL = "https://appleid.apple.com/auth/token"
APPLE_REVOKE_URL = "https://appleid.apple.com/auth/revoke"

# Apple allows up to 6 months; short is fine — one is minted per call.
CLIENT_SECRET_TTL_SECONDS = 300

logger = logging.getLogger(__name__)


def make_client_secret() -> str:
    """The ES256 JWT Apple accepts as ``client_secret``."""
    now = int(time.time())
    return jwt.encode(
        {
            "iss": settings.apple_team_id,
            "iat": now,
            "exp": now + CLIENT_SECRET_TTL_SECONDS,
            "aud": "https://appleid.apple.com",
            "sub": settings.apple_bundle_id,
        },
        # .p8 contents; platform env vars often carry newlines as literal \n.
        settings.apple_private_key.replace("\\n", "\n"),
        algorithm="ES256",
        headers={"kid": settings.apple_key_id},
    )


async def exchange_authorization_code(code: str) -> str | None:
    """One-time code -> long-lived Apple refresh token, or None on any failure."""
    if not settings.apple_revocation_configured:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                APPLE_TOKEN_URL,
                data={
                    "client_id": settings.apple_bundle_id,
                    "client_secret": make_client_secret(),
                    "code": code,
                    "grant_type": "authorization_code",
                },
            )
        if response.status_code != 200:
            logger.warning(
                "Apple code exchange failed: %s %s", response.status_code, response.text
            )
            return None
        token = response.json().get("refresh_token")
        return token if isinstance(token, str) else None
    except Exception:
        logger.exception("Apple code exchange errored")
        return None


async def revoke_apple_token(refresh_token: str) -> None:
    """Best-effort revocation at Apple. Never raises."""
    if not settings.apple_revocation_configured:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                APPLE_REVOKE_URL,
                data={
                    "client_id": settings.apple_bundle_id,
                    "client_secret": make_client_secret(),
                    "token": refresh_token,
                    "token_type_hint": "refresh_token",
                },
            )
        if response.status_code != 200:
            logger.warning(
                "Apple revocation failed: %s %s", response.status_code, response.text
            )
    except Exception:
        logger.exception("Apple revocation errored")
