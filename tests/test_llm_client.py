"""
Unit tests for utils/llm_client.py (Anthropic Claude + OpenAI-compatible paths).

All network calls are mocked - these tests never hit an API.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.llm_client import (  # noqa: E402
    LLMAnalyzer,
    SIGNAL_SCHEMA,
    resolve_provider,
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_OPENAI_MODEL,
)

PRICE_DATA = {
    "price": 100_000.0,
    "timestamp": "2026-10-20T10:00:00",
    "high": 100_500.0,
    "low": 99_500.0,
    "volume": 1234.5,
    "price_change": 0.4,
    "kline_data": [
        {"open": 99_000 + i * 100, "high": 99_200 + i * 100, "low": 98_900 + i * 100,
         "close": 99_100 + i * 100, "volume": 100 + i, "timestamp": i}
        for i in range(10)
    ],
}
TECHNICAL_DATA = {
    "sma_5": 99_900.0, "sma_20": 99_500.0, "sma_50": 98_000.0,
    "rsi": 58.0, "macd": 120.0, "macd_signal": 80.0, "macd_histogram": 40.0,
    "bb_upper": 101_000.0, "bb_middle": 99_500.0, "bb_lower": 98_000.0, "bb_position": 0.67,
    "volume_ratio": 1.6, "support": 98_500.0, "resistance": 101_200.0, "atr": 350.0,
    "short_term_trend": "上涨", "medium_term_trend": "上涨", "overall_trend": "强势上涨",
    "macd_trend": "bullish",
}
SENTIMENT = {"positive_ratio": 0.62, "negative_ratio": 0.38, "net_sentiment": 0.24,
             "classification": "Greed"}
GOOD_SIGNAL = {
    "signal": "BUY", "confidence": "HIGH", "reason": "Strong uptrend with volume",
    "stop_loss": 98_400.0, "take_profit": 102_500.0,
    "trend_strength": "STRONG", "risk_assessment": "LOW",
}


def _anthropic_response(payload, stop_reason="end_turn"):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=3000, output_tokens=200),
    )


def _claude(**kwargs) -> LLMAnalyzer:
    analyzer = LLMAnalyzer(api_key="sk-ant-test", provider="anthropic", **kwargs)
    analyzer.client = Mock()
    return analyzer


# --------------------------------------------------------------- provider

def test_resolve_provider():
    assert resolve_provider("anthropic", "x") == "anthropic"
    assert resolve_provider("claude", "x") == "anthropic"
    assert resolve_provider("openai", "sk-ant-x") == "openai"
    assert resolve_provider("deepseek", "x") == "openai"
    assert resolve_provider("auto", "sk-ant-abc") == "anthropic"
    assert resolve_provider("auto", "sk-abc", model="claude-opus-5-5") == "anthropic"
    assert resolve_provider("auto", "sk-abc", model="deepseek-v4-pro") == "openai"
    assert resolve_provider(None, "abc", base_url="https://api.moonshot.cn/v1") == "openai"


def test_default_models_per_provider():
    assert _claude().model == DEFAULT_ANTHROPIC_MODEL
    o = LLMAnalyzer(api_key="sk-x", provider="openai")
    assert o.model == DEFAULT_OPENAI_MODEL and o.base_url == "https://api.deepseek.com"


def test_workspace_id_sets_default_header_and_is_optional():
    with_ws = LLMAnalyzer(api_key="sk-ant-test", provider="anthropic", workspace_id=" wrkspc_01ABC ")
    assert with_ws.workspace_id == "wrkspc_01ABC"
    assert with_ws.client.default_headers.get("anthropic-workspace-id") == "wrkspc_01ABC"
    without = LLMAnalyzer(api_key="sk-ant-test", provider="anthropic", workspace_id="")
    assert without.workspace_id is None
    assert "anthropic-workspace-id" not in without.client.default_headers


def test_missing_workspace_header_error_is_actionable():
    analyzer = _claude(max_retries=1)

    class BadRequest(Exception):
        status_code = 400

    analyzer.client.messages.create.side_effect = BadRequest(
        "This API key is not scoped to a workspace, so this request must include the "
        "anthropic-workspace-id header"
    )
    signal = analyzer.analyze(PRICE_DATA, TECHNICAL_DATA, None, None)
    assert signal["is_fallback"]
    assert analyzer._structured_output_supported is True  # not misdiagnosed as a schema problem
    assert analyzer.client.messages.create.call_count == 1


def test_signal_schema_is_closed_and_complete():
    assert SIGNAL_SCHEMA["additionalProperties"] is False
    assert set(SIGNAL_SCHEMA["required"]) == set(SIGNAL_SCHEMA["properties"])
    assert SIGNAL_SCHEMA["properties"]["signal"]["enum"] == ["BUY", "SELL", "HOLD"]


# ---------------------------------------------------------------- anthropic

def test_anthropic_request_uses_structured_outputs_and_effort():
    analyzer = _claude(effort="low", max_tokens=777)
    analyzer.client.messages.create.return_value = _anthropic_response(GOOD_SIGNAL)

    signal = analyzer.analyze(PRICE_DATA, TECHNICAL_DATA, SENTIMENT, None)

    kwargs = analyzer.client.messages.create.call_args.kwargs
    assert kwargs["model"] == DEFAULT_ANTHROPIC_MODEL
    assert kwargs["max_tokens"] == 777
    assert "temperature" not in kwargs  # not a Messages API parameter any more
    assert kwargs["output_config"]["effort"] == "low"
    assert kwargs["output_config"]["format"] == {"type": "json_schema", "schema": SIGNAL_SCHEMA}
    assert kwargs["messages"][0]["role"] == "user"
    assert "BTC/USDT FUTURES" in kwargs["messages"][0]["content"]
    assert "STRONG UPTREND" in kwargs["messages"][0]["content"]  # Chinese labels translated
    assert "Fear & Greed" in kwargs["messages"][0]["content"]
    assert isinstance(kwargs["system"], str) and "JSON" in kwargs["system"]

    assert signal["signal"] == "BUY" and signal["confidence"] == "HIGH"
    assert signal["provider"] == "anthropic" and signal["model"] == DEFAULT_ANTHROPIC_MODEL
    assert "is_fallback" not in signal
    assert analyzer.signal_history[-1]["signal"] == "BUY"


def test_anthropic_falls_back_to_plain_json_when_structured_outputs_rejected():
    analyzer = _claude()

    class BadRequest(Exception):
        status_code = 400

    analyzer.client.messages.create.side_effect = [
        BadRequest("output_config.format is not supported for this model"),
        _anthropic_response("```json\n" + json.dumps(GOOD_SIGNAL) + "\n```"),
    ]

    signal = analyzer.analyze(PRICE_DATA, TECHNICAL_DATA, None, None)

    assert signal["signal"] == "BUY"
    assert analyzer._structured_output_supported is False
    second_call = analyzer.client.messages.create.call_args_list[1].kwargs
    assert "output_config" not in second_call
    assert "DO NOT use double quotes" in second_call["messages"][0]["content"]


def test_anthropic_refusal_or_garbage_yields_hold_fallback():
    analyzer = _claude(max_retries=2)
    analyzer.client.messages.create.return_value = _anthropic_response("not json at all")

    signal = analyzer.analyze(PRICE_DATA, TECHNICAL_DATA, None, None)

    assert signal["signal"] == "HOLD" and signal["is_fallback"] is True
    assert analyzer.client.messages.create.call_count == 2  # retried, then fell back
    assert signal["stop_loss"] == 98_000.0 and signal["take_profit"] == 102_000.0
    assert analyzer.signal_history == []  # fallbacks are not recorded as signals


def test_api_exception_is_contained():
    analyzer = _claude(max_retries=1)
    analyzer.client.messages.create.side_effect = RuntimeError("connection reset")

    signal = analyzer.analyze(PRICE_DATA, TECHNICAL_DATA, None, None)

    assert signal["signal"] == "HOLD" and signal["is_fallback"]


# ------------------------------------------------------------ validation

def test_invalid_enum_values_are_rejected_not_coerced():
    """An unknown `signal` must never reach the execution layer (it used to
    be treated as a SHORT because anything != BUY became 'short')."""
    analyzer = _claude(max_retries=1)
    bad = dict(GOOD_SIGNAL, signal="WAIT")
    analyzer.client.messages.create.return_value = _anthropic_response(bad)

    signal = analyzer.analyze(PRICE_DATA, TECHNICAL_DATA, None, None)
    assert signal["signal"] == "HOLD" and signal["is_fallback"]


def test_lowercase_values_are_normalised():
    analyzer = _claude(max_retries=1)
    payload = dict(GOOD_SIGNAL, signal="sell", confidence="medium", stop_loss="101500",
                   take_profit="97000", trend_strength="weird", risk_assessment=None)
    analyzer.client.messages.create.return_value = _anthropic_response(payload)

    signal = analyzer.analyze(PRICE_DATA, TECHNICAL_DATA, None, None)
    assert signal["signal"] == "SELL" and signal["confidence"] == "MEDIUM"
    assert signal["stop_loss"] == 101_500.0 and signal["take_profit"] == 97_000.0
    assert signal["trend_strength"] == "MODERATE" and signal["risk_assessment"] == "MEDIUM"


def test_missing_required_field_triggers_fallback():
    analyzer = _claude(max_retries=1)
    payload = {k: v for k, v in GOOD_SIGNAL.items() if k != "stop_loss"}
    analyzer.client.messages.create.return_value = _anthropic_response(payload)
    assert analyzer.analyze(PRICE_DATA, TECHNICAL_DATA, None, None)["is_fallback"]


# ------------------------------------------------------------------ openai

def test_openai_compatible_path():
    analyzer = LLMAnalyzer(api_key="sk-x", provider="openai", model="kimi-k3",
                           base_url="https://api.moonshot.cn/v1", temperature=1.0)
    analyzer.client = Mock()
    analyzer.client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(GOOD_SIGNAL)))]
    )

    signal = analyzer.analyze(PRICE_DATA, TECHNICAL_DATA, SENTIMENT, {"side": "long",
                              "quantity": 0.01, "avg_px": 99_000.0, "unrealized_pnl": 10.0})

    kwargs = analyzer.client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "kimi-k3" and kwargs["temperature"] == 1.0
    assert kwargs["messages"][0]["role"] == "system"
    assert "LONG position" in kwargs["messages"][1]["content"]
    assert "DO NOT use double quotes" in kwargs["messages"][1]["content"]
    assert signal["signal"] == "BUY" and signal["provider"] == "openai"


def test_json_extraction_handles_fences_and_prose():
    analyzer = _claude()
    assert analyzer._safe_parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert analyzer._safe_parse_json('Sure! {"a": 1} Hope this helps.') == {"a": 1}
    assert analyzer._safe_parse_json('[1, 2]') is None
    assert analyzer._safe_parse_json('') is None
    multiline = '{\n  "signal": "SELL",\n  "reason": "a "quoted" word",\n  "stop_loss": 1\n}'
    assert analyzer._safe_parse_json(multiline)["reason"] == "a 'quoted' word"


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"✅ {name}")
            except AssertionError as e:
                failures += 1
                print(f"❌ {name}: {e}")
    sys.exit(1 if failures else 0)
