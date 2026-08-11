import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/refresh", response_model=TokenPair)
async def refresh(
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
async def logout(
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
async def dev_login(session: AsyncSession = Depends(get_session)) -> TokenPair:
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

@router.post("/{provider}", response_model=TokenPair)
async def provider_login(
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
    refresh_token = await issue_refresh_token(session, user.id)
    await session.commit()

    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=refresh_token,
    )