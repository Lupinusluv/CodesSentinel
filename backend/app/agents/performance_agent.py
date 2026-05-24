from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.llm import get_llm
from app.agents.prompts import PERFORMANCE_SYSTEM_PROMPT, build_agent_prompt
from app.agents.state import IssueOutput, ReviewState
from app.agents.utils import parse_agent_json
from app.core.logging import get_logger

log = get_logger(__name__)


async def performance_node(state: ReviewState) -> dict:
    """专注性能问题的 Agent 节点。返回 {"issues": [...]} 供 Reducer 追加。"""
    messages = [
        SystemMessage(content=PERFORMANCE_SYSTEM_PROMPT),
        HumanMessage(content=build_agent_prompt(
            state["source_code"], state["language"], state.get("rag_context", "")
        )),
    ]
    llm = get_llm(temperature=0.0)
    response = await llm.ainvoke(messages)
    issues: list[IssueOutput] = parse_agent_json(response.content, "performance", "performance_agent")
    log.info("performance_agent_done", issue_count=len(issues))
    return {"issues": issues}
