from fastapi import Depends, FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.routes import router as auth_router
from app.db import get_session
from app.rate_limit import limiter
from app.sync.routes import router as sync_router

app = FastAPI()

# slowapi's integration contract: the limiter rides on app.state, and the
# handler turns a tripped limit into a 429 instead of a 500.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(auth_router)
app.include_router(sync_router)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/health/db")
async def health_db(session: AsyncSession = Depends(get_session)):
    result = await session.execute(text("SELECT 1"))
    return {"db": result.scalar_one()}