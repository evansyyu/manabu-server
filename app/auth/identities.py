from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.oidc import VerifiedIdentity
from app.models import Identity, User


async def find_or_create_user(
    session: AsyncSession, verified: VerifiedIdentity
) -> User:
    result = await session.execute(
        select(Identity).where(
            Identity.provider == verified.provider,
            Identity.provider_sub == verified.subject,
        )
    )
    identity = result.scalar_one_or_none()

    if identity is not None:
        if identity.email is None and verified.email is not None:
            identity.email = verified.email
            await session.flush()
        return await session.get(User, identity.user_id)

    user = User()
    session.add(user)
    await session.flush()

    session.add(
        Identity(
            user_id=user.id,
            provider=verified.provider,
            provider_sub=verified.subject,
            email=verified.email,
        )
    )
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        result = await session.execute(
            select(Identity).where(
                Identity.provider == verified.provider,
                Identity.provider_sub == verified.subject,
            )
        )
        identity = result.scalar_one()
        return await session.get(User, identity.user_id)

    return user