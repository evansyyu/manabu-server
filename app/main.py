from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.routes import router as auth_router
from app.db import get_session

app = FastAPI()

app.include_router(auth_router)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/health/db")
async def health_db(session: AsyncSession = Depends(get_session)):
    result = await session.execute(text("SELECT 1"))
    return {"db": result.scalar_one()}