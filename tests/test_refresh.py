import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.refresh import issue_refresh_token, rotate_refresh_token
from app.models import RefreshToken, User


async def _make_user(session: AsyncSession) -> User:
    user = User()
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_issue_and_rotate(session: AsyncSession):
    user = await _make_user(session)
    raw = await issue_refresh_token(session, user.id)

    user_id, new_raw = await rotate_refresh_token(session, raw)

    assert user_id == user.id
    assert new_raw != raw


@pytest.mark.asyncio
async def test_rotation_chains_old_to_new(session: AsyncSession):
    user = await _make_user(session)
    raw = await issue_refresh_token(session, user.id)
    await rotate_refresh_token(session, raw)

    result = await session.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id)
    )
    tokens = result.scalars().all()

    assert len(tokens) == 2
    old = next(t for t in tokens if t.revoked_at is not None)
    new = next(t for t in tokens if t.revoked_at is None)
    assert old.replaced_by == new.id


@pytest.mark.asyncio
async def test_reuse_revokes_entire_chain(session: AsyncSession):
    user = await _make_user(session)
    raw = await issue_refresh_token(session, user.id)
    await rotate_refresh_token(session, raw)

    with pytest.raises(ValueError, match="reuse"):
        await rotate_refresh_token(session, raw)

    result = await session.execute(
        select(RefreshToken)
        .where(RefreshToken.user_id == user.id)
        .execution_options(populate_existing=True)
    )
    tokens = result.scalars().all()
    assert all(t.revoked_at is not None for t in tokens)


@pytest.mark.asyncio
async def test_unknown_token_rejected(session: AsyncSession):
    with pytest.raises(ValueError, match="Unknown"):
        await rotate_refresh_token(session, "not-a-real-token")