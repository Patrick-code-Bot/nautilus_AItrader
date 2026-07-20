#!/usr/bin/env python3
"""
Score DeepSeek signal quality against realized price paths.

Reads the JSONL signal dataset written by the strategy (logs/signal_log.jsonl)
and simulates each BUY/SELL signal's bracket outcome (first hit of SL or TP
wins; conservative same-bar rule: SL wins ties) using klines fetched from
Binance's public API. No credentials required.

Usage:
    python tools/score_signals.py [--file logs/signal_log.jsonl]
                                  [--symbol BTCUSDT] [--interval 15m]
                                  [--max-bars 96]

Interpretation:
    avgR > 0 with n >= 30 (ideally 100+) suggests the signal has edge.
    Compare HIGH vs MEDIUM vs LOW to check confidence calibration, and
    regime-aligned vs counter-regime to validate the regime filter.
"""

import argparse
import json
import sys
import time
from datetime import datetime

import requests

BINANCE_KLINES = "https://fapi.binance.com/fapi/v1/klines"


def parse_ts(ts: str) -> int:
    """ISO-8601 timestamp -> epoch milliseconds."""
    return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> list:
    """Fetch klines in [start_ms, end_ms] from Binance public API (paginated)."""
    klines = {}
    cursor = start_ms
    while cursor < end_ms:
        resp = requests.get(
            BINANCE_KLINES,
            params={
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            },
            timeout=15,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        for k in batch:
            klines[k[0]] = k
        cursor = batch[-1][0] + 1
        if len(batch) < 1000:
            break
        time.sleep(0.2)  # stay clear of rate limits
    return [klines[t] for t in sorted(klines)]


def outcome(record: dict, klines: list, max_bars: int):
    """
    Simulate one signal's bracket outcome.

    Returns (result, r_multiple) where result is 'win', 'loss', 'timeout',
    or 'pending' (not enough forward data yet). None if unusable.
    """
    entry = record["price"]
    sl = record["sl_price"]
    tp = record["tp_price"]
    is_long = record["signal"] == "BUY"
    sl_dist = abs(entry - sl)
    if sl_dist <= 0:
        return None

    ts = parse_ts(record["ts"])
    forward = [k for k in klines if k[0] >= ts][:max_bars]
    if not forward:
        return ("pending", 0.0)

    for k in forward:
        high = float(k[2])
        low = float(k[3])
        if is_long:
            hit_sl = low <= sl
            hit_tp = high >= tp
        else:
            hit_sl = high >= sl
            hit_tp = low <= tp
        if hit_sl:
            return ("loss", -1.0)  # SL-first on ties (conservative)
        if hit_tp:
            return ("win", abs(tp - entry) / sl_dist)

    if len(forward) < max_bars:
        return ("pending", 0.0)  # window not complete yet

    # Timeout: mark-to-market in R
    exit_price = float(forward[-1][4])
    r = (exit_price - entry) / sl_dist if is_long else (entry - exit_price) / sl_dist
    return ("timeout", r)


def stats(results: list):
    """Aggregate (result, r) tuples into summary metrics."""
    n = len(results)
    if n == 0:
        return None
    wins = [r for res, r in results if res == "win"]
    losses = [r for res, r in results if res == "loss"]
    timeouts = [r for res, r in results if res == "timeout"]
    total_r = sum(r for _, r in results)
    gross_win = sum(r for r in wins) + sum(r for r in timeouts if r > 0)
    gross_loss = abs(sum(losses)) + abs(sum(r for r in timeouts if r < 0))
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "timeouts": len(timeouts),
        "win_rate": len(wins) / n,
        "avg_r": total_r / n,
        "pf": (gross_win / gross_loss) if gross_loss > 0 else float("inf"),
    }


def fmt(name: str, s) -> str:
    if not s:
        return f"  {name:<26} n=0"
    return (
        f"  {name:<26} n={s['n']:<5} win {s['win_rate']:6.1%}  "
        f"avgR {s['avg_r']:+.3f}  PF {s['pf']:.2f}  "
        f"(W/L/T {s['wins']}/{s['losses']}/{s['timeouts']})"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Score DeepSeek signal quality")
    ap.add_argument("--file", default="logs/signal_log.jsonl")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--interval", default="15m")
    ap.add_argument(
        "--max-bars", type=int, default=96,
        help="max forward bars per signal (96 = 24h at 15m)",
    )
    args = ap.parse_args()

    records = []
    with open(args.file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                r.get("signal") in ("BUY", "SELL")
                and r.get("sl_price")
                and r.get("tp_price")
            ):
                records.append(r)

    if not records:
        print(
            "No BUY/SELL signal records found. "
            "Run the bot with SIGNAL_ONLY_MODE=true to build the dataset first."
        )
        return 1

    start = min(parse_ts(r["ts"]) for r in records)
    end = min(
        int(time.time() * 1000),
        max(parse_ts(r["ts"]) for r in records) + (args.max_bars + 1) * 900_000,
    )
    print(f"Fetching {args.interval} klines for {args.symbol} ({len(records)} signals)...")
    klines = fetch_klines(args.symbol, args.interval, start, end)
    print(f"Got {len(klines)} klines.\n")

    scored, pending = [], 0
    for r in records:
        res = outcome(r, klines, args.max_bars)
        if res is None:
            continue
        if res[0] == "pending":
            pending += 1
            continue
        scored.append((r, res))

    def aligned(r):
        return (r["signal"] == "BUY" and r.get("regime") == "up") or (
            r["signal"] == "SELL" and r.get("regime") == "down"
        )

    def counter(r):
        return (r["signal"] == "BUY" and r.get("regime") == "down") or (
            r["signal"] == "SELL" and r.get("regime") == "up"
        )

    print(fmt("ALL SIGNALS", stats([res for _, res in scored])))
    print(fmt("regime-aligned", stats([res for r, res in scored if aligned(r)])))
    print(fmt("counter-regime", stats([res for r, res in scored if counter(r)])))
    print(fmt("flat regime", stats([res for r, res in scored if r.get("regime") == "flat"])))
    print()
    for conf in ("HIGH", "MEDIUM", "LOW"):
        print(fmt(f"confidence {conf}", stats([res for r, res in scored if r.get("confidence") == conf])))
    print()
    for sig in ("BUY", "SELL"):
        print(fmt(f"side {sig}", stats([res for r, res in scored if r["signal"] == sig])))
    if pending:
        print(f"\n  ({pending} recent signals still pending - window not complete)")

    # Verdict
    s = stats([res for _, res in scored])
    high = stats([res for r, res in scored if r.get("confidence") == "HIGH"])
    print()
    if not s or s["n"] < 30:
        n = s["n"] if s else 0
        print(f"⚠️  Only {n} scored signals - keep collecting (aim for 100+) before judging.")
    elif s["avg_r"] > 0 and high and high["n"] >= 10 and high["avg_r"] > s["avg_r"]:
        print("✅ Signal shows edge AND confidence is calibrated (HIGH > overall).")
        print("   The LLM signal layer is worth keeping.")
    elif s["avg_r"] > 0:
        print("🟡 Edge is positive but confidence is NOT clearly calibrated.")
        print("   Consider treating all signals equally (flatten confidence sizing).")
    else:
        print("❌ No measurable edge in the signal (avgR <= 0).")
        print("   Recommend a deterministic, backtestable core with the LLM demoted")
        print("   to veto/filter duty - or shutting the strategy down.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
