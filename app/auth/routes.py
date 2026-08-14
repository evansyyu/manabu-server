import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.apple_revocation import exchange_authorization_code, revoke_apple_token
from app.auth.deps import get_current_user
from app.auth.identities import find_or_create_user
from app.auth.oidc import InvalidIdentityToken, verify_identity_token
from app.auth.refresh import (
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
)
from app.auth.schemas import ProviderLoginRequest, RefreshRequest, TokenPair
from app.auth.tokens import create_access_token
from app.config import settings
from app.db import get_session
from app.models import Identity, User
from app.rate_limit import ACCOUNT_DELETE_LIMIT, LOGIN_LIMIT, REFRESH_LIMIT, limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/refresh", response_model=TokenPair)
@limiter.limit(REFRESH_LIMIT)
async def refresh(
    request: Request,
    body: RefreshRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenPair:
    try:
        user_id, new_refresh = await rotate_refresh_token(
            session, body.refresh_token
        )
    except ValueError as exc:
        await session.commit()
        logger.warning("Refresh rejected: %s", exc)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid refresh token"
        ) from exc

    await session.commit()
    return TokenPair(
        access_token=create_access_token(user_id),
        refresh_token=new_refresh,
    )


# NB: must be registered before the catch-all POST /auth/{provider} below, or
# "logout" would be parsed as a provider name and 404.
@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(LOGIN_LIMIT)
async def logout(
    request: Request,
    body: RefreshRequest,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Revokes the presented refresh token. Deliberately unauthenticated —
    the access token may already be expired when the user signs out, and the
    refresh token itself is proof of possession. Always 204: the outcome for
    an unknown token is indistinguishable on purpose."""
    await revoke_refresh_token(session, body.refresh_token)
    await session.commit()


@router.post("/dev-login", response_model=TokenPair)
@limiter.limit(LOGIN_LIMIT)
async def dev_login(
    request: Request, session: AsyncSession = Depends(get_session)
) -> TokenPair:
    if not settings.dev_login_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    user = User()
    session.add(user)
    await session.flush()

    refresh_token = await issue_refresh_token(session, user.id)
    await session.commit()

    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=refresh_token,
    )

@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {"user_id": str(user.id), "created_at": user.created_at}


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(ACCOUNT_DELETE_LIMIT)
async def delete_account(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Permanently deletes the account and everything it owns.

    Every table carries a users FK with ondelete=CASCADE (SyncedMixin,
    identities, refresh_tokens, user_sync_state), so deleting the user row is
    the whole erasure. Apple tokens are revoked first, per App Store guideline
    5.1.1(v) — best-effort, because an Apple outage must not make an account
    undeletable; the tokens die with the identity rows regardless.
    """
    result = await session.execute(
        select(Identity.apple_refresh_token).where(
            Identity.user_id == user.id,
            Identity.provider == "apple",
            Identity.apple_refresh_token.is_not(None),
        )
    )
    for (apple_token,) in result.all():
        await revoke_apple_token(apple_token)

    await session.delete(user)
    await session.commit()
    logger.info("account deleted user=%s", user.id)

@router.post("/{provider}", response_model=TokenPair)
@limiter.limit(LOGIN_LIMIT)
async def provider_login(
    request: Request,
    provider: str,
    body: ProviderLoginRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenPair:
    if provider not in ("apple", "google"):
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    try:
        verified = await verify_identity_token(provider, body.identity_token)
    except InvalidIdentityToken as exc:
        logger.warning("Identity token rejected (%s): %s", provider, exc)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid identity token"
        ) from exc

    user = await find_or_create_user(session, verified)

    # Apple only: bank the refresh token that account deletion will revoke.
    # The authorizationCode is single-use and lives five minutes — this
    # sign-in is the only chance to exchange it. Best-effort: a failed
    # exchange logs and moves on (exchange_authorization_code never raises).
    if provider == "apple" and body.authorization_code:
        apple_token = await exchange_authorization_code(body.authorization_code)
        if apple_token is not None:
            await session.execute(
                Identity.__table__.update()
                .where(
                    Identity.provider == "apple",
                    Identity.provider_sub == verified.subject,
                )
                .values(apple_refresh_token=apple_token)
            )

    refresh_token = await issue_refresh_token(session, user.id)
    await session.commit()

    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=refresh_token,
    )