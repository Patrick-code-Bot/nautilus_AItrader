#!/bin/bash
# Restart the AI trading strategy. An open position is re-adopted on start
# (exchange-side exits are verified / re-armed automatically).
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"
echo "🔄 Restarting trading strategy..."
[ -f trader.pid ] && ./stop_trader.sh || true
sleep 2
exec ./start_trader.sh "$@"
