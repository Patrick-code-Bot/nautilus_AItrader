#!/bin/bash
# Stop the AI trading strategy gracefully (SIGINT -> Nautilus shutdown; protective
# exchange-side orders are kept when a position is open).
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

if [ ! -f trader.pid ]; then
    echo "❌ No PID file found. Is the trader running?"; exit 1
fi
PID=$(cat trader.pid)
if ps -p "$PID" >/dev/null 2>&1; then
    echo "🛑 Stopping trading strategy (PID $PID)..."
    kill -INT "$PID"
    for _ in $(seq 1 20); do ps -p "$PID" >/dev/null 2>&1 || break; sleep 1; done
    if ps -p "$PID" >/dev/null 2>&1; then
        echo "⚠️  Still running after 20s, sending SIGTERM..."; kill "$PID"; sleep 3
        ps -p "$PID" >/dev/null 2>&1 && { echo "⚠️  Forcing termination..."; kill -9 "$PID"; }
    fi
    echo "✅ Trading strategy stopped"
else
    echo "⚠️  Process not running (PID $PID)"
fi
rm -f trader.pid
