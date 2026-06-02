"""Agent 共用工具函数。"""

import json
import re

from app.agents.state import IssueOutput
from app.core.logging import get_logger

log = get_logger(__name__)


def parse_agent_json(text: str, category: str, log_name: str) -> tuple[list[IssueOutput], bool]:
    """从 Agent 响应中提取 JSON issue 列表。

    Agent 被要求直接输出 JSON 数组，但有时会包裹在 ```json...``` 中。
    用正则安全剥离 markdown fence，再解析。

    返回 (issues, ok)：ok=False 表示解析失败（非法 JSON 或非数组）。失败时仍返回 []
    保持降级不崩，但由 bool 信号让上游把"整类问题被吞掉"上报，避免静默漏报。
    """
    try:
        cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
        raw = json.loads(cleaned)
        # 非数组（如对象/标量）不是合法 issue 列表，按解析失败处理并发信号
        if not isinstance(raw, list):
            log.warning(f"{log_name}_parse_error", error="expected JSON array", preview=text[:200])
            return [], False
        issues = [IssueOutput.model_validate({**item, "category": category}) for item in raw]
        return issues, True
    except Exception as exc:
        log.warning(f"{log_name}_parse_error", error=str(exc), preview=text[:200])
        return [], False
