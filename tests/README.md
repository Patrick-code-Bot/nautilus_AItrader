# Testing

Unit tests run offline (no exchange, no LLM network calls) and need only the
project requirements installed (`nautilus_trader`, `anthropic`, `openai`).

```bash
# All offline tests
python -m pytest tests -q --deselect tests/manual_order_test.py

# Individual files also run as plain scripts
python tests/test_llm_client.py
python tests/test_bracket_order.py
python tests/test_strategy_components.py
python tests/test_rounding_fix.py
python tests/test_integration_mock.py

# Manual Binance connectivity / order test (needs real keys; use --dry-run)
python tests/manual_order_test.py --dry-run --signal BUY
```

## Files

| File | Covers |
|---|---|
| `helpers.py` | `make_strategy_stub()` - binds the strategy's Python methods onto a plain object so Cython read-only attributes (`cache`, `log`, ...) can be stubbed |
| `test_llm_client.py` | Claude (Anthropic) request shape incl. `output_config` structured outputs + `effort`, graceful fallback when structured outputs are rejected, response validation (unknown enum values -> HOLD), retry -> fallback, OpenAI-compatible path, JSON extraction |
| `test_bracket_order.py` | Bracket SL/TP pricing (S/R and ATR), no unprotected entries, partial-TP state without trailing (regression), trailing stop **modifies** the SL in place (regression: cancelling it cancelled the OUO-linked TP), native-stop fallback after restart, SL never moves backwards |
| `test_strategy_components.py` | Risk-based position sizing (leverage cap, min-notional skip, confidence/RSI modifiers), SL/TP maths, daily-loss guard (live-vs-live only), pause expiry, anti-churn ignores HOLD runs, close-only reversals, pyramiding block |
| `test_rounding_fix.py` | Quantity flooring to 0.001 and the Phase 0 "skip, never upsize" rule |
| `test_integration_mock.py` | Mocked Binance -> indicators -> AI -> order-decision flow |

## Live tests on Binance Futures Testnet (paper money)

Testnet/demo keys are separate from live keys (create them at
testnet.binancefuture.com) and are rejected by live Binance with
`-2015`/`-2008`. Set `BINANCE_ENV=testnet` (or `demo`) in `.env`.

**1. Signal-only (no orders), real market data + real Claude calls**

```bash
TEST_MODE=true AUTO_CONFIRM=true TIMER_INTERVAL_SEC=60 python main_live.py
```

Expect in the log: `LLM analyzer ready`, `Pre-fetched 199 bars ... Indicators
ready: True`, `Subscribed to ...15-MINUTE...`, then one `🤖 Signal:` line per
cycle without `FALLBACK`, and `Signal-only mode: signal recorded`. Signals are
appended to `logs/signal_log.jsonl` for `tools/score_signals.py`.

**2. Order path (paper orders), forced first signal + restart + manual close**

```bash
TEST_MODE=false FORCE_SIGNAL=BUY TIMER_INTERVAL_SEC=60 python main_live.py
```

`FORCE_SIGNAL` is refused when `BINANCE_ENV=live`. The first cycle pushes a
synthetic HIGH-confidence signal through the unchanged risk guards, sizing,
bracket order and disaster-stop code; later cycles use the LLM. Expect
`Position Sizing`, `Opening long position ... (MARKET)`, `Order filled`,
`Position opened`, `Exchange-side exits armed`, `Native disaster stop submitted`.
Then kill the process (Ctrl-C / `./stop_trader.sh`) with the position open and
start it again WITHOUT `FORCE_SIGNAL`: expect `Re-adopting open LONG position
... persisted state restored` and `Exchange-side exits already live` with no
new orders. Closing the position from the Binance UI while the node runs must
log `Position closed`, `Cancelled SL exit order`, `Cancelled TP exit order`,
`Cancelled disaster stop`, and remove `logs/position_state.json`.

Verified 2026-10-21 on testnet for all of the above.

Note: Binance Futures now serves conditional orders (STOP_MARKET etc.) through
its **algo-order API** - they appear under `GET /fapi/v1/openAlgoOrders`, not
`GET /fapi/v1/openOrders`. Checking only `openOrders` wrongly suggests the
stop is missing.

Binance does NOT auto-cancel reduce-only algo orders when a position is closed
by an external order; the strategy cancels them itself (claimed external fills)
and sweeps any leftovers at startup / each cycle when flat.

**Observed on 2026-10-21 (testnet, claude-opus-5-5, effort=medium):** Claude
latency 6.7-9.7 s per cycle; sizing on $5,000 paper equity -> 0.118 BTC
(capped at 2x equity notional); round-trip taker commission ~$8 on ~$9.9k
notional.

## One-week replay with real LLM decisions (`tools/replay_week.py`)

```bash
python tools/replay_week.py decide --days 7 --workers 4 --time-budget 150   # resumable; ~675 LLM calls
python tools/replay_week.py simulate --equity 500 [--no-regime-filter] [--min-confidence LOW]
```

Feeds the last N days of real 15m klines through `TechnicalIndicatorManager`,
asks the configured model for a signal at every bar close (same prompt as
live, but shown no open position), then simulates the live execution rules
(risk sizing, ATR SL/TP, partial TP, ATR trailing, regime filter, kill-switches,
taker fees 0.05%/side, 0.02% slippage). Decisions are checkpointed in
`logs/replay/decisions.jsonl`; results in `logs/replay/result_<equity>.json`.

Result for 2026-10-15 → 2026-10-22 (claude-opus-5-5, effort medium, 675 decisions,
0 fallbacks): 95% HOLD, 22 SELL / 9 BUY; with $500: 8 trades, 50% win rate,
profit factor 0.90, net **-$1.66 (-0.33%)**, fees $7.49, max drawdown 2.6%
(BTC +2.06% buy-and-hold). Without the regime filter: +$6.28 (+1.26%, 13
trades, PF 1.25). Eight trades is far too small a sample to claim an edge
either way; fees were the largest single line item.
