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
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "done",
                        "issue_count": review.total_issues,
                        "duration_ms": review.duration_ms,
                    }
                )
            )
            await websocket.close()
            return
        if review and review.status == ReviewStatus.failed:
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "error",
                        "message": review.error_message or "review failed",
                    }
                )
            )
            await websocket.close()
            return
    except Exception:
        pass  # 若检查失败，降级走正常订阅流程

    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)

    # 订阅完成后补发已完成的 agent 进度（解决 WS 连接晚于 agent_done 事件的竞态）
    try:
        progress_key = f"review:{review_id}:progress"
        completed: dict[str, str] = await redis.hgetall(progress_key)
        for agent_name, issue_count_str in completed.items():
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "agent_done",
                        "agent": agent_name,
                        "issue_count": int(issue_count_str),
                    }
                )
            )
    except Exception:
        pass  # 追赶失败不影响后续正常流

    # 二次检查：防止 subscribe 之前 review 已结束的竞态
    try:
        async with get_session_factory()() as db2:
            review2 = await db2.get(Review, uid)
        if review2 and review2.status == ReviewStatus.done:
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "done",
                        "issue_count": review2.total_issues,
                        "duration_ms": review2.duration_ms,
                    }
                )
            )
            await websocket.close()
            return
        if review2 and review2.status == ReviewStatus.failed:
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "error",
                        "message": review2.error_message or "review failed",
                    }
                )
            )
            await websocket.close()
            return
    except Exception:
        pass  # 若检查失败，降级继续监听频道

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
