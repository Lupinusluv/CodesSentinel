from langchain_openai import ChatOpenAI

from app.core.config import get_settings


def get_llm(temperature: float = 0.1, tags: list[str] | None = None) -> ChatOpenAI:
    """返回指向 DeepSeek API 的 ChatOpenAI 实例。

    每次调用返回新实例（无状态，实例化开销极低）。
    tags 会附加到 LangChain 事件上，供 astream_events 过滤使用。
    """
    s = get_settings()
    return ChatOpenAI(
        model=s.deepseek_model,
        api_key=s.deepseek_api_key,
        base_url=s.deepseek_base_url,
        temperature=temperature,
        streaming=True,
        tags=tags or [],
    )
