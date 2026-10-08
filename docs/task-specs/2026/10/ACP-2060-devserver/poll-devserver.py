"""Poll the demo project's dev-server state until it settles.

Prints one line per poll so the report shows the actual progression
(installing deps -> starting -> running), not just the end state.

Usage: python3 poll-devserver.sh.py [timeout_seconds]
"""

import json
import subprocess
import sys
import time

ROOT = "/home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-kc-v1"
PROBE = f"{ROOT}/docs/task-specs/2026/10/ACP-2060-devserver/probe-devserver.sh"
TIMEOUT = float(sys.argv[1]) if len(sys.argv) > 1 else 900.0
INTERVAL = 5.0

deadline = time.monotonic() + TIMEOUT
last = None
while time.monotonic() < deadline:
    out = subprocess.run(["bash", PROBE, "get"], capture_output=True, text=True).stdout
    try:
        data = json.loads(out)
    except ValueError:
        print(f"[non-json] {out.strip()}", flush=True)
        time.sleep(INTERVAL)
        continue
    brief = {k: data.get(k) for k in ("state", "url", "ports", "failedStep", "startedAt")}
    if brief != last:
        print(time.strftime("%H:%M:%S"), json.dumps(brief, ensure_ascii=False), flush=True)
        last = brief
    if data.get("state") in ("running", "failed", "stopped"):
        print("FINAL:", json.dumps(data, ensure_ascii=False), flush=True)
        if data.get("message"):
            print("MESSAGE:", data["message"], flush=True)
        sys.exit(0 if data.get("state") == "running" else 1)
    time.sleep(INTERVAL)
print("TIMEOUT waiting for the dev server to settle", flush=True)
sys.exit(2)
