from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("")
async def metrics_summary() -> dict[str, str]:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="metrics_summary not implemented yet",
    )


@router.get("/issues")
async def issues_distribution() -> dict[str, str]:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="issues_distribution not implemented yet",
    )
