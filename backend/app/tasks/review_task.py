"""审查后台任务（ARQ）。

流式协议：
  {"type": "agent_start",      "agent": "security"|"performance"|"style"|"synthesis"}
  {"type": "agent_done",       "agent": "...", "issue_count": N}
  {"type": "synthesis_token",  "content": "..."}   ← synthesis LLM 逐 token
  {"type": "done",             "issue_count": N, "duration_ms": N}
  {"type": "error",            "message": "..."}
"""

import json
import re
import time
import uuid

from app.agents.graph import compiled_graph
from app.agents.state import IssueOutput, ReviewState
from app.agents.synthesis_agent import deduplicate_issues
from app.core.dependencies import get_redis, get_session_factory
from app.core.logging import get_logger
from app.models.issue import Issue
from app.models.review import Review, ReviewStatus

log = get_logger(__name__)

_STREAM_CHANNEL = "review:{review_id}:stream"
_AGENT_NODES = {"security", "performance", "style"}


async def run_review_task(ctx: dict, review_id: str, source_code: str, language: str) -> None:
    """ARQ 入口：驱动 LangGraph 图，推送进度事件到 Redis Pub/Sub。"""
    channel = _STREAM_CHANNEL.format(review_id=review_id)
    session_factory = get_session_factory()
    redis = get_redis()
    started_at = time.monotonic()

    async with session_factory() as db:
        review = await db.get(Review, uuid.UUID(review_id))
        if review is None:
            log.error("review_not_found", review_id=review_id)
            return

        try:
            review.status = ReviewStatus.running
            await db.commit()

            initial_state: ReviewState = {
                "source_code": source_code,
                "language": language,
                "rag_context": "",   # paste 模式无仓库上下文
                "issues": [],
                "report_text": "",
                "error": None,
            }

            final_state: ReviewState | None = None

            # astream_events 遍历图执行事件，按类型路由到 Pub/Sub 消息
            async for event in compiled_graph.astream_events(initial_state, version="v2"):
                kind: str = event["event"]
                name: str = event.get("name", "")
                tags: list[str] = event.get("tags", [])

                if kind == "on_chain_start" and name in _AGENT_NODES:
                    await redis.publish(channel, json.dumps({"type": "agent_start", "agent": name}))

                elif kind == "on_chain_end" and name in _AGENT_NODES:
                    output = event["data"].get("output") or {}
                    issue_count = len(output.get("issues", []))
                    msg = json.dumps({"type": "agent_done", "agent": name, "issue_count": issue_count})
                    await redis.publish(channel, msg)
                    # 持久化进度，供晚连接的 WS 追赶（TTL 1小时）
                    progress_key = f"review:{review_id}:progress"
                    await redis.hset(progress_key, name, issue_count)
                    await redis.expire(progress_key, 3600)

                elif kind == "on_chain_start" and name == "synthesis":
                    await redis.publish(channel, json.dumps({"type": "agent_start", "agent": "synthesis"}))

                elif kind == "on_chat_model_stream" and "synthesis" in tags:
                    token: str = event["data"]["chunk"].content
                    if token:
                        await redis.publish(channel, json.dumps({
                            "type": "synthesis_token",
                            "content": token,
                        }))

                elif kind == "on_chain_end" and name == "LangGraph":
                    # 图执行结束，拿到最终状态
                    final_state = event["data"].get("output")

            if final_state is None:
                raise RuntimeError("LangGraph returned no final state")

            # 三个并行 Agent 的输出经 Reducer 合并，写 DB 前统一去重
            issues: list[IssueOutput] = deduplicate_issues(final_state.get("issues", []))
            report_text: str = final_state.get("report_text", "")
            duration_ms = int((time.monotonic() - started_at) * 1000)

            review.status = ReviewStatus.done
            review.report_text = report_text
            review.total_issues = len(issues)
            review.duration_ms = duration_ms
            for issue in issues:
                db.add(Issue(
                    review_id=review.id,
                    category=issue.category,
                    severity=issue.severity,
                    file_path=issue.file_path,
                    line_start=issue.line_start,
                    line_end=issue.line_end,
                    description=issue.description,
                    suggestion=issue.suggestion,
                ))
            await db.commit()

            await redis.publish(channel, json.dumps({
                "type": "done",
                "issue_count": len(issues),
                "duration_ms": duration_ms,
            }))
            log.info("review_done", review_id=review_id, issues=len(issues), ms=duration_ms)

        except Exception as exc:
            log.exception("review_failed", review_id=review_id)
            try:
                review.status = ReviewStatus.failed
                review.error_message = str(exc)
                await db.commit()
            except Exception:
                pass
            await redis.publish(channel, json.dumps({"type": "error", "message": str(exc)}))


# ── 遗留：v0.1.0 单节点解析函数，供单元测试继续使用 ─────────────────────────────

def _parse_issues(text: str) -> list[IssueOutput]:
    """从 LLM 响应末尾的 ```json 块中提取结构化 issue 列表（v0.1.0 遗留）。"""
    matches = re.findall(r"```json\s*([\s\S]*?)\s*```", text)
    if not matches:
        log.warning("no_json_block_in_response", preview=text[-300:])
        return []
    try:
        raw = json.loads(matches[-1])
        items = raw if isinstance(raw, list) else raw.get("issues", [])
        return [IssueOutput.model_validate(item) for item in items]
    except Exception as exc:
        log.warning("issue_parse_error", error=str(exc), preview=matches[-1][:300])
        return []
