from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session

from app.auth.deps import get_current_user
from app.models import User

app = FastAPI()


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/health/db")
async def health_db(session: AsyncSession = Depends(get_session)):
    result = await session.execute(text("SELECT 1"))
    return {"db": result.scalar_one()}

@app.get("/auth/me")
async def me(user: User = Depends(get_current_user)):
    return {"user_id": str(user.id), "created_at": user.created_at}
