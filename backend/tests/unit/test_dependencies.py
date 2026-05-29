"""get_arq_pool 接线单测。

v0.5.2 P1-2：旧实现手写 url.replace/split 只取 host/port，丢密码、db 索引、
rediss:// TLS。改用 arq 的 RedisSettings.from_dsn 后，带鉴权/TLS 的 Redis DSN
必须被完整解析。本测试拦截 create_pool，断言传入的 RedisSettings 字段正确，不真连。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core import dependencies


@pytest.mark.asyncio
async def test_get_arq_pool_parses_full_dsn(monkeypatch):
    captured: dict = {}

    async def fake_create_pool(redis_settings):
        captured["settings"] = redis_settings
        return AsyncMock()

    monkeypatch.setattr(dependencies, "create_pool", fake_create_pool)
    monkeypatch.setattr(dependencies, "_arq_pool", None)

    fake_settings = SimpleNamespace(redis_url="redis://:secret@example.com:6380/2")
    await dependencies.get_arq_pool(fake_settings)  # type: ignore[arg-type]

    rs = captured["settings"]
    assert rs.host == "example.com"
    assert rs.port == 6380
    assert rs.database == 2
    assert rs.password == "secret"


@pytest.mark.asyncio
async def test_get_arq_pool_handles_rediss_tls(monkeypatch):
    captured: dict = {}

    async def fake_create_pool(redis_settings):
        captured["settings"] = redis_settings
        return AsyncMock()

    monkeypatch.setattr(dependencies, "create_pool", fake_create_pool)
    monkeypatch.setattr(dependencies, "_arq_pool", None)

    fake_settings = SimpleNamespace(redis_url="rediss://user:pw@tls-host:6380/1")
    await dependencies.get_arq_pool(fake_settings)  # type: ignore[arg-type]

    assert captured["settings"].ssl is True
