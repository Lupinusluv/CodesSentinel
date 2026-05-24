"""Agent 共用工具函数。"""

import json
import re

from app.agents.state import IssueOutput
from app.core.logging import get_logger

log = get_logger(__name__)


def parse_agent_json(text: str, category: str, log_name: str) -> list[IssueOutput]:
    """从 Agent 响应中提取 JSON issue 列表。

    Agent 被要求直接输出 JSON 数组，但有时会包裹在 ```json...``` 中。
    用正则安全剥离 markdown fence，再解析。
    """
    try:
        cleaned = re.sub(r'^```(?:json)?\s*', '', text.strip())
        cleaned = re.sub(r'\s*```$', '', cleaned).strip()
        raw = json.loads(cleaned)
        items = raw if isinstance(raw, list) else []
        return [IssueOutput.model_validate({**item, "category": category}) for item in items]
    except Exception as exc:
        log.warning(f"{log_name}_parse_error", error=str(exc), preview=text[:200])
        return []
