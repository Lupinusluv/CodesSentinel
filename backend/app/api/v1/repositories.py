from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/repositories", tags=["repositories"])


@router.get("")
async def list_repositories() -> dict[str, str]:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="list_repositories not implemented yet",
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_repository() -> dict[str, str]:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="create_repository not implemented yet",
    )


@router.delete("/{repository_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_repository(repository_id: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="delete_repository not implemented yet",
    )
