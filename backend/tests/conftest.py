"""共享测试 fixture。

集成测试 (@pytest.mark.integration) 需要真实 PostgreSQL：
  - 默认连到 TEST_DATABASE_URL 环境变量；未设置时回退到 docker-compose 的本地 PG
  - 测试 DB 应该是单独的 `codessentinel_test`，事先用 alembic upgrade head 建好 schema
  - 如果连不上，自动 skip 整个集成测试套件
"""

import os
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# 提前注入测试 env，让 Settings 读取
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DEEPSEEK_API_KEY", "dummy-for-tests")
os.environ.setdefault(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://codessentinel:codessentinel@localhost:5432/codessentinel_test",
)
os.environ.setdefault("DATABASE_URL", os.environ["TEST_DATABASE_URL"])

import app.models  # noqa: F401, E402  触发所有 model 注册
from app.core.dependencies import get_arq_dep, get_db_session  # noqa: E402
from main import app as fastapi_app  # noqa: E402


TEST_DATABASE_URL = os.environ["TEST_DATABASE_URL"]


@pytest_asyncio.fixture
async def test_engine():
    """每个测试独立建 engine，避免 asyncpg pool 跨 event loop；若连不上 PG 自动 skip。"""
    engine = create_async_engine(TEST_DATABASE_URL, future=True, pool_size=2, max_overflow=0)
    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"Integration DB not reachable: {exc}")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine):
    """每个测试一个会话；测试结束清空业务表保证彼此隔离。"""
    factory = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        yield session

    # 清理：依赖 ondelete CASCADE 可只清 reviews 即可带走 issues / patches
    async with factory() as cleanup:
        from sqlalchemy import text

        # 测试不该碰 repositories / code_chunks 历史数据，逐表清更安全
        for tbl in ["patches", "issues", "reviews"]:
            await cleanup.execute(text(f"DELETE FROM {tbl}"))
        await cleanup.commit()


@pytest_asyncio.fixture
async def http_client(test_engine, db_session):
    """注入测试 session 的 FastAPI HTTP 客户端，arq pool 用 mock 替身。"""
    factory = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)

    async def _override_session():
        async with factory() as s:
            yield s

    fake_arq = AsyncMock()
    fake_arq.enqueue_job = AsyncMock(return_value=None)

    async def _override_arq():
        return fake_arq

    fastapi_app.dependency_overrides[get_db_session] = _override_session
    fastapi_app.dependency_overrides[get_arq_dep] = _override_arq

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.fake_arq = fake_arq  # type: ignore[attr-defined]
        yield client

    fastapi_app.dependency_overrides.clear()


@pytest.fixture
def sample_python_code() -> str:
    return (
        "import os\n"
        "def login(user, pw):\n"
        "    sql = 'SELECT * FROM users WHERE u=' + user\n"
        "    return sql\n"
    )


@pytest.fixture
def unique_marker() -> str:
    """让每个测试可以用唯一字符串识别自己创建的行，避免误清他人数据。"""
    return f"test-{uuid.uuid4().hex[:8]}"


@pytest_asyncio.fixture
async def github_repo(test_engine):
    """注册一个 GitHub 仓库供 webhook / 回写测试使用。

    conftest 的 db_session cleanup 不碰 repositories 表，所以本 fixture 自行清理
    （含其名下 reviews，避免 FK 残留）。url 带随机后缀，重复跑不冲突。
    """
    from app.models.repository import Platform, Repository

    factory = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    url = f"https://github.com/octocat/repo-{uuid.uuid4().hex[:8]}"
    async with factory() as s:
        repo = Repository(platform=Platform.github, url=url)
        s.add(repo)
        await s.commit()
        await s.refresh(repo)

    yield repo

    async with factory() as cleanup:
        from sqlalchemy import text

        for tbl in ["patches", "issues", "reviews"]:
            await cleanup.execute(text(f"DELETE FROM {tbl}"))
        obj = await cleanup.get(Repository, repo.id)
        if obj is not None:
            await cleanup.delete(obj)
        await cleanup.commit()
