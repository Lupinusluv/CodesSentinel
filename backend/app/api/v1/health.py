from fastapi import APIRouter
from sqlalchemy import text

from app.core.dependencies import DBSessionDep, RedisDep, SettingsDep

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def readiness(
    settings: SettingsDep,
    db: DBSessionDep,
    redis: RedisDep,
) -> dict[str, object]:
    db_ok = False
    redis_ok = False

    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    try:
        pong = await redis.ping()
        redis_ok = bool(pong)
    except Exception:
        redis_ok = False

    return {
        "status": "ok" if (db_ok and redis_ok) else "degraded",
        "env": settings.app_env,
        "database": db_ok,
        "redis": redis_ok,
    }
