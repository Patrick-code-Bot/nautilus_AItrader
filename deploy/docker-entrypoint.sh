#!/bin/sh
# Container entrypoint.
#   trade      (default) run the live preflight, then the trading node
#   preflight  run only tools/preflight_live.py
#   score      tools/score_signals.py on the mounted logs
#   shell      interactive shell
#   anything else is executed as-is
set -eu
cd /app
mode="${1:-trade}"
[ $# -gt 0 ] && shift

case "$mode" in
  trade)
    if [ "${SKIP_PREFLIGHT:-false}" != "true" ]; then
      echo "[entrypoint] running live preflight..."
      if ! python tools/preflight_live.py; then
        echo "[entrypoint] PREFLIGHT FAILED - not starting the trading node. Fix the environment variables and redeploy."
        echo "[entrypoint] (set SKIP_PREFLIGHT=true only for paper venues when you accept the warnings)"
        sleep 120   # throttle restart loops so the failure stays readable in the logs
        exit 1
      fi
    fi
    echo "[entrypoint] starting trading node (BINANCE_ENV=${BINANCE_ENV:-live})"
    exec python main_live.py "$@"
    ;;
  preflight) exec python tools/preflight_live.py "$@" ;;
  score)     exec python tools/score_signals.py "$@" ;;
  shell)     exec /bin/sh ;;
  *)         exec "$mode" "$@" ;;
esac
