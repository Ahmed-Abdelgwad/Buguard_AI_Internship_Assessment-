"""LLM factory — returns a ChatAnthropic instance from environment settings."""
from functools import lru_cache

from langchain_anthropic import ChatAnthropic

from app.config import settings


@lru_cache(maxsize=1)
def get_llm() -> ChatAnthropic:
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. "
            "Add it to your .env file before using AI features."
        )
    return ChatAnthropic(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        max_tokens=4096,
    )
