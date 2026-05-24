from collections.abc import AsyncGenerator
from typing import Annotated

import redis.asyncio as aioredis
from arq import ArqRedis, create_pool
from arq.connections import RedisSettings as ArqRedisSettings
from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_redis_client: aioredis.Redis | None = None
_arq_pool: ArqRedis | None = None


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = settings or get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.is_dev,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def get_redis(settings: Settings | None = None) -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        settings = settings or get_settings()
        _redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def get_arq_pool(settings: Settings | None = None) -> ArqRedis:
    global _arq_pool
    if _arq_pool is None:
        settings = settings or get_settings()
        url = settings.redis_url  # redis://localhost:6379/0
        parts = url.replace("redis://", "").split("/")[0].split(":")
        host = parts[0]
        port = int(parts[1]) if len(parts) > 1 else 6379
        _arq_pool = await create_pool(ArqRedisSettings(host=host, port=port))
    return _arq_pool


async def close_resources() -> None:
    global _engine, _redis_client, _session_factory, _arq_pool
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
    if _arq_pool is not None:
        await _arq_pool.aclose()
        _arq_pool = None
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    _session_factory = None


SettingsDep = Annotated[Settings, Depends(get_settings)]
DBSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
RedisDep = Annotated[aioredis.Redis, Depends(get_redis)]
