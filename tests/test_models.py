# tests/test_models.py
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Identity, User


@pytest.mark.asyncio
async def test_create_user_with_identity(session: AsyncSession):
    user = User()
    session.add(user)
    await session.flush()

    identity = Identity(
        user_id=user.id,
        provider="apple",
        provider_sub="000123.abc.456",
        email="evans@example.com",
    )
    session.add(identity)
    await session.flush()

    result = await session.execute(
        select(Identity).where(Identity.provider_sub == "000123.abc.456")
    )
    found = result.scalar_one()
    assert found.user_id == user.id
    assert found.email == "evans@example.com"