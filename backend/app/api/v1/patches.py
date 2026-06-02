"""AutoFix 触发与查询接口。

- POST /api/v1/reviews/{id}/autofix  入队 autofix 任务，要求 review.status=done
- GET  /api/v1/reviews/{id}/patches  查询 patch 列表（前端用作轮询入口）
"""

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, select

from app.core.dependencies import ArqPoolDep, DBSessionDep
from app.models.patch import Patch
from app.models.review import Review, ReviewStatus

router = APIRouter(prefix="/reviews", tags=["patches"])


# ── 响应 Schema ───────────────────────────────────────────────────────────────


class PatchResponse(BaseModel):
    id: str
    review_id: str
    issue_id: str
    original_code: str
    fixed_code: str
    diff: str
    syntax_valid: bool
    error_msg: str | None
    status: str
    is_final: bool
    created_at: str


class PatchListResponse(BaseModel):
    review_id: str
    total: int
    patches: list[PatchResponse]


class AutoFixTriggerResponse(BaseModel):
    review_id: str
    status: str


# ── 路由 ──────────────────────────────────────────────────────────────────────


@router.post(
    "/{review_id}/autofix",
    response_model=AutoFixTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_autofix(
    review_id: str, db: DBSessionDep, arq: ArqPoolDep
) -> AutoFixTriggerResponse:
    try:
        uid = uuid.UUID(review_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid review_id format")

    review = await db.get(Review, uid)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.status != ReviewStatus.done:
        raise HTTPException(
            status_code=409,
            detail=f"Review must be in 'done' status to autofix, current: {review.status.value}",
        )
    if not review.source_code:
        raise HTTPException(
            status_code=409,
            detail="Review has no source_code stored; cannot generate patches",
        )

    # race fix：trigger 同步 DELETE + commit 旧 patches，让前端 polling
    # 永远拉不到上一轮残留（task 里的 DELETE 仍保留作幂等保护）
    await db.execute(delete(Patch).where(Patch.review_id == uid))
    await db.commit()

    await arq.enqueue_job("run_autofix_task", review_id)

    return AutoFixTriggerResponse(review_id=review_id, status="queued")


@router.get("/{review_id}/patches", response_model=PatchListResponse)
async def list_patches(review_id: str, db: DBSessionDep) -> PatchListResponse:
    try:
        uid = uuid.UUID(review_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid review_id format")

    result = await db.execute(
        select(Patch)
        .where(Patch.review_id == uid)
        .order_by(Patch.is_final.desc(), Patch.created_at.asc())
    )
    rows = list(result.scalars())
    return PatchListResponse(
        review_id=review_id,
        total=len(rows),
        patches=[
            PatchResponse(
                id=str(p.id),
                review_id=str(p.review_id),
                issue_id=str(p.issue_id),
                original_code=p.original_code,
                fixed_code=p.fixed_code,
                diff=p.diff,
                syntax_valid=p.syntax_valid,
                error_msg=p.error_msg,
                status=p.status.value,
                is_final=p.is_final,
                created_at=p.created_at.isoformat(),
            )
            for p in rows
        ],
    )
