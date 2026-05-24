"""初始化数据库表。

用法（项目根目录）：
    python scripts/init_db.py

依赖：docker compose up -d postgres
"""

import asyncio
import sys
from pathlib import Path

DROP_ALL = "--drop-all" in sys.argv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from sqlalchemy import text  # noqa: E402

from app.core.dependencies import close_resources, get_engine  # noqa: E402
from app.models import Base  # noqa: E402,F401


async def init_models() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        if DROP_ALL:
            print("[init_db] --drop-all: dropping existing tables and types...")
            await conn.run_sync(Base.metadata.drop_all)
            for enum_name in ("issue_category_enum", "issue_severity_enum",
                              "platform_enum", "review_status_enum"):
                await conn.execute(text(f"DROP TYPE IF EXISTS {enum_name} CASCADE"))

        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    print("[init_db] pgvector extension enabled")
    print(f"[init_db] tables ready: {', '.join(Base.metadata.tables)}")


async def main() -> None:
    try:
        await init_models()
    finally:
        await close_resources()


if __name__ == "__main__":
    asyncio.run(main())
