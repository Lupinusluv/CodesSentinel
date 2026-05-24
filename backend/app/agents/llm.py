from langchain_openai import ChatOpenAI

from app.core.config import get_settings


def get_llm(temperature: float = 0.1) -> ChatOpenAI:
    """返回指向 DeepSeek API 的 ChatOpenAI 实例。

    每次调用返回新实例（无状态，实例化开销极低）。
    temperature 低是为了让审查结果更稳定一致。
    """
    s = get_settings()
    return ChatOpenAI(
        model=s.deepseek_model,
        api_key=s.deepseek_api_key,
        base_url=s.deepseek_base_url,
        temperature=temperature,
        streaming=True,
    )
