#!/usr/bin/env python3
"""
Replay the strategy over recent REAL market data with REAL LLM decisions, then
simulate execution with the strategy's own rules.

    python tools/replay_week.py decide   --days 7 --workers 4 --time-budget 150   # resumable
    python tools/replay_week.py simulate --equity 500

Phase "decide" fetches 15m / 4h klines (live Binance Futures) and the Fear &
Greed history, builds the exact technical snapshot the live strategy would see
at each 15m close (TechnicalIndicatorManager), asks the configured LLM
(utils.llm_client.LLMAnalyzer, same prompt) for a signal, and appends each
decision to logs/replay/decisions.jsonl (checkpointed; re-run until complete).

Phase "simulate" walks the bars with the decisions and applies the live rules:
regime filter, MEDIUM minimum confidence, risk-based sizing from LIVE equity
(1% x confidence/trend/RSI modifiers, 2x equity notional cap, $100 minimum
notional -> skip), ATR exits (SL 1.5 ATR, TP 3 ATR), partial TP 50% at 1R,
ATR trailing (activate 1 ATR, trail 1 ATR, 0.25 ATR step), close-only
reversals, no pyramiding, anti-churn, daily-loss and consecutive-loss pauses,
taker fees and slippage. Intrabar SL/TP are detected from highs/lows (SL first
when both are touched).

Approximation (deliberate): the LLM is shown NO open position and no previous
signal, so decisions are independent and can run in parallel. The live bot
shows both, which mainly affects HOLD-vs-maintain wording, not entries.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import requests  # noqa: E402

REPLAY_DIR = ROOT / "logs" / "replay"
KLINES_FILE = REPLAY_DIR / "klines_15m.json"
KLINES_4H_FILE = REPLAY_DIR / "klines_4h.json"
FNG_FILE = REPLAY_DIR / "fng.json"
DECISIONS_FILE = REPLAY_DIR / "decisions.jsonl"
LIVE_REST = "https://fapi.binance.com"
WARMUP_BARS = 200

# Strategy parameters mirrored from main_live.py / strategy defaults
RISK_PER_TRADE = 0.01
MAX_POS_LEVERAGE = 2.0
MIN_NOTIONAL = 100.0
MIN_QTY = 0.001
CONF_MULT = {"HIGH": 1.5, "MEDIUM": 1.0, "LOW": 0.5}
TREND_MULT = 1.2
RSI_EXTREME = (25.0, 75.0)
RSI_MULT = 0.7
SL_ATR, TP_ATR = 1.5, 3.0
TRAIL_ACT_ATR, TRAIL_DIST_ATR, TRAIL_STEP_ATR = 1.0, 1.0, 0.25
PARTIAL_R, PARTIAL_PCT = 1.0, 0.5
MIN_CONFIDENCE = "MEDIUM"
MAX_SAME_SIGNAL = 5
DAILY_LOSS_LIMIT = 0.03
MAX_CONSEC_LOSSES = 5
PAUSE_HOURS = 24
REGIME_FLAT_PCT = 0.002
TAKER_FEE = 0.0005   # Binance USDT-M VIP0 taker (per side)
SLIPPAGE = 0.0002    # per market execution, live BTCUSDT depth


# --------------------------------------------------------------------------- data

def fetch_json(url: str, params: dict) -> Any:
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def load_or_fetch_data(days: int) -> tuple[list, list, list]:
    REPLAY_DIR.mkdir(parents=True, exist_ok=True)
    if KLINES_FILE.exists():
        return (json.loads(KLINES_FILE.read_text()), json.loads(KLINES_4H_FILE.read_text()),
                json.loads(FNG_FILE.read_text()))
    now_ms = int(time.time() * 1000)
    need = WARMUP_BARS + days * 96 + 2
    k15: list = []
    end = now_ms
    while len(k15) < need:
        chunk = fetch_json(f"{LIVE_REST}/fapi/v1/klines",
                           {"symbol": "BTCUSDT", "interval": "15m", "limit": 1500, "endTime": end})
        if not chunk:
            break
        k15 = chunk + k15
        end = chunk[0][0] - 1
    k15 = [k for k in k15 if int(k[6]) <= now_ms][-need:]  # closed bars only
    k4h = fetch_json(f"{LIVE_REST}/fapi/v1/klines",
                     {"symbol": "BTCUSDT", "interval": "4h", "limit": 60 + days * 6 + 5, "endTime": now_ms})
    k4h = [k for k in k4h if int(k[6]) <= now_ms]
    fng = fetch_json("https://api.alternative.me/fng/", {"limit": days + 5}).get("data", [])
    KLINES_FILE.write_text(json.dumps(k15))
    KLINES_4H_FILE.write_text(json.dumps(k4h))
    FNG_FILE.write_text(json.dumps(fng))
    return k15, k4h, fng


def ema(values: List[float], period: int) -> float:
    k = 2.0 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def regime_at(k4h: list, ts_ms: int) -> str:
    closes = [float(k[4]) for k in k4h if int(k[6]) <= ts_ms]
    if len(closes) < 51:
        return "unknown"
    closes = closes[-60:]
    spread = (ema(closes, 20) - ema(closes, 50)) / closes[-1]
    if abs(spread) < REGIME_FLAT_PCT:
        return "flat"
    return "up" if spread > 0 else "down"


def sentiment_at(fng: list, ts_ms: int) -> Optional[Dict[str, Any]]:
    rows = sorted(((int(e["timestamp"]), e) for e in fng), key=lambda x: x[0])
    chosen = None
    for ts, e in rows:
        if ts * 1000 <= ts_ms:
            chosen = e
    if chosen is None:
        return None
    value = float(chosen["value"])
    return {"positive_ratio": value / 100, "negative_ratio": 1 - value / 100,
            "net_sentiment": (value - 50) / 50, "classification": chosen.get("value_classification", ""),
            "data_time": chosen["timestamp"], "data_delay_minutes": 0}


def build_snapshots(k15: list) -> List[Dict[str, Any]]:
    """Technical snapshot after each closed bar from WARMUP_BARS on (what the live bot sees)."""
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.model.objects import Price, Quantity
    from nautilus_trader.core.datetime import millis_to_nanos
    from indicators.technical_manager import TechnicalIndicatorManager

    bt = BarType.from_str("BTCUSDT-PERP.BINANCE-15-MINUTE-LAST-EXTERNAL")
    im = TechnicalIndicatorManager(sma_periods=[5, 20, 50], ema_periods=[12, 26], rsi_period=14,
                                   macd_fast=12, macd_slow=26, bb_period=20, bb_std=2.0, atr_period=14)
    snaps = []
    for i, k in enumerate(k15):
        bar = Bar(bt, Price.from_str(f"{float(k[1]):.1f}"), Price.from_str(f"{float(k[2]):.1f}"),
                  Price.from_str(f"{float(k[3]):.1f}"), Price.from_str(f"{float(k[4]):.1f}"),
                  Quantity.from_str(f"{float(k[5]):.3f}"), millis_to_nanos(int(k[6])), millis_to_nanos(int(k[6])))
        im.update(bar)
        if i < WARMUP_BARS - 1 or not im.is_initialized():
            continue
        price = float(k[4])
        tech = im.get_technical_data(price)
        prev_close = float(k15[i - 1][4])
        snaps.append({
            "i": i, "close_time": int(k[6]),
            "price_data": {"price": price, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(int(k[6]) / 1000)),
                           "high": float(k[2]), "low": float(k[3]), "volume": float(k[5]),
                           "price_change": (price / prev_close - 1) * 100, "kline_data": im.get_kline_data(10)},
            "technical_data": tech,
        })
    return snaps


# ------------------------------------------------------------------------- decide

def run_decide(days: int, workers: int, time_budget: float) -> None:
    import main_live
    from utils.llm_client import LLMAnalyzer

    k15, k4h, fng = load_or_fetch_data(days)
    snaps = build_snapshots(k15)
    done = set()
    if DECISIONS_FILE.exists():
        for line in DECISIONS_FILE.read_text().splitlines():
            try:
                done.add(json.loads(line)["close_time"])
            except Exception:
                pass
    todo = [s for s in snaps if s["close_time"] not in done]
    print(f"bars={len(k15)} snapshots={len(snaps)} done={len(done)} todo={len(todo)}")
    if not todo:
        print("DECIDE_COMPLETE")
        return

    cfg = main_live.resolve_llm_settings(main_live.load_yaml_config().get("strategy", {}))

    def make_analyzer():
        return LLMAnalyzer(api_key=cfg["api_key"], model=cfg["model"] or None, provider=cfg["provider"],
                           effort=cfg["effort"], timeout_sec=min(cfg["timeout_sec"], 60),
                           max_tokens=cfg["max_tokens"], workspace_id=cfg.get("workspace_id"), max_retries=1)

    analyzers = [make_analyzer() for _ in range(workers)]
    print(f"model={analyzers[0].model} provider={analyzers[0].provider} workers={workers} budget={time_budget}s")

    def decide(idx: int, snap: Dict[str, Any]) -> Dict[str, Any]:
        an = analyzers[idx % workers]
        an.signal_history.clear()  # independent decisions (no previous-signal context)
        sent = sentiment_at(fng, snap["close_time"])
        t0 = time.monotonic()
        sig = an.analyze(snap["price_data"], snap["technical_data"], sent, None)
        return {"close_time": snap["close_time"], "i": snap["i"], "price": snap["price_data"]["price"],
                "signal": sig["signal"], "confidence": sig["confidence"], "fallback": bool(sig.get("is_fallback")),
                "atr": snap["technical_data"].get("atr"), "rsi": snap["technical_data"].get("rsi"),
                "overall_trend": snap["technical_data"].get("overall_trend"),
                "regime": regime_at(k4h, snap["close_time"]), "elapsed": round(time.monotonic() - t0, 1),
                "reason": sig.get("reason", "")[:200]}

    start = time.monotonic()
    written = 0
    with ThreadPoolExecutor(max_workers=workers) as pool, DECISIONS_FILE.open("a") as out:
        futures = {}
        queue = list(enumerate(todo))
        while queue or futures:
            while queue and len(futures) < workers and time.monotonic() - start < time_budget:
                idx, snap = queue.pop(0)
                futures[pool.submit(decide, idx, snap)] = snap["close_time"]
            if not futures:
                break
            for fut in as_completed(list(futures), timeout=90):
                futures.pop(fut, None)
                try:
                    rec = fut.result()
                    out.write(json.dumps(rec) + "\n"); out.flush(); written += 1
                except Exception as e:  # noqa: BLE001
                    print("decision failed:", e)
                break
            if time.monotonic() - start >= time_budget and not futures:
                break
    remaining = len(todo) - written
    print(f"written={written} remaining={remaining} elapsed={time.monotonic() - start:.0f}s")
    print("DECIDE_COMPLETE" if remaining <= 0 else "DECIDE_PARTIAL")


# ----------------------------------------------------------------------- simulate

def run_simulate(equity0: float, min_conf: str = MIN_CONFIDENCE, regime_filter: bool = True,
                 out_json: Optional[Path] = None) -> Dict[str, Any]:
    k15 = json.loads(KLINES_FILE.read_text())
    decisions = {}
    for line in DECISIONS_FILE.read_text().splitlines():
        try:
            d = json.loads(line); decisions[d["close_time"]] = d
        except Exception:
            pass
    by_i = {d["i"]: d for d in decisions.values()}
    first_i = min(by_i) if by_i else None
    if first_i is None:
        raise SystemExit("no decisions yet - run 'decide' first")

    conf_rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    equity = equity0
    peak = equity
    max_dd = 0.0
    pos: Optional[Dict[str, Any]] = None
    trades: List[Dict[str, Any]] = []
    fees_total = 0.0
    consecutive_losses = 0
    paused_until = 0
    day = None
    day_start_equity = equity
    same_run = 0
    last_actionable = None
    counters = {"HOLD": 0, "BUY": 0, "SELL": 0, "fallback": 0, "blocked_regime": 0, "blocked_conf": 0,
                "blocked_churn": 0, "blocked_pause": 0, "skipped_notional": 0, "entries": 0, "reversal_closes": 0,
                "sl_exits": 0, "tp_exits": 0, "partial_tps": 0, "trailing_moves": 0, "no_decision": 0}

    def fee(notional: float) -> float:
        return notional * TAKER_FEE

    def close_position(px: float, qty: float, when: int, how: str) -> None:
        nonlocal equity, pos, fees_total, consecutive_losses, peak, max_dd
        px_exec = px * (1 - SLIPPAGE) if pos["side"] == "LONG" else px * (1 + SLIPPAGE)
        gross = (px_exec - pos["entry"]) * qty * (1 if pos["side"] == "LONG" else -1)
        f = fee(px_exec * qty)
        fees_total += f
        equity += gross - f
        pos["qty"] -= qty
        pos["realized"] += gross - f
        pos["exits"].append({"how": how, "px": round(px_exec, 1), "qty": qty, "pnl": round(gross - f, 2),
                             "t": time.strftime("%m-%d %H:%M", time.gmtime(when / 1000))})
        if pos["qty"] <= MIN_QTY / 2:
            net = pos["realized"]
            trades.append({**{k: pos[k] for k in ("side", "entry", "orig_qty", "opened", "confidence")},
                           "net": round(net, 2), "exits": pos["exits"], "bars": pos["bars"]})
            consecutive_losses = consecutive_losses + 1 if net < 0 else 0
            pos = None
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)

    for i in range(first_i, len(k15) - 1):
        bar = k15[i]
        o, h, l, c, close_time = float(bar[1]), float(bar[2]), float(bar[3]), float(bar[4]), int(bar[6])
        d = by_i.get(i)

        # ---- exits inside this bar for a position opened earlier
        if pos is not None and pos["opened_i"] < i:
            pos["bars"] += 1
            hit_sl = l <= pos["sl"] if pos["side"] == "LONG" else h >= pos["sl"]
            hit_tp = h >= pos["tp"] if pos["side"] == "LONG" else l <= pos["tp"]
            if hit_sl:
                counters["sl_exits"] += 1
                close_position(pos["sl"], pos["qty"], close_time, "SL")
            elif hit_tp:
                counters["tp_exits"] += 1
                close_position(pos["tp"], pos["qty"], close_time, "TP")
        if pos is not None and pos["opened_i"] < i:
            # cycle-time maintenance at bar close (partial TP, trailing)
            r_now = ((c - pos["entry"]) if pos["side"] == "LONG" else (pos["entry"] - c)) / pos["sl_dist"]
            if not pos["partial_done"] and r_now >= PARTIAL_R:
                q = int(pos["orig_qty"] * PARTIAL_PCT * 1000) / 1000
                if q >= MIN_QTY and q < pos["qty"]:
                    counters["partial_tps"] += 1
                    pos["partial_done"] = True
                    close_position(c, q, close_time, "PARTIAL")
            if pos is not None:
                atr = pos["atr"]
                if pos["side"] == "LONG":
                    pos["extreme"] = max(pos["extreme"], c)
                    if not pos["trail_on"] and c - pos["entry"] >= TRAIL_ACT_ATR * atr:
                        pos["trail_on"] = True
                    if pos["trail_on"]:
                        new_sl = pos["extreme"] - TRAIL_DIST_ATR * atr
                        if new_sl - pos["sl"] >= TRAIL_STEP_ATR * atr:
                            pos["sl"] = new_sl; counters["trailing_moves"] += 1
                else:
                    pos["extreme"] = min(pos["extreme"], c)
                    if not pos["trail_on"] and pos["entry"] - c >= TRAIL_ACT_ATR * atr:
                        pos["trail_on"] = True
                    if pos["trail_on"]:
                        new_sl = pos["extreme"] + TRAIL_DIST_ATR * atr
                        if pos["sl"] - new_sl >= TRAIL_STEP_ATR * atr:
                            pos["sl"] = new_sl; counters["trailing_moves"] += 1

        # ---- daily baseline / pauses
        bar_day = time.strftime("%Y-%m-%d", time.gmtime(close_time / 1000))
        if bar_day != day:
            day, day_start_equity = bar_day, equity
        if (equity - day_start_equity) / day_start_equity <= -DAILY_LOSS_LIMIT and close_time >= paused_until:
            paused_until = close_time + PAUSE_HOURS * 3600_000
        if consecutive_losses >= MAX_CONSEC_LOSSES and close_time >= paused_until:
            paused_until = close_time + PAUSE_HOURS * 3600_000
            consecutive_losses = 0

        # ---- decision at this bar close
        if d is None:
            counters["no_decision"] += 1
            continue
        sig, conf = d["signal"], d["confidence"]
        counters[sig] = counters.get(sig, 0) + 1
        if d.get("fallback"):
            counters["fallback"] += 1
        if sig == "HOLD":
            continue
        same_run = same_run + 1 if sig == last_actionable else 1
        last_actionable = sig
        if close_time < paused_until:
            counters["blocked_pause"] += 1; continue
        if conf_rank.get(conf, 1) < conf_rank[min_conf]:
            counters["blocked_conf"] += 1; continue
        if same_run > MAX_SAME_SIGNAL:
            counters["blocked_churn"] += 1; continue
        if regime_filter:
            reg = d.get("regime")
            if reg == "flat" or (reg == "up" and sig == "SELL") or (reg == "down" and sig == "BUY"):
                counters["blocked_regime"] += 1; continue

        want = "LONG" if sig == "BUY" else "SHORT"
        next_open = float(k15[i + 1][1])
        if pos is not None:
            if pos["side"] != want:
                counters["reversal_closes"] += 1
                close_position(next_open, pos["qty"], int(k15[i + 1][6]), "REVERSAL")
            continue  # same side: no pyramiding; opposite: close only (re-entry next cycle)

        # ---- sizing (live rules)
        atr = float(d.get("atr") or 0)
        price = next_open
        sl_dist_pct = max((SL_ATR * atr) / price if atr > 0 else 0.02, 0.002)
        trend_mult = TREND_MULT if d.get("overall_trend") in ("强势上涨", "强势下跌") else 1.0
        rsi = float(d.get("rsi") or 50)
        rsi_mult = RSI_MULT if (rsi > RSI_EXTREME[1] or rsi < RSI_EXTREME[0]) else 1.0
        risk_usdt = equity * RISK_PER_TRADE * CONF_MULT.get(conf, 1.0) * trend_mult * rsi_mult
        qty = risk_usdt / (sl_dist_pct * price)
        qty = min(qty, equity * MAX_POS_LEVERAGE / price)
        qty = int(qty * 1000) / 1000
        if qty < MIN_QTY or qty * price < MIN_NOTIONAL:
            counters["skipped_notional"] += 1; continue

        px_exec = price * (1 + SLIPPAGE) if want == "LONG" else price * (1 - SLIPPAGE)
        f = fee(px_exec * qty); fees_total += f; equity -= f
        sl = px_exec - SL_ATR * atr if want == "LONG" else px_exec + SL_ATR * atr
        tp = px_exec + TP_ATR * atr if want == "LONG" else px_exec - TP_ATR * atr
        pos = {"side": want, "entry": px_exec, "qty": qty, "orig_qty": qty, "sl": sl, "tp": tp,
               "sl_dist": abs(px_exec - sl), "atr": atr, "opened_i": i + 1, "bars": 0,
               "opened": time.strftime("%m-%d %H:%M", time.gmtime(int(k15[i + 1][0]) / 1000)),
               "confidence": conf, "extreme": px_exec, "trail_on": False, "partial_done": False,
               "realized": -f, "exits": []}
        counters["entries"] += 1

    # mark-to-market anything still open at the end
    open_pnl = 0.0
    if pos is not None:
        last = float(k15[-1][4])
        open_pnl = (last - pos["entry"]) * pos["qty"] * (1 if pos["side"] == "LONG" else -1)

    wins = [t for t in trades if t["net"] > 0]
    losses = [t for t in trades if t["net"] <= 0]
    span_days = (int(k15[-1][6]) - int(k15[first_i][6])) / 86_400_000
    result = {
        "period": f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime(int(k15[first_i][6]) / 1000))} -> "
                  f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime(int(k15[-1][6]) / 1000))} UTC ({span_days:.1f} days)",
        "decisions": len(by_i), "start_equity": equity0, "end_equity": round(equity, 2),
        "net_pnl": round(equity - equity0, 2), "net_pnl_pct": round((equity / equity0 - 1) * 100, 2),
        "open_position_mtm": round(open_pnl, 2), "fees": round(fees_total, 2), "max_drawdown_pct": round(max_dd * 100, 2),
        "trades": len(trades), "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else None,
        "avg_win": round(sum(t["net"] for t in wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(t["net"] for t in losses) / len(losses), 2) if losses else None,
        "profit_factor": round(sum(t["net"] for t in wins) / abs(sum(t["net"] for t in losses)), 2) if losses and wins and sum(t["net"] for t in losses) else None,
        "btc_buy_and_hold_pct": round((float(k15[-1][4]) / float(k15[first_i][4]) - 1) * 100, 2),
        "counters": counters, "trade_list": trades,
        "assumptions": {"taker_fee_per_side": TAKER_FEE, "slippage_per_exec": SLIPPAGE, "min_confidence": min_conf,
                        "regime_filter": regime_filter, "llm_sees_position": False},
    }
    if out_json:
        out_json.write_text(json.dumps(result, indent=1, ensure_ascii=False))
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["decide", "simulate"])
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--time-budget", type=float, default=150.0)
    ap.add_argument("--equity", type=float, default=500.0)
    ap.add_argument("--min-confidence", default=MIN_CONFIDENCE)
    ap.add_argument("--no-regime-filter", action="store_true")
    args = ap.parse_args()
    if args.phase == "decide":
        run_decide(args.days, args.workers, args.time_budget)
        return 0
    res = run_simulate(args.equity, args.min_confidence, not args.no_regime_filter,
                       REPLAY_DIR / f"result_{int(args.equity)}.json")
    tl = res.pop("trade_list")
    print(json.dumps(res, indent=1, ensure_ascii=False))
    print("\nTRADES:")
    for t in tl:
        exits = ", ".join(f"{e['how']}@{e['px']}({e['pnl']:+.2f})" for e in t["exits"])
        print(f" {t['opened']} {t['side']:5s} {t['confidence']:6s} {t['orig_qty']:.3f} @ {t['entry']:.1f} "
              f"-> {exits} | net {t['net']:+.2f} | {t['bars']} bars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
