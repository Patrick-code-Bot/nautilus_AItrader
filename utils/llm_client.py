"""
LLM Trade-Decision Client for NautilusTrader

Provider-agnostic market analyser that turns technical indicators, K-line data,
sentiment and position state into a structured trading signal.

Supported providers
-------------------
* ``anthropic`` - Claude via the Anthropic Messages API (default). Uses
  structured outputs (``output_config.format`` with a JSON schema) so the
  response is guaranteed to be a schema-valid JSON object. Falls back to
  plain-text JSON parsing if the model/SDK rejects structured outputs.
* ``openai``    - Any OpenAI-compatible chat-completions endpoint
  (DeepSeek, Kimi/Moonshot, OpenAI, ...).

The analyser always returns a dict with the keys::

    signal          BUY | SELL | HOLD
    confidence      HIGH | MEDIUM | LOW
    reason          str
    stop_loss       float
    take_profit     float
    trend_strength  STRONG | MODERATE | WEAK
    risk_assessment LOW | MEDIUM | HIGH
    timestamp       "YYYY-MM-DD HH:MM:SS"
    is_fallback     bool (only present on the conservative fallback signal)

Anything the model returns that does not validate is replaced by a
conservative HOLD fallback - an unexpected value must never reach the
execution layer.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional

# Optional SDKs - imported lazily so that a missing SDK for an unused provider
# never breaks startup (and so unit tests can stub either module).
try:  # pragma: no cover - import guard
    import anthropic as _anthropic
except Exception:  # noqa: BLE001
    _anthropic = None

try:  # pragma: no cover - import guard
    from openai import OpenAI as _OpenAI
except Exception:  # noqa: BLE001
    _OpenAI = None


PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OPENAI = "openai"
PROVIDER_AUTO = "auto"

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5-5"
DEFAULT_OPENAI_MODEL = "deepseek-v4-pro"
DEFAULT_OPENAI_BASE_URL = "https://api.deepseek.com"

VALID_SIGNALS = ("BUY", "SELL", "HOLD")
VALID_CONFIDENCE = ("HIGH", "MEDIUM", "LOW")
VALID_TREND_STRENGTH = ("STRONG", "MODERATE", "WEAK")
VALID_RISK = ("LOW", "MEDIUM", "HIGH")
VALID_EFFORT = ("low", "medium", "high", "xhigh", "max")

# JSON schema used for Anthropic structured outputs (and for validation).
SIGNAL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "signal": {"type": "string", "enum": list(VALID_SIGNALS)},
        "confidence": {"type": "string", "enum": list(VALID_CONFIDENCE)},
        "reason": {
            "type": "string",
            "description": (
                "Concise analysis: (1) trend assessment, (2) key indicators, "
                "(3) support/resistance, (4) volume, (5) risk factors, "
                "(6) why this signal now."
            ),
        },
        "stop_loss": {"type": "number", "description": "Stop-loss price in USDT"},
        "take_profit": {"type": "number", "description": "Take-profit price in USDT"},
        "trend_strength": {"type": "string", "enum": list(VALID_TREND_STRENGTH)},
        "risk_assessment": {"type": "string", "enum": list(VALID_RISK)},
    },
    "required": [
        "signal",
        "confidence",
        "reason",
        "stop_loss",
        "take_profit",
        "trend_strength",
        "risk_assessment",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You are an elite algorithmic trading system specializing in "
    "cryptocurrency perpetual futures on Binance (BTCUSDT-PERP). "
    "You analyze 15-minute K-line data with precision, combining multiple "
    "technical indicators, market microstructure, and sentiment analysis. "
    "Your decisions must be data-driven, risk-aware, and optimized for the "
    "15-minute timeframe. You never invent data that was not provided. "
    "You respond with a single JSON object and nothing else."
)

# Internal trend labels produced by indicators/technical_manager.py are
# Chinese; translate them for the model prompt only (the strategy's sizing
# logic still keys off the original strings).
_TREND_LABELS = {
    "上涨": "UP",
    "下跌": "DOWN",
    "强势上涨": "STRONG UPTREND",
    "强势下跌": "STRONG DOWNTREND",
    "震荡整理": "RANGE / CONSOLIDATION",
}


class _StructuredOutputUnsupported(Exception):
    """Raised once when the Anthropic API/SDK rejects structured outputs."""


def resolve_provider(
    provider: Optional[str],
    api_key: Optional[str],
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> str:
    """
    Resolve the LLM provider name.

    Explicit ``anthropic`` / ``openai`` win. ``auto`` (or empty) picks
    Anthropic when the key looks like an Anthropic key, the model looks like a
    Claude model, or the base URL points at Anthropic; otherwise OpenAI-compatible.
    """
    prov = (provider or PROVIDER_AUTO).strip().lower()
    if prov in (PROVIDER_ANTHROPIC, "claude"):
        return PROVIDER_ANTHROPIC
    if prov in (PROVIDER_OPENAI, "deepseek", "kimi", "moonshot", "openai-compatible"):
        return PROVIDER_OPENAI

    key = api_key or ""
    mdl = (model or "").lower()
    url = (base_url or "").lower()
    if key.startswith("sk-ant-") or mdl.startswith("claude") or "anthropic" in url:
        return PROVIDER_ANTHROPIC
    return PROVIDER_OPENAI


class LLMAnalyzer:
    """
    LLM-powered market analyser producing structured trading signals.

    Parameters
    ----------
    api_key : str
        API key for the selected provider.
    model : str, optional
        Model name. Defaults to ``claude-sonnet-5-5`` (Anthropic) or
        ``deepseek-v4-pro`` (OpenAI-compatible).
    temperature : float
        Sampling temperature. Only used by OpenAI-compatible providers - the
        current Anthropic Messages API has no temperature parameter; use
        ``effort`` instead.
    base_url : str, optional
        API base URL. For Anthropic leave empty (SDK default) unless using a
        gateway. For OpenAI-compatible providers defaults to DeepSeek.
    max_retries : int
        Analysis-level retries (each one a full request) before falling back
        to a conservative HOLD signal.
    provider : str
        ``anthropic`` | ``openai`` | ``auto`` (see :func:`resolve_provider`).
    effort : str
        Anthropic ``output_config.effort``: low | medium | high | xhigh | max.
    timeout_sec : float
        Per-request HTTP timeout. The strategy calls this client synchronously
        from the trading event loop, so a bounded timeout is essential.
    max_tokens : int
        Max output tokens for the response.
    workspace_id : str, optional
        Anthropic workspace ID (``wrkspc_...``). Required when the API key is a
        multi-workspace key (not scoped to a single workspace): the API then
        rejects requests without an ``anthropic-workspace-id`` header. Found at
        https://platform.claude.com/settings/workspaces. Ignored for other providers.
    nautilus_logger : optional
        NautilusTrader logger (``self.log`` from a Strategy). Falls back to
        the standard ``logging`` module.
    """

    def __init__(
        self,
        api_key: str,
        model: Optional[str] = None,
        temperature: float = 0.1,
        base_url: Optional[str] = None,
        max_retries: int = 2,
        provider: str = PROVIDER_AUTO,
        effort: str = "medium",
        timeout_sec: float = 60.0,
        max_tokens: int = 1024,
        workspace_id: Optional[str] = None,
        nautilus_logger=None,
    ):
        if not api_key:
            raise ValueError("LLM API key not provided")

        self.provider = resolve_provider(provider, api_key, model, base_url)
        self.temperature = temperature
        self.max_retries = max(1, int(max_retries))
        self.timeout_sec = float(timeout_sec)
        self.max_tokens = int(max_tokens)
        self.workspace_id = (workspace_id or "").strip() or None
        self.effort = effort if effort in VALID_EFFORT else "medium"
        self._structured_output_supported = True  # Anthropic: disabled on first 400

        self._nautilus_log = nautilus_logger
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        if self.provider == PROVIDER_ANTHROPIC:
            if _anthropic is None:
                raise ImportError(
                    "The 'anthropic' package is required for LLM_PROVIDER=anthropic. "
                    "Install it with: pip install anthropic"
                )
            self.model = model or DEFAULT_ANTHROPIC_MODEL
            self.base_url = base_url or None
            client_kwargs: Dict[str, Any] = {
                "api_key": api_key,
                "timeout": self.timeout_sec,
                "max_retries": 1,  # transport-level retries; analysis retries handled here
            }
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            if self.workspace_id:
                # Multi-workspace keys must name the workspace on every request
                client_kwargs["default_headers"] = {"anthropic-workspace-id": self.workspace_id}
            self.client = _anthropic.Anthropic(**client_kwargs)
        else:
            if _OpenAI is None:
                raise ImportError(
                    "The 'openai' package is required for OpenAI-compatible providers. "
                    "Install it with: pip install openai"
                )
            self.model = model or DEFAULT_OPENAI_MODEL
            self.base_url = base_url or DEFAULT_OPENAI_BASE_URL
            self.client = _OpenAI(
                api_key=api_key,
                base_url=self.base_url,
                timeout=self.timeout_sec,
                max_retries=1,
            )

        # Track signal history (the strategy's anti-churn guard reads this)
        self.signal_history: list = []

        self._log_info(
            f"🧠 LLM analyzer ready: provider={self.provider} model={self.model}"
            + (f" effort={self.effort}" if self.provider == PROVIDER_ANTHROPIC
               else f" temperature={self.temperature} base_url={self.base_url}")
        )

    # ------------------------------------------------------------------ logging

    def _log_info(self, msg: str):
        if self._nautilus_log:
            self._nautilus_log.info(msg)
        else:
            self.logger.info(msg)

    def _log_warning(self, msg: str):
        if self._nautilus_log:
            self._nautilus_log.warning(msg)
        else:
            self.logger.warning(msg)

    def _log_error(self, msg: str):
        if self._nautilus_log:
            self._nautilus_log.error(msg)
        else:
            self.logger.error(msg)

    def _log_debug(self, msg: str):
        if self._nautilus_log:
            self._nautilus_log.debug(msg)
        else:
            self.logger.debug(msg)

    # ----------------------------------------------------------------- public API

    def analyze(
        self,
        price_data: Dict[str, Any],
        technical_data: Dict[str, Any],
        sentiment_data: Optional[Dict[str, Any]] = None,
        current_position: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Analyse market conditions and generate a validated trading signal.

        Retries up to ``max_retries`` times on request failure or an invalid
        response, then returns a conservative HOLD fallback.
        """
        for attempt in range(1, self.max_retries + 1):
            try:
                signal = self._analyze_once(
                    price_data, technical_data, sentiment_data, current_position
                )
                if signal and not signal.get("is_fallback", False):
                    return signal
                self._log_warning(
                    f"⚠️ LLM attempt {attempt}/{self.max_retries} produced no valid signal"
                )
            except Exception as e:  # noqa: BLE001 - never let the trading loop die
                self._log_error(
                    f"❌ LLM attempt {attempt}/{self.max_retries} failed: "
                    f"{type(e).__name__}: {e}"
                )

        return self._create_fallback_signal(price_data)

    # --------------------------------------------------------------- single call

    def _analyze_once(
        self,
        price_data: Dict[str, Any],
        technical_data: Dict[str, Any],
        sentiment_data: Optional[Dict[str, Any]],
        current_position: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        def _prompt() -> str:
            structured = self.provider == PROVIDER_ANTHROPIC and self._structured_output_supported
            return self._build_analysis_prompt(
                price_data, technical_data, sentiment_data, current_position,
                structured_output=structured,
            )

        if self.provider == PROVIDER_ANTHROPIC:
            try:
                raw = self._call_anthropic(_prompt())
            except _StructuredOutputUnsupported:
                # Flag flipped inside _call_anthropic -> rebuild the prompt with
                # explicit JSON formatting instructions and call once more.
                raw = self._call_anthropic(_prompt())
        else:
            raw = self._call_openai(_prompt())

        self._log_info(f"🤖 LLM raw response ({self.provider}/{self.model}): {raw[:500]}")

        parsed = self._safe_parse_json(raw)
        if parsed is None:
            self._log_error(f"❌ Could not parse JSON from LLM response: {raw[:200]}")
            return self._create_fallback_signal(price_data)

        signal_data = self._validate_signal(parsed, price_data)
        if signal_data is None:
            return self._create_fallback_signal(price_data)

        signal_data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        signal_data["provider"] = self.provider
        signal_data["model"] = self.model

        self.signal_history.append(signal_data)
        if len(self.signal_history) > 30:
            self.signal_history.pop(0)

        self._log_signal_stats(signal_data)
        return signal_data

    def _call_anthropic(self, prompt: str) -> str:
        """Call the Anthropic Messages API, preferring structured outputs."""
        request: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self._structured_output_supported:
            request["output_config"] = {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": SIGNAL_SCHEMA},
            }

        try:
            response = self.client.messages.create(**request)
        except TypeError as e:
            # Older SDK without output_config support -> plain prompt mode
            if "output_config" in str(e) and self._structured_output_supported:
                self._log_warning(
                    "⚠️ Installed anthropic SDK does not support output_config; "
                    "falling back to plain JSON responses (pip install -U anthropic)"
                )
                self._structured_output_supported = False
                raise _StructuredOutputUnsupported() from e
            raise
        except Exception as e:  # noqa: BLE001
            status = getattr(e, "status_code", None)
            text = str(e)
            if status == 400 and "anthropic-workspace-id" in text:
                # Multi-workspace key without a workspace header: configuration
                # problem, not a model problem - say exactly what to set.
                raise RuntimeError(
                    "Anthropic API key is not scoped to a workspace. Set "
                    "ANTHROPIC_WORKSPACE_ID=wrkspc_... in .env (see "
                    "https://platform.claude.com/settings/workspaces) or create a key "
                    "scoped to a single workspace."
                ) from e
            # A 400 mentioning output_config/effort means this model/gateway
            # rejects structured outputs -> degrade gracefully (once).
            if (
                self._structured_output_supported
                and status == 400
                and ("output_config" in text or "effort" in text or "format" in text)
            ):
                self._log_warning(
                    f"⚠️ Structured outputs rejected by API ({text[:160]}); "
                    "falling back to plain JSON responses"
                )
                self._structured_output_supported = False
                raise _StructuredOutputUnsupported() from e
            raise

        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "max_tokens":
            self._log_warning("⚠️ Claude response truncated (max_tokens); parsing best effort")
        elif stop_reason == "refusal":
            self._log_warning("⚠️ Claude refused the request; using fallback signal")
            return ""

        usage = getattr(response, "usage", None)
        if usage is not None:
            self._log_debug(
                f"📊 Claude usage: in={getattr(usage, 'input_tokens', '?')} "
                f"out={getattr(usage, 'output_tokens', '?')}"
            )

        texts = [
            getattr(block, "text", "")
            for block in getattr(response, "content", []) or []
            if getattr(block, "type", "") == "text"
        ]
        return "\n".join(t for t in texts if t)

    def _call_openai(self, prompt: str) -> str:
        """Call an OpenAI-compatible chat-completions endpoint."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            stream=False,
            temperature=self.temperature,
        )
        content = response.choices[0].message.content
        return content or ""

    # ---------------------------------------------------------------- validation

    def _validate_signal(
        self, data: Dict[str, Any], price_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Normalise and validate a parsed response.

        Returns None when the response is unusable. Unknown enum values are
        rejected rather than coerced: an unexpected ``signal`` must never be
        interpreted by the execution layer.
        """
        if not isinstance(data, dict):
            return None

        required = ["signal", "confidence", "reason", "stop_loss", "take_profit"]
        missing = [f for f in required if f not in data]
        if missing:
            self._log_warning(f"⚠️ Missing required fields in LLM response: {missing}")
            return None

        signal = str(data.get("signal", "")).strip().upper()
        confidence = str(data.get("confidence", "")).strip().upper()
        if signal not in VALID_SIGNALS:
            self._log_warning(f"⚠️ Invalid signal value from LLM: {data.get('signal')!r}")
            return None
        if confidence not in VALID_CONFIDENCE:
            self._log_warning(f"⚠️ Invalid confidence value from LLM: {data.get('confidence')!r}")
            return None

        try:
            stop_loss = float(data["stop_loss"])
            take_profit = float(data["take_profit"])
        except (TypeError, ValueError):
            self._log_warning("⚠️ stop_loss/take_profit are not numeric in LLM response")
            return None

        price = float(price_data.get("price", 0) or 0)
        if price > 0:
            if signal == "BUY" and not (stop_loss < price < take_profit):
                self._log_warning(
                    f"⚠️ BUY levels inconsistent (SL {stop_loss:.2f} / price {price:.2f} / "
                    f"TP {take_profit:.2f}); strategy will use its own ATR/S-R exits"
                )
            elif signal == "SELL" and not (take_profit < price < stop_loss):
                self._log_warning(
                    f"⚠️ SELL levels inconsistent (TP {take_profit:.2f} / price {price:.2f} / "
                    f"SL {stop_loss:.2f}); strategy will use its own ATR/S-R exits"
                )

        trend_strength = str(data.get("trend_strength", "MODERATE")).strip().upper()
        if trend_strength not in VALID_TREND_STRENGTH:
            trend_strength = "MODERATE"
        risk_assessment = str(data.get("risk_assessment", "MEDIUM")).strip().upper()
        if risk_assessment not in VALID_RISK:
            risk_assessment = "MEDIUM"

        return {
            "signal": signal,
            "confidence": confidence,
            "reason": str(data.get("reason", "")).strip(),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "trend_strength": trend_strength,
            "risk_assessment": risk_assessment,
        }

    # ------------------------------------------------------------------- prompt

    def _build_analysis_prompt(
        self,
        price_data: Dict[str, Any],
        technical_data: Dict[str, Any],
        sentiment_data: Optional[Dict[str, Any]],
        current_position: Optional[Dict[str, Any]],
        structured_output: bool = False,
    ) -> str:
        """Build the full analysis prompt."""
        kline_text = self._format_kline_data(price_data.get("kline_data", []))
        technical_text = self._format_technical_data(technical_data)
        sentiment_text = self._format_sentiment_data(sentiment_data)
        position_text = self._format_position_data(current_position)

        signal_text = ""
        if self.signal_history:
            last_signal = self.signal_history[-1]
            signal_text = (
                f"\n【Previous Signal】\n"
                f"Signal: {last_signal.get('signal', 'N/A')}\n"
                f"Confidence: {last_signal.get('confidence', 'N/A')}"
            )

        rsi = float(technical_data.get("rsi", 0) or 0)
        rsi_label = "🔴 Overbought" if rsi > 70 else "🟢 Oversold" if rsi < 30 else "⚪ Neutral"

        prompt = f"""
═══════════════════════════════════════════════════════════════
  BTC/USDT FUTURES - 15-MINUTE TIMEFRAME ANALYSIS
═══════════════════════════════════════════════════════════════

【MARKET CONTEXT - REAL-TIME DATA】

{kline_text}

{technical_text}

{sentiment_text}

{signal_text}

【CURRENT MARKET STATE】
├─ Current Price: ${price_data['price']:,.2f}
├─ Time: {price_data['timestamp']}
├─ Period High: ${price_data.get('high', 0):,.2f}
├─ Period Low: ${price_data.get('low', 0):,.2f}
├─ Volume: {price_data.get('volume', 0):.2f} BTC
├─ Price Change: {price_data.get('price_change', 0):+.2f}%
└─ Current Position: {position_text}

【CRITICAL TECHNICAL STATUS】
├─ Overall Trend: {self._trend_label(technical_data.get('overall_trend'))}
├─ Short-term Trend: {self._trend_label(technical_data.get('short_term_trend'))}
├─ RSI: {rsi:.1f} ({rsi_label})
└─ MACD Direction: {technical_data.get('macd_trend', 'N/A')}

═══════════════════════════════════════════════════════════════
  TRADING STRATEGY FRAMEWORK - MUST FOLLOW
═══════════════════════════════════════════════════════════════

【1. DECISION HIERARCHY (Weight Distribution)】

Primary Layer (60% weight) - TECHNICAL ANALYSIS:
├─ Trend Direction (MA alignment, price action)
│  ├─ Strong uptrend: Price > SMA5 > SMA20 > SMA50 → BUY bias
│  ├─ Strong downtrend: Price < SMA5 < SMA20 < SMA50 → SELL bias
│  └─ Mixed/consolidation: No clear trend → HOLD/Cautious
├─ Support/Resistance Levels
│  ├─ Price near resistance with volume → Potential reversal SELL
│  ├─ Price near support with volume → Potential bounce BUY
│  └─ Price breaking key levels with volume → Strong signal
└─ K-line Patterns & Candlestick Formations
   ├─ Bullish patterns (hammer, engulfing, etc.) → BUY signal
   ├─ Bearish patterns (shooting star, dark cloud, etc.) → SELL signal
   └─ Doji/indecision → Wait for confirmation

Secondary Layer (30% weight) - MARKET SENTIMENT:
├─ Sentiment aligns with technical → Enhance confidence by 1 level
├─ Sentiment diverges from technical → Follow technical, sentiment as warning
└─ Sentiment data unavailable/delayed → Ignore, focus on technical

Tertiary Layer (10% weight) - RISK MANAGEMENT:
├─ Current position P&L status
├─ Stop-loss placement (should be 1-2% from entry)
└─ Position sizing constraints

【2. SIGNAL GENERATION LOGIC - STRICT RULES】

BUY Signal Conditions (require at least 3 of the following):
├─ ✅ Strong uptrend confirmed by MA alignment
├─ ✅ Price breaks above resistance with volume surge
├─ ✅ RSI recovering from oversold (< 40) or healthy momentum (40-60)
├─ ✅ MACD bullish crossover or positive histogram
├─ ✅ Bullish K-line pattern (hammer, bullish engulfing, etc.)
└─ ✅ Sentiment positive (if available, adds confidence)

SELL Signal Conditions (require at least 3 of the following):
├─ ✅ Strong downtrend confirmed by MA alignment
├─ ✅ Price breaks below support with volume surge
├─ ✅ RSI declining from overbought (> 60) or strong bearish momentum
├─ ✅ MACD bearish crossover or negative histogram
├─ ✅ Bearish K-line pattern (shooting star, bearish engulfing, etc.)
└─ ✅ Sentiment negative (if available, adds confidence)

HOLD Signal Conditions:
├─ ⚠️ Consolidation/narrow range trading (no clear direction)
├─ ⚠️ Mixed signals (some indicators bullish, some bearish)
├─ ⚠️ Waiting for confirmation (potential reversal but not confirmed)
└─ ⚠️ Low volume with indecisive candles

【3. CONFIDENCE LEVEL ASSIGNMENT】

HIGH Confidence:
├─ 3+ technical indicators align
├─ Clear trend with strong volume
├─ Price action confirms indicator signals
└─ Sentiment supports (if available)

MEDIUM Confidence:
├─ 2 technical indicators align
├─ Moderate trend strength
├─ Some conflicting signals present
└─ Sentiment neutral or unavailable

LOW Confidence:
├─ Only 1 strong indicator
├─ Mixed signals predominant
├─ Low volume/consolidation phase
└─ Sentiment contradicts technical

【4. ANTI-OVERTRADING PRINCIPLES】

1. Trend Continuity: don't reverse on a single candle; require 2-3 bars confirming a reversal
2. Position Stability: maintain direction unless a clear reversal pattern appears
3. Signal Confirmation: when in doubt, HOLD - a missed trade costs less than a wrong one
4. Volume Validation: high-confidence signals require volume confirmation

【5. 15-MINUTE TIMEFRAME SPECIFIC CONSIDERATIONS】

├─ Balanced timeframe for both trend following and swing trading
├─ Volume analysis is important for confirmation
├─ RSI > 70 or < 30 indicates strong momentum (act with caution)
└─ MACD crossovers are significant and should be respected

【6. RISK MANAGEMENT INTEGRATION】

Stop-Loss Placement:
├─ BUY signal: 1-2% below entry or below recent support
├─ SELL signal: 1-2% above entry or above recent resistance
└─ Consider volatility: tighter stops in volatile conditions

Take-Profit Targets:
├─ High confidence: 2-3% target
├─ Medium confidence: 1.5-2% target
└─ Low confidence: 1% target or consider HOLD

Position Management:
├─ Existing LONG: trend continues → BUY; trend reverses → SELL to close; loss > 2% → consider cutting
└─ Existing SHORT: trend continues → SELL; trend reverses → BUY to close; loss > 2% → consider cutting

═══════════════════════════════════════════════════════════════
  OUTPUT REQUIREMENTS
═══════════════════════════════════════════════════════════════
{self._output_instructions(structured_output)}
Level sanity rules:
- BUY: stop_loss < current_price < take_profit (e.g. SL ≈ price × 0.98-0.99, TP ≈ price × 1.02-1.03)
- SELL: take_profit < current_price < stop_loss (e.g. SL ≈ price × 1.01-1.02, TP ≈ price × 0.97-0.98)
- HOLD: set stop_loss and take_profit to the current price

Remember: be decisive but not reckless. Quality over quantity.
"""
        return prompt

    @staticmethod
    def _output_instructions(structured_output: bool) -> str:
        if structured_output:
            return (
                "\nReturn exactly one JSON object matching the provided schema "
                "(signal, confidence, reason, stop_loss, take_profit, trend_strength, "
                "risk_assessment). Keep 'reason' under 120 words.\n"
            )
        return """
CRITICAL: Your response MUST be a single valid JSON object only - no markdown fences, no extra text.

JSON formatting rules:
1. DO NOT use double quotes (") inside string values - use single quotes or parentheses for emphasis
2. The "reason" field must be one continuous string under 120 words

JSON Format:
{
    "signal": "BUY|SELL|HOLD",
    "confidence": "HIGH|MEDIUM|LOW",
    "reason": "Concise analysis: (1) trend, (2) key indicators, (3) support/resistance, (4) volume, (5) risk factors, (6) why this signal now.",
    "stop_loss": <numerical_price_value>,
    "take_profit": <numerical_price_value>,
    "trend_strength": "STRONG|MODERATE|WEAK",
    "risk_assessment": "LOW|MEDIUM|HIGH"
}
"""

    @staticmethod
    def _trend_label(value: Any) -> str:
        if value is None:
            return "N/A"
        return _TREND_LABELS.get(str(value), str(value))

    def _format_kline_data(self, kline_data: list) -> str:
        """Format K-line data for the prompt."""
        if not kline_data:
            return "【Recent K-line Data】\nNo K-line data available"

        kline_text = "【Recent 10 15-minute K-lines (oldest → most recent)】\n"
        for i, kline in enumerate(kline_data[-10:], 1):
            candle_type = "🟢 Bullish" if kline['close'] > kline['open'] else "🔴 Bearish"
            change = ((kline['close'] - kline['open']) / kline['open']) * 100 if kline['open'] else 0.0
            body_size = abs(kline['close'] - kline['open'])
            total_range = kline['high'] - kline['low']
            body_ratio = (body_size / total_range * 100) if total_range > 0 else 0

            kline_text += (
                f"K{i}: {candle_type} | "
                f"O:{kline['open']:.2f} H:{kline['high']:.2f} L:{kline['low']:.2f} C:{kline['close']:.2f} | "
                f"Change:{change:+.2f}% | "
                f"Vol:{kline['volume']:.2f} | "
                f"Body:{body_ratio:.1f}%\n"
            )
        return kline_text

    def _format_technical_data(self, technical_data: Dict[str, Any]) -> str:
        """Format technical indicator data for the prompt."""

        def safe_float(val, default=0.0):
            try:
                return float(val) if val is not None else default
            except (TypeError, ValueError):
                return default

        rsi = safe_float(technical_data.get('rsi'))
        hist = safe_float(technical_data.get('macd_histogram'))
        bb_pos = safe_float(technical_data.get('bb_position'))
        vol_ratio = safe_float(technical_data.get('volume_ratio'))
        atr = safe_float(technical_data.get('atr'))

        text = f"""
【Technical Indicator Analysis】
📈 Moving Averages (SMA):
{self._format_sma_data(technical_data)}

🎯 Trend Analysis:
├─ Short-term: {self._trend_label(technical_data.get('short_term_trend'))}
├─ Medium-term: {self._trend_label(technical_data.get('medium_term_trend'))}
├─ Overall: {self._trend_label(technical_data.get('overall_trend'))}
└─ MACD Direction: {technical_data.get('macd_trend', 'N/A')}

📊 Momentum Indicators:
├─ RSI: {rsi:.2f} ({'🔴 Overbought (>70)' if rsi > 70 else '🟢 Oversold (<30)' if rsi < 30 else '⚪ Neutral (30-70)'})
├─ MACD Line: {safe_float(technical_data.get('macd')):.4f}
├─ Signal Line: {safe_float(technical_data.get('macd_signal')):.4f}
└─ Histogram: {hist:.4f} {'🟢 Bullish' if hist > 0 else '🔴 Bearish'}

🎚️ Bollinger Bands:
├─ Upper Band: {safe_float(technical_data.get('bb_upper')):.2f}
├─ Middle Band (SMA): {safe_float(technical_data.get('bb_middle')):.2f}
├─ Lower Band: {safe_float(technical_data.get('bb_lower')):.2f}
└─ Price Position: {bb_pos:.2%} ({'🔴 Near Upper (>80%)' if bb_pos > 0.8 else '🟢 Near Lower (<20%)' if bb_pos < 0.2 else '⚪ Middle Zone (20-80%)'})

💰 Key Levels:
├─ Resistance: ${safe_float(technical_data.get('resistance')):.2f}
└─ Support: ${safe_float(technical_data.get('support')):.2f}

📦 Volume & Volatility:
├─ Volume Ratio: {vol_ratio:.2f}x average ({'🟢 High Volume' if vol_ratio > 1.5 else '🔴 Low Volume' if vol_ratio < 0.5 else '⚪ Normal'})
└─ ATR(14): ${atr:.2f}
"""
        return text

    def _format_sma_data(self, technical_data: Dict[str, Any]) -> str:
        """Format SMA data dynamically based on available periods."""
        sma_keys = [key for key in technical_data.keys() if key.startswith('sma_')]
        if not sma_keys:
            return "├─ SMA data not available"

        lines = []
        for key in sorted(sma_keys, key=lambda x: int(x.split('_')[1])):
            period = key.split('_')[1]
            try:
                lines.append(f"├─ SMA {period}: ${float(technical_data[key]):,.2f}")
            except (TypeError, ValueError):
                lines.append(f"├─ SMA {period}: N/A")
        return "\n".join(lines)

    def _format_sentiment_data(self, sentiment_data: Optional[Dict[str, Any]]) -> str:
        """Format sentiment data for the prompt."""
        if not sentiment_data:
            return "【Market Sentiment】Data not available"

        sign = '+' if sentiment_data['net_sentiment'] >= 0 else ''
        label = sentiment_data.get('classification')
        label_text = f" | {label}" if label else ""
        return (
            f"【Market Sentiment (Fear & Greed)】"
            f"Bullish {sentiment_data['positive_ratio']:.1%} | "
            f"Bearish {sentiment_data['negative_ratio']:.1%} | "
            f"Net {sign}{sentiment_data['net_sentiment']:.3f}{label_text}"
        )

    def _format_position_data(self, position: Optional[Dict[str, Any]]) -> str:
        """Format position data for the prompt."""
        if not position:
            return "No position"

        return (
            f"{str(position.get('side', 'unknown')).upper()} position, "
            f"Size: {position.get('quantity', 0):.3f} BTC, "
            f"Avg Price: ${position.get('avg_px', 0):,.2f}, "
            f"Unrealized P&L: {position.get('unrealized_pnl', 0):+.2f} USDT"
        )

    # ------------------------------------------------------------------ parsing

    def _safe_parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Parse a JSON object out of a model response.

        Handles: clean JSON, markdown code fences, leading/trailing prose,
        and (as a last resort) stray double quotes inside string values.
        """
        if not text:
            return None

        candidate = text.strip()

        # Strip ```json ... ``` fences
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", candidate, re.DOTALL | re.IGNORECASE)
        if fence:
            candidate = fence.group(1).strip()

        try:
            obj = json.loads(candidate)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            pass

        # Extract the outermost {...}
        start = candidate.find('{')
        end = candidate.rfind('}')
        if start == -1 or end <= start:
            return None
        snippet = candidate[start:end + 1]

        try:
            obj = json.loads(snippet)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            pass

        # Last resort: replace stray double quotes inside string values
        try:
            fixed_lines = []
            for line in snippet.split('\n'):
                stripped = line.strip()
                if '": "' in line and stripped.endswith(('",', '"')):
                    key_end = line.find('": "') + 4
                    value_end = line.rfind('",') if stripped.endswith(',') else line.rfind('"')
                    if key_end > 4 and value_end > key_end:
                        prefix, value, suffix = line[:key_end], line[key_end:value_end], line[value_end:]
                        line = prefix + value.replace('"', "'") + suffix
                fixed_lines.append(line)
            obj = json.loads('\n'.join(fixed_lines))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError as e:
            self._log_error(f"❌ JSON parse failed: {e}")
            self._log_debug(f"Original content: {snippet[:500]}...")
        except Exception as e:  # noqa: BLE001
            self._log_error(f"❌ JSON fix error: {e}")

        return None

    # ----------------------------------------------------------------- fallback

    def _create_fallback_signal(self, price_data: Dict[str, Any]) -> Dict[str, Any]:
        """Conservative HOLD signal used when analysis fails."""
        price = float(price_data.get('price', 0) or 0)
        return {
            "signal": "HOLD",
            "reason": "Conservative fallback: AI analysis unavailable or invalid",
            "stop_loss": price * 0.98,
            "take_profit": price * 1.02,
            "confidence": "LOW",
            "trend_strength": "WEAK",
            "risk_assessment": "HIGH",
            "is_fallback": True,
            "provider": self.provider,
            "model": self.model,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _log_signal_stats(self, signal_data: Dict[str, Any]):
        """Log signal statistics."""
        signal = signal_data['signal']
        signal_count = sum(1 for s in self.signal_history if s.get('signal') == signal)
        total = len(self.signal_history)
        self._log_debug(
            f"📊 Signal Stats: {signal} (appeared {signal_count}/{total} times in recent history)"
        )

        if len(self.signal_history) >= 3:
            last_three = [s['signal'] for s in self.signal_history[-3:]]
            if len(set(last_three)) == 1:
                self._log_warning(f"⚠️ 3 consecutive {signal} signals")


# Backwards-compatible alias (the original DeepSeek-only class name)
DeepSeekAnalyzer = LLMAnalyzer

__all__ = [
    "LLMAnalyzer",
    "DeepSeekAnalyzer",
    "resolve_provider",
    "SIGNAL_SCHEMA",
    "PROVIDER_ANTHROPIC",
    "PROVIDER_OPENAI",
    "PROVIDER_AUTO",
    "DEFAULT_ANTHROPIC_MODEL",
    "DEFAULT_OPENAI_MODEL",
]
