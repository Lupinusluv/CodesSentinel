import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.dependencies import get_redis
from app.core.logging import get_logger

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
