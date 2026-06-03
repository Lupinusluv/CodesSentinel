from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.dependencies import DBSessionDep
from app.models.issue import Issue
from app.models.review import Review, ReviewStatus

router = APIRouter(prefix="/metrics", tags=["metrics"])


class MetricsSummary(BaseModel):
    total_reviews: int
    total_issues: int
    avg_duration_ms: int
    issues_by_category: dict[str, int]
    issues_by_severity: dict[str, int]


@router.get("", response_model=MetricsSummary)
async def metrics_summary(db: DBSessionDep) -> MetricsSummary:
    # Aggregate over completed reviews
    row = (
        await db.execute(
            select(
                func.count(Review.id),
                func.coalesce(func.sum(Review.total_issues), 0),
                func.coalesce(func.avg(Review.duration_ms), 0),
            ).where(Review.status == ReviewStatus.done)
        )
    ).one()

    # Per-category × per-severity distribution.
    # 与上面的 headline 口径一致：只统计 done 的 review（join + where），
    # 否则分布与 total_issues 可能分叉。
    dist_rows = (
        await db.execute(
            select(Issue.category, Issue.severity, func.count(Issue.id))
            .join(Review, Issue.review_id == Review.id)
            .where(Review.status == ReviewStatus.done)
            .group_by(Issue.category, Issue.severity)
        )
    ).all()

    issues_by_category: dict[str, int] = {}
    issues_by_severity: dict[str, int] = {}
    for cat, sev, cnt in dist_rows:
        cat_key = cat.value if hasattr(cat, "value") else str(cat)
        sev_key = sev.value if hasattr(sev, "value") else str(sev)
        issues_by_category[cat_key] = issues_by_category.get(cat_key, 0) + cnt
        issues_by_severity[sev_key] = issues_by_severity.get(sev_key, 0) + cnt

    return MetricsSummary(
        total_reviews=row[0],
        total_issues=int(row[1]),
        avg_duration_ms=round(float(row[2])) if row[2] else 0,
        issues_by_category=issues_by_category,
        issues_by_severity=issues_by_severity,
    )
