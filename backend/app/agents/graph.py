"""LangGraph 主图：RAG → 并行三 Agent → Synthesis。

拓扑结构：
    START → rag_node
    rag_node → security_node, performance_node, style_node  (并行 superstep)
    security_node, performance_node, style_node → synthesis_node
    synthesis_node → END
"""

from langgraph.graph import END, START, StateGraph

from app.agents.performance_agent import performance_node
from app.agents.security_agent import security_node
from app.agents.state import ReviewState
from app.agents.style_agent import style_node
from app.agents.synthesis_agent import synthesis_node


async def rag_node(state: ReviewState) -> dict:
    """RAG 检索节点：为 paste 模式返回空字符串，webhook 模式注入仓库上下文。

    完整的 DB 查询由 review_task 在调用 graph 前注入 rag_context，
    此节点作为图中的占位，保持图结构清晰。
    """
    return {"rag_context": state.get("rag_context", "")}


def build_graph() -> StateGraph:
    graph = StateGraph(ReviewState)

    graph.add_node("rag",         rag_node)
    graph.add_node("security",    security_node)
    graph.add_node("performance", performance_node)
    graph.add_node("style",       style_node)
    graph.add_node("synthesis",   synthesis_node)

    graph.add_edge(START,         "rag")
    # 扇出：rag → 三个 Agent 同时执行（LangGraph 同一 superstep）
    graph.add_edge("rag",         "security")
    graph.add_edge("rag",         "performance")
    graph.add_edge("rag",         "style")
    # 扇入：三个 Agent 全部完成后才进入 synthesis
    graph.add_edge("security",    "synthesis")
    graph.add_edge("performance", "synthesis")
    graph.add_edge("style",       "synthesis")
    graph.add_edge("synthesis",   END)

    return graph


# 模块级单例，避免每次请求重新编译
compiled_graph = build_graph().compile()
