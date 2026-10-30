#!/usr/bin/env python3
"""
Container liveness check: exit 0 if the strategy's heartbeat file is fresh.

The strategy touches HEARTBEAT_FILE (default logs/heartbeat) on start, on every
bar and on every analysis cycle. With 15-minute bars a healthy process refreshes
it at least every 15 minutes; HEALTH_MAX_AGE_SEC (default 2400 = 40 min) leaves
room for a quiet market plus one skipped cycle. A stale heartbeat usually means
a dead websocket or a hung event loop - exactly the cases worth a restart.
"""
import os
import sys
import time

path = (os.getenv("HEARTBEAT_FILE") or "logs/heartbeat").split("#")[0].strip()
max_age = float((os.getenv("HEALTH_MAX_AGE_SEC") or "2400").split("#")[0].strip())

try:
    age = time.time() - os.path.getmtime(path)
except FileNotFoundError:
    print(f"heartbeat {path} missing")
    sys.exit(1)

if age > max_age:
    print(f"heartbeat stale: {age:.0f}s > {max_age:.0f}s")
    sys.exit(1)
print(f"ok ({age:.0f}s)")
sys.exit(0)
