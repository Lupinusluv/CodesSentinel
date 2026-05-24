"""
审查后台任务。

MVP 阶段用 FastAPI BackgroundTasks 驱动；
feat/arq-worker 分支将迁移为 ARQ 队列 Worker。
"""

import json
import re
import time
import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select

from app.agents.llm import get_llm
from app.agents.prompts import REVIEW_SYSTEM_PROMPT, build_review_prompt
from app.agents.state import IssueOutput
from app.core.dependencies import get_redis, get_session_factory
from app.core.logging import get_logger
from app.models.issue import Issue
from app.models.review import Review, ReviewStatus

log = get_logger(__name__)

_STREAM_CHANNEL = "review:{review_id}:stream"


async def run_review_task(review_id: str, source_code: str, language: str) -> None:
    """流式调用 LLM，将 token 推送到 Redis Pub/Sub，结束后将结果写入数据库。"""
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

            messages = [
                SystemMessage(content=REVIEW_SYSTEM_PROMPT),
                HumanMessage(content=build_review_prompt(source_code, language)),
            ]

            llm = get_llm()
            accumulated = ""
            async for chunk in llm.astream(messages):
                token = chunk.content
                if token:
                    accumulated += token
                    await redis.publish(
                        channel,
                        json.dumps({"type": "token", "content": token}),
                    )

            issues = _parse_issues(accumulated)
            duration_ms = int((time.monotonic() - started_at) * 1000)

            review.status = ReviewStatus.done
            review.report_text = accumulated
            review.total_issues = len(issues)
            review.duration_ms = duration_ms
            for issue in issues:
                db.add(Issue(
                    review_id=review.id,
                    category=issue.category,
                    severity=issue.severity,
                    line_start=issue.line_start,
                    line_end=issue.line_end,
                    description=issue.description,
                    suggestion=issue.suggestion,
                ))
            await db.commit()

            await redis.publish(
                channel,
                json.dumps({"type": "done", "issue_count": len(issues), "duration_ms": duration_ms}),
            )
            log.info("review_done", review_id=review_id, issues=len(issues), ms=duration_ms)

        except Exception as exc:
            log.exception("review_failed", review_id=review_id)
            try:
                review.status = ReviewStatus.failed
                review.error_message = str(exc)
                await db.commit()
            except Exception:
                pass
            await redis.publish(
                channel,
                json.dumps({"type": "error", "message": str(exc)}),
            )


def _parse_issues(text: str) -> list[IssueOutput]:
    """从 LLM 响应末尾的 ```json 块中提取结构化 issue 列表。"""
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
