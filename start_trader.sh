#!/bin/bash
# Start the AI trading strategy in the background (works on macOS and Linux).
#
# Usage:  ./start_trader.sh            # uses .env in the repo root
#         ./start_trader.sh --setup    # also create .venv (Python 3.12 via uv) and install requirements
#
# The process is detached with nohup; PID is stored in trader.pid; logs go to logs/trader_<timestamp>.log
# plus the structured NautilusTrader JSONL log under logs/.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

if [ ! -f .env ]; then
    echo "❌ .env not found in $REPO_DIR (copy .env.template to .env and fill in the keys)"; exit 1
fi

# --- locate / create the Python environment -------------------------------
pick_python() {
    for candidate in "$REPO_DIR/.venv/bin/python" "$REPO_DIR/venv/bin/python" "$HOME/deepseek_venv/bin/python"; do
        if [ -x "$candidate" ] && "$candidate" -c "import nautilus_trader" >/dev/null 2>&1; then
            echo "$candidate"; return 0
        fi
    done
    return 1
}

if [ "${1:-}" = "--setup" ] || ! PYTHON="$(pick_python)"; then
    echo "🔧 Setting up .venv (Python 3.12 + requirements)..."
    if command -v uv >/dev/null 2>&1; then
        uv python install 3.12 >/dev/null
        uv venv --python 3.12 "$REPO_DIR/.venv" >/dev/null
        UV_CONCURRENT_DOWNLOADS=2 uv pip install --python "$REPO_DIR/.venv/bin/python" -r requirements.txt
    else
        PY312="$(command -v python3.12 || command -v python3 || true)"
        [ -n "$PY312" ] || { echo "❌ Need Python 3.12 (brew install python@3.12 or install uv)"; exit 1; }
        "$PY312" -m venv "$REPO_DIR/.venv"
        "$REPO_DIR/.venv/bin/pip" install -q -r requirements.txt
    fi
    PYTHON="$REPO_DIR/.venv/bin/python"
fi
echo "🐍 Using $PYTHON ($("$PYTHON" --version 2>&1))"

# --- already running? -------------------------------------------------------
if [ -f trader.pid ] && ps -p "$(cat trader.pid)" >/dev/null 2>&1; then
    echo "⚠️  Trader already running with PID $(cat trader.pid) - use ./restart_trader.sh"; exit 1
fi

mkdir -p logs
export AUTO_CONFIRM=true   # non-interactive; the venue is selected by BINANCE_ENV in .env

LOG_FILE="logs/trader_$(date +%Y%m%d_%H%M%S).log"
nohup "$PYTHON" main_live.py > "$LOG_FILE" 2>&1 &
echo $! > trader.pid

sleep 2
if ps -p "$(cat trader.pid)" >/dev/null 2>&1; then
    echo "✅ Trading strategy started (PID $(cat trader.pid))"
    echo "📋 Console log : tail -f $REPO_DIR/$LOG_FILE"
    echo "📋 Signal log  : tail -f $REPO_DIR/logs/signal_log.jsonl"
    echo "🛑 Stop        : $REPO_DIR/stop_trader.sh"
    grep -E "BINANCE_ENV|TEST_MODE|LLM provider" "$LOG_FILE" 2>/dev/null | head -5 || true
else
    echo "❌ Process exited immediately - last log lines:"; tail -20 "$LOG_FILE"; rm -f trader.pid; exit 1
fi
