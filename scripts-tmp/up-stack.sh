#!/bin/bash
# ACP-754 real-machine harness: an isolated worktree stack for the demo's
# doc assertions. Own KIROCREW_HOME, own ports (6788 gateway / 3050 vite),
# nothing touches ~/.kiro or the main checkout's 6777/3000. Kept out of the
# tracked tree's normal scripts — this is a harness, not product code.
set -e
ROOT=/home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-ai-studio-reqloop
export KIROCREW_HOME=/tmp/acp754-home
export KIROCREW_PORT=6788
export KIROCREW_ALLOWED_LOOPBACK_PORTS=3000,3050
export PYTHONPATH="$ROOT/src"
RUNTIME_PYTHON=/home/jereh/repo/github.com/kirodotdev/KiroCrew/.venv/bin/python
mkdir -p "$KIROCREW_HOME/logs"

echo "[stack] booting gateway :6788"
"$RUNTIME_PYTHON" -m kiro_crew gateway --no-open --port 6788 --approval reads \
  > "$KIROCREW_HOME/logs/gateway.log" 2>&1 &
GW=$!
for i in $(seq 1 90); do
  curl -fsS -o /dev/null --max-time 2 http://127.0.0.1:6788/ 2>/dev/null && break
  [ "$i" -eq 90 ] && { echo "[stack] gateway timeout"; cat "$KIROCREW_HOME/logs/gateway.log"; exit 1; }
  sleep 1
done
echo "[stack] gateway up"

echo "[stack] booting vite :3050"
( cd "$ROOT/website" && KIROCREW_PORT=6788 exec npm run dev -- --port 3050 --strictPort \
  > "$KIROCREW_HOME/logs/vite.log" 2>&1 ) &
VT=$!
for i in $(seq 1 40); do
  curl -fsS -o /dev/null --max-time 2 http://127.0.0.1:3050/ 2>/dev/null && break
  [ "$i" -eq 40 ] && { echo "[stack] vite timeout"; cat "$KIROCREW_HOME/logs/vite.log"; exit 1; }
  sleep 1
done
echo "[stack] vite up"

# Mint a token against THIS home+port, rewrite the port to vite's.
TOKEN_URL="$(PYTHONPATH="$ROOT/src" "$RUNTIME_PYTHON" -m kiro_crew token --port 6788 2>/dev/null \
  | grep -oE 'http://localhost:[0-9]+[^ ]*' | head -1)"
OPEN_URL="$(printf '%s' "$TOKEN_URL" | sed 's/:6788/:3050/')"
echo "[stack] token url: $OPEN_URL"
echo "$OPEN_URL" > "$KIROCREW_HOME/token-url.txt"

# ai-studio installs DISABLED on a fresh home — every API call answers 403
# app_disabled until explicitly enabled (found the hard way, ACP-754). The
# enable goes through the running gateway; give the config applier a beat.
KIROCREW_HOME="$KIROCREW_HOME" "$RUNTIME_PYTHON" -m kiro_crew app enable ai-studio 2>&1 | sed 's/^/[stack] /'
sleep 3
echo "[stack] PIDS gateway=$GW vite=$VT  (running; log tail below)"
wait
