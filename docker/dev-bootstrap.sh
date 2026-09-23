#!/bin/sh
# One-time dev bootstrap — run INSIDE a dev container that has the source
# tree bind-mounted at /workspace (docker/dev.Dockerfile):
#
#   docker exec <ctr> /workspace/docker/dev-bootstrap.sh
#
# Creates the venv on the /home/kirocrew named volume and installs the
# mounted tree editable, so dependencies are resolved once and later source
# edits take effect without any reinstall (restart = dev-run.sh). Safe to
# re-run: the venv is reused; pip re-resolves the editable install (needed
# when pyproject dependencies change, harmless otherwise).
#
# All pip traffic goes to the Nexus pypi group via PIP_INDEX_URL baked into
# the image — never to an external index, never through a proxy.
set -eu

VENV="${KIROCREW_DEV_VENV:-/home/kirocrew/venv}"
# The editable install targets $SRC (default: the /workspace bind-mount).
# A read-only mount (the upstream reference container) needs a writable copy
# first — `pip install -e` always writes *.egg-info into the project root —
# and then points this at the copy: -e KIROCREW_DEV_SRC=/home/kirocrew/src.
SRC="${KIROCREW_DEV_SRC:-/workspace}"

if [ ! -d "$SRC/src/kiro_crew" ]; then
    echo "[dev-bootstrap] $SRC has no KiroCrew source tree — is the" \
         "bind-mount missing or pointed at the wrong checkout?" >&2
    exit 1
fi

if [ ! -x "$VENV/bin/python" ]; then
    echo "[dev-bootstrap] creating venv at $VENV"
    python3 -m venv "$VENV"
fi

echo "[dev-bootstrap] pip install -e $SRC (editable)"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -e "$SRC"

# The editable console script, not `--version`'s pre-import fast path, is
# what proves the mounted tree actually resolves.
"$VENV/bin/python" -c 'import kiro_crew.cli'
echo "[dev-bootstrap] done — start the gateway with $SRC/docker/dev-run.sh"
