import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RefreshToken

REFRESH_TOKEN_TTL = timedelta(days=30)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def issue_refresh_token(session: AsyncSession, user_id: uuid.UUID) -> str:
    raw = secrets.token_urlsafe(32)
    session.add(
        RefreshToken(
            user_id=user_id,
            token_hash=_hash(raw),
            expires_at=datetime.now(UTC) + REFRESH_TOKEN_TTL,
        )
    )
    await session.flush()
    return raw


async def rotate_refresh_token(
    session: AsyncSession, raw: str
) -> tuple[uuid.UUID, str]:
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == _hash(raw))
    )
    existing = result.scalar_one_or_none()

    if existing is None:
        raise ValueError("Unknown refresh token")

    if existing.revoked_at is not None:
        await _revoke_all_for_user(session, existing.user_id)
        raise ValueError("Refresh token reuse detected")

    if existing.expires_at < datetime.now(UTC):
        raise ValueError("Refresh token expired")

    new_raw = secrets.token_urlsafe(32)
    replacement = RefreshToken(
        user_id=existing.user_id,
        token_hash=_hash(new_raw),
        expires_at=datetime.now(UTC) + REFRESH_TOKEN_TTL,
    )
    session.add(replacement)
    await session.flush()

    existing.revoked_at = datetime.now(UTC)
    existing.replaced_by = replacement.id
    await session.flush()

    return existing.user_id, new_raw


async def revoke_refresh_token(session: AsyncSession, raw: str) -> None:
    """Logout: revoke one token. Idempotent and silent — an unknown or already-
    revoked token is not an error worth telling an attacker about, and the
    client is about to discard its copy either way."""
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == _hash(raw), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
        .execution_options(synchronize_session="fetch")
    )
    await session.flush()


async def _revoke_all_for_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
        .execution_options(synchronize_session="fetch")
    )
    await session.flush()