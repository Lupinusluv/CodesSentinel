"""仓库索引任务（ARQ）。

执行步骤：
  1. 加载 Repository，解析 owner/repo_name
  2. 拉取 GitHub 文件树（一次请求，含 size 字段）
  3. 过滤：扩展名 + 目录黑名单 + size < 900 KB，优先级排序，截断至 200 个文件
  4. 并发拉取文件内容（asyncio.Semaphore(10)）
  5. AST 分块（chunk_code），跳过解析失败的文件
  6. 批量 Embedding：收集所有 chunk content，每 100 条调一次 embed_texts
  7. 幂等写入：先删该仓库旧 CodeChunk，再批量 INSERT 新记录
  8. 更新 repository.indexed_at
"""

import asyncio
import base64
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import delete, insert

from app.core.config import get_settings
from app.core.dependencies import get_session_factory
from app.core.logging import get_logger
from app.models.code_chunk import CodeChunk
from app.models.repository import Repository
from app.platform.adapters.github import GitHubAdapter
from app.rag.chunker import Chunk, chunk_code
from app.rag.embeddings import embed_texts

log = get_logger(__name__)

_GITHUB_API     = "https://api.github.com"
_API_VERSION    = "2022-11-28"
_MAX_FILES      = 200
_MAX_FILE_BYTES = 900 * 1024   # GitHub 超过 1 MB 返回 403，保守取 900 KB
_EMBED_BATCH    = 100           # 每批 embedding API 调用的 chunk 数
_FETCH_SEM      = 10            # 并发拉文件内容的最大协程数

_SKIP_DIRS = {
    "tests", "test", "docs", "doc", "node_modules", "vendor",
    "dist", "build", ".venv", "venv", "__pycache__", ".git",
    "coverage", "htmlcov", "fixtures", "static", "assets", "public",
}
_PRIORITY_DIRS = {"src", "app", "lib", "core", "api", "services", "models"}
_EXT_TO_LANG   = {".py": "python", ".js": "javascript", ".ts": "typescript"}


async def run_index_task(ctx: dict, repository_id: str) -> None:
    """ARQ 入口：对指定仓库建立 pgvector 索引。"""
    session_factory = get_session_factory()

    async with session_factory() as db:
        repo: Repository | None = await db.get(Repository, uuid.UUID(repository_id))
        if repo is None:
            log.error("index_repo_not_found", repository_id=repository_id)
            return

        owner, repo_name = GitHubAdapter.parse_repo_url(repo.url)
        log.info("index_started", owner=owner, repo=repo_name)

        settings = get_settings()
        headers = {
            "Authorization": f"Bearer {settings.github_token}",
            "X-GitHub-Api-Version": _API_VERSION,
            "Accept": "application/vnd.github+json",
        }

        async with httpx.AsyncClient(timeout=60, headers=headers) as client:
            # ── 1. 拉文件树，过滤 + 排序 + 截断 ──────────────────────────────────
            files = await _fetch_file_tree(client, owner, repo_name)
            log.info("index_files_selected", count=len(files))

            # ── 2. 并发拉文件内容 ─────────────────────────────────────────────────
            sem = asyncio.Semaphore(_FETCH_SEM)
            fetch_results = await asyncio.gather(
                *[_fetch_file_content(client, owner, repo_name, f, sem) for f in files],
                return_exceptions=True,
            )

        # ── 3. AST 分块 ──────────────────────────────────────────────────────────
        items: list[tuple[str, Chunk]] = []
        for file_meta, result in zip(files, fetch_results):
            if isinstance(result, Exception):
                log.warning("index_fetch_failed", path=file_meta["path"], error=str(result))
                continue
            content, lang = result
            try:
                for chunk in chunk_code(content, lang):
                    items.append((file_meta["path"], chunk))
            except Exception as exc:
                log.warning("index_chunk_failed", path=file_meta["path"], error=str(exc))

        log.info("index_chunks_total", count=len(items))

        if not items:
            log.warning("index_no_chunks", owner=owner, repo=repo_name)
            repo.indexed_at = datetime.now(timezone.utc)
            await db.commit()
            return

        # ── 4. 批量 Embedding（每 100 条一次 API 调用，串行）─────────────────────
        all_contents: list[str] = [chunk.content for _, chunk in items]
        all_embeddings: list[list[float]] = []
        for i in range(0, len(all_contents), _EMBED_BATCH):
            vecs = await embed_texts(all_contents[i : i + _EMBED_BATCH])
            all_embeddings.extend(vecs)

        # ── 5. 幂等写入 pgvector ──────────────────────────────────────────────────
        repo_uuid = uuid.UUID(repository_id)
        await db.execute(delete(CodeChunk).where(CodeChunk.repository_id == repo_uuid))

        rows = [
            {
                "id": uuid.uuid4(),
                "repository_id": repo_uuid,
                "file_path": path,
                "symbol_name": chunk.symbol_name,
                "symbol_type": chunk.symbol_type,
                "content": chunk.content,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "embedding": emb,
            }
            for (path, chunk), emb in zip(items, all_embeddings)
        ]
        await db.execute(insert(CodeChunk), rows)

        repo.indexed_at = datetime.now(timezone.utc)
        await db.commit()

        log.info(
            "index_done",
            owner=owner, repo=repo_name,
            files=len(files), chunks=len(items),
        )


# ── 内部工具 ──────────────────────────────────────────────────────────────────

def _should_skip(path: str) -> bool:
    """路径中任意目录部分命中黑名单则跳过（不检查文件名本身）。"""
    parts = path.split("/")
    return any(part in _SKIP_DIRS for part in parts[:-1])


def _priority_key(file: dict) -> int:
    """顶层目录在 _PRIORITY_DIRS 中则排前（返回 0），其他返回 1。"""
    top = file["path"].split("/")[0]
    return 0 if top in _PRIORITY_DIRS else 1


async def _fetch_file_tree(
    client: httpx.AsyncClient, owner: str, repo: str
) -> list[dict]:
    """一次性拉取 GitHub 文件树，过滤后返回候选文件列表。"""
    resp = await client.get(
        f"{_GITHUB_API}/repos/{owner}/{repo}/git/trees/HEAD",
        params={"recursive": "1"},
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("truncated"):
        log.warning("index_tree_truncated", owner=owner, repo=repo)

    blobs = [
        item for item in data.get("tree", [])
        if item["type"] == "blob"
        and any(item["path"].endswith(ext) for ext in _EXT_TO_LANG)
        and not _should_skip(item["path"])
        and item.get("size", 0) < _MAX_FILE_BYTES
    ]

    blobs.sort(key=_priority_key)

    if len(blobs) > _MAX_FILES:
        log.warning("index_files_truncated", total=len(blobs), kept=_MAX_FILES)
        blobs = blobs[:_MAX_FILES]

    return blobs


async def _fetch_file_content(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    file: dict,
    sem: asyncio.Semaphore,
) -> tuple[str, str]:
    """拉取单文件内容，返回 (decoded_content, language)。"""
    path = file["path"]
    ext  = "." + path.rsplit(".", 1)[-1]
    lang = _EXT_TO_LANG[ext]

    async with sem:
        resp = await client.get(f"{_GITHUB_API}/repos/{owner}/{repo}/contents/{path}")

    if resp.status_code == 403:
        raise RuntimeError(f"Access denied or file too large: {path}")
    resp.raise_for_status()

    content_b64 = resp.json().get("content", "")
    decoded = base64.b64decode(content_b64).decode("utf-8", errors="replace")
    return decoded, lang
