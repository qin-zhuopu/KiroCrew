#!/bin/sh
# (Re)start the dev gateway inside a running dev container — the whole dev
# loop is this one exec (docker/dev.Dockerfile):
#
#   docker exec <ctr> /workspace/docker/dev-run.sh
#
# Kill-old + start-new: any gateway from a previous run is stopped, then the
# production entrypoint (/workspace/docker/entrypoint.sh, mounted with the
# source) is launched DETACHED — setsid + full redirection — so closing the
# `docker exec` client does not take the service down with it. Detaching via
# the entrypoint rather than a bare CLI call keeps the dev instance on the
# SAME posture code as the prod image: credential env->file sync + scrub,
# and the probe-based sandbox seeding on first run (see docker/AGENTS notes
# in entrypoint.sh). tini (container PID 1) reaps the trees left behind.
#
# After source edits no reinstall is needed (editable install); re-running
# this script is the restart. Log: $KIROCREW_DEV_LOG (default
# /home/kirocrew/gateway.log) — tail it from the host with
# `docker exec <ctr> tail -n 50 <log>`.
set -eu

VENV="${KIROCREW_DEV_VENV:-/home/kirocrew/venv}"
LOG="${KIROCREW_DEV_LOG:-/home/kirocrew/gateway.log}"
# Same source root dev-bootstrap.sh was pointed at (the editable install
# resolves from it); a read-only bind-mount of upstream uses the home-volume
# copy instead — see KIROCREW_DEV_SRC in dev-bootstrap.sh.
SRC="${KIROCREW_DEV_SRC:-/workspace}"
ENTRYPOINT_SH="$SRC/docker/entrypoint.sh"

if [ ! -x "$VENV/bin/kirocrew" ]; then
    echo "[dev-run] no editable install at $VENV — run" \
         "/workspace/docker/dev-bootstrap.sh first." >&2
    exit 1
fi
if [ ! -r "$ENTRYPOINT_SH" ]; then
    echo "[dev-run] $ENTRYPOINT_SH not readable — is the source tree" \
         "mounted at /workspace?" >&2
    exit 1
fi

# Only the gateway; agent-launched shells must not be collateral.
pkill -f 'kirocrew gateway' 2>/dev/null || true
# Give the old process time to release port 5476 before the new bind.
i=0
while pgrep -f 'kirocrew gateway' >/dev/null 2>&1 && [ "$i" -lt 20 ]; do
    sleep 0.5
    i=$((i + 1))
done

# KIROCREW_PORT flows through entrypoint.sh's health banner and the gateway;
# the container default 5476 matches VIRTUAL_PORT on every dev container.
export KIROCREW_PORT="${KIROCREW_PORT:-5476}"

cd /home/kirocrew
setsid sh -c "exec sh $ENTRYPOINT_SH gateway" </dev/null >>"$LOG" 2>&1 &
echo "[dev-run] gateway starting on port $KIROCREW_PORT; log: $LOG"
