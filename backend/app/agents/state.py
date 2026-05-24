import operator
from typing import Annotated

from typing_extensions import TypedDict

from app.models.issue import IssueCategory, IssueSeverity
from pydantic import BaseModel


class IssueOutput(BaseModel):
    """单条审查问题，由 Agent 节点输出。"""

    category: IssueCategory
    severity: IssueSeverity
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    description: str
    suggestion: str | None = None


class ReviewState(TypedDict):
    """LangGraph 图的共享状态。

    issues 使用 operator.add 作为 Reducer，允许三个并行 Agent 节点各自追加
    自己的 issue 列表，LangGraph 会在 superstep 结束时合并，而非覆盖。
    """

    source_code: str
    language: str
    rag_context: str                                    # RAG 节点写入，Agent 节点只读
    issues: Annotated[list[IssueOutput], operator.add]  # 并行节点安全追加
    report_text: str                                    # Synthesis 节点写入
    error: str | None                                   # 任意节点写入错误信息
