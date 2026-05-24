from pydantic import BaseModel

from app.models.issue import IssueCategory, IssueSeverity


class IssueOutput(BaseModel):
    """单条审查问题，由 LLM 输出 JSON 解析而来。"""

    category: IssueCategory
    severity: IssueSeverity
    line_start: int | None = None
    line_end: int | None = None
    description: str
    suggestion: str | None = None


class ReviewResult(BaseModel):
    """一次完整审查的最终结果。"""

    report_text: str
    issues: list[IssueOutput]
