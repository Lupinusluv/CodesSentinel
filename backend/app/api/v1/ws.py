import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.dependencies import get_redis, get_session_factory
from app.core.logging import get_logger
from app.models.review import Review, ReviewStatus

router = APIRouter(tags=["websocket"])
log = get_logger(__name__)

_TERMINAL_TYPES = {"done", "error"}


@router.websocket("/ws/{review_id}")
async def review_stream(websocket: WebSocket, review_id: str) -> None:
    """订阅指定审查的 Redis Pub/Sub 频道，将 token 流实时推送给 WebSocket 客户端。

    消息格式（JSON）：
      {"type": "token",  "content": "..."}   ← LLM 输出 token
      {"type": "done",   "issue_count": N}    ← 审查完成
      {"type": "error",  "message": "..."}    ← 发生错误
    """
    await websocket.accept()
    redis = get_redis()
    channel = f"review:{review_id}:stream"

    # 晚连接保护：若审查已结束，直接推终态消息，无需订阅频道
    try:
        uid = uuid.UUID(review_id)
        async with get_session_factory()() as db:
            review = await db.get(Review, uid)
        if review and review.status == ReviewStatus.done:
            await websocket.send_text(json.dumps({
                "type": "done",
                "issue_count": review.total_issues,
                "duration_ms": review.duration_ms,
            }))
            await websocket.close()
            return
        if review and review.status == ReviewStatus.failed:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": review.error_message or "review failed",
            }))
            await websocket.close()
            return
    except Exception:
        pass  # 若检查失败，降级走正常订阅流程

    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)
    log.info("ws_connected", review_id=review_id)

    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            data: str = message["data"]
            await websocket.send_text(data)

            try:
                if json.loads(data).get("type") in _TERMINAL_TYPES:
                    break
            except Exception:
                pass

    except WebSocketDisconnect:
        log.info("ws_disconnected", review_id=review_id)
    except Exception:
        log.exception("ws_error", review_id=review_id)
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        log.info("ws_closed", review_id=review_id)
