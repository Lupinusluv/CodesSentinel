import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.core.dependencies import DBSessionDep
from app.models.issue import Issue
from app.models.review import Review, ReviewStatus
from app.tasks.review_task import run_review_task

router = APIRouter(prefix="/reviews", tags=["reviews"])


# ── 请求 / 响应 Schema ────────────────────────────────────────────────────────

class CreateReviewRequest(BaseModel):
    source_code: str
    language: str = "python"


class IssueResponse(BaseModel):
    id: str
    category: str
    severity: str
    line_start: int | None
    line_end: int | None
    description: str
    suggestion: str | None
    fixed: bool


class ReviewResponse(BaseModel):
    id: str
    status: str
    language: str | None
    total_issues: int
    duration_ms: int | None
    created_at: str
    report_text: str | None = None
    issues: list[IssueResponse] = []


# ── 路由 ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ReviewResponse])
async def list_reviews(db: DBSessionDep) -> list[ReviewResponse]:
    result = await db.execute(
        select(Review).order_by(Review.created_at.desc()).limit(50)
    )
    return [_to_response(r) for r in result.scalars()]


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_review(
    body: CreateReviewRequest,
    background_tasks: BackgroundTasks,
    db: DBSessionDep,
) -> dict:
    if not body.source_code.strip():
        raise HTTPException(status_code=400, detail="source_code cannot be empty")

    review = Review(
        status=ReviewStatus.pending,
        language=body.language,
        source_code=body.source_code,
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)

    background_tasks.add_task(
        run_review_task,
        str(review.id),
        body.source_code,
        body.language,
    )

    return {"review_id": str(review.id), "status": review.status.value}


@router.get("/{review_id}", response_model=ReviewResponse)
async def get_review(review_id: str, db: DBSessionDep) -> ReviewResponse:
    try:
        uid = uuid.UUID(review_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid review_id format")

    review = await db.get(Review, uid)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")

    result = await db.execute(
        select(Issue).where(Issue.review_id == uid).order_by(Issue.severity)
    )
    return _to_response(review, list(result.scalars()))


# ── 内部工具 ──────────────────────────────────────────────────────────────────

def _to_response(review: Review, issues: list[Issue] | None = None) -> ReviewResponse:
    return ReviewResponse(
        id=str(review.id),
        status=review.status.value,
        language=review.language,
        total_issues=review.total_issues,
        duration_ms=review.duration_ms,
        created_at=review.created_at.isoformat(),
        report_text=review.report_text,
        issues=[
            IssueResponse(
                id=str(i.id),
                category=i.category.value,
                severity=i.severity.value,
                line_start=i.line_start,
                line_end=i.line_end,
                description=i.description,
                suggestion=i.suggestion,
                fixed=i.fixed,
            )
            for i in (issues or [])
        ],
    )
