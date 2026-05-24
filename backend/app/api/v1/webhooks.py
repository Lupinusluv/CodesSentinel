from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook() -> dict[str, str]:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="github_webhook not implemented yet",
    )


@router.post("/gitlab", status_code=status.HTTP_202_ACCEPTED)
async def gitlab_webhook() -> dict[str, str]:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="gitlab_webhook not implemented yet",
    )


@router.post("/gitee", status_code=status.HTTP_202_ACCEPTED)
async def gitee_webhook() -> dict[str, str]:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="gitee_webhook not implemented yet",
    )
