"""
Backwards-compatibility shim.

The LLM decision layer now lives in ``utils.llm_client`` and supports both
Anthropic Claude (default) and any OpenAI-compatible provider (DeepSeek,
Kimi/Moonshot, ...). ``DeepSeekAnalyzer`` is kept as an alias so existing
imports keep working.
"""

from .llm_client import (  # noqa: F401
    LLMAnalyzer,
    DeepSeekAnalyzer,
    resolve_provider,
    SIGNAL_SCHEMA,
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
    PROVIDER_AUTO,
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_OPENAI_MODEL,
)

__all__ = ["LLMAnalyzer", "DeepSeekAnalyzer", "resolve_provider"]
