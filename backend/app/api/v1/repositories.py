import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select

from app.core.dependencies import DBSessionDep, get_arq_pool
from app.core.logging import get_logger
from app.models.repository import Platform, Repository

log = get_logger(__name__)
router = APIRouter(prefix="/repositories", tags=["repositories"])


# ── Schema ────────────────────────────────────────────────────────────────────

_PLATFORM_URL_PREFIX: dict[str, str] = {
    "github": "https://github.com/",
    "gitee":  "https://gitee.com/",
}


class CreateRepositoryRequest(BaseModel):
    platform: Platform
    url: str

    @field_validator("url")
    @classmethod
    def url_matches_platform(cls, v: str, info) -> str:
        v = v.rstrip("/")
        platform_val = (info.data.get("platform") or Platform.github).value
        prefix = _PLATFORM_URL_PREFIX.get(platform_val)
        if prefix and not v.startswith(prefix):
            raise ValueError(f"{platform_val} URL must start with {prefix}")
        if not v.startswith("https://"):
            raise ValueError("URL must use HTTPS")
        return v


class RepositoryResponse(BaseModel):
    id: str
    platform: str
    url: str
    indexed_at: str | None
    created_at: str


# ── 路由 ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[RepositoryResponse])
async def list_repositories(db: DBSessionDep) -> list[RepositoryResponse]:
    result = await db.execute(select(Repository).order_by(Repository.created_at.desc()))
    return [_to_response(r) for r in result.scalars()]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=RepositoryResponse)
async def create_repository(body: CreateRepositoryRequest, db: DBSessionDep) -> RepositoryResponse:
    existing = await db.execute(select(Repository).where(Repository.url == body.url))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Repository already registered")

    repo = Repository(
        platform=body.platform,
        url=body.url,
    )
    db.add(repo)
    await db.commit()
    await db.refresh(repo)
    log.info("repository_created", id=str(repo.id), url=repo.url)
    return _to_response(repo)


@router.post("/{repository_id}/index", status_code=status.HTTP_202_ACCEPTED)
async def trigger_index(repository_id: str, db: DBSessionDep) -> dict[str, str]:
    try:
        uid = uuid.UUID(repository_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid repository_id format")

    repo = await db.get(Repository, uid)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    arq = await get_arq_pool()
    await arq.enqueue_job("run_index_task", str(uid))
    log.info("index_enqueued", repository_id=str(uid))
    return {"status": "accepted", "repository_id": str(uid)}


@router.delete("/{repository_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_repository(repository_id: str, db: DBSessionDep) -> None:
    try:
        uid = uuid.UUID(repository_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid repository_id format")

    repo = await db.get(Repository, uid)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    await db.delete(repo)
    await db.commit()
    log.info("repository_deleted", id=repository_id)


# ── 工具 ──────────────────────────────────────────────────────────────────────

def _to_response(repo: Repository) -> RepositoryResponse:
    return RepositoryResponse(
        id=str(repo.id),
        platform=repo.platform.value,
        url=repo.url,
        indexed_at=repo.indexed_at.isoformat() if repo.indexed_at else None,
        created_at=repo.created_at.isoformat(),
    )
