from fastapi import APIRouter

from app.api.v1 import health, metrics, repositories, reviews, webhooks

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(reviews.router)
api_router.include_router(repositories.router)
api_router.include_router(webhooks.router)
api_router.include_router(metrics.router)

__all__ = ["api_router"]
