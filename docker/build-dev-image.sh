#!/bin/sh
# Build the KiroCrew dev base image ON THIS HOST (native arch — this is the
# arm64 build box; never QEMU-cross per the intranet build discipline).
#
#   docker/build-dev-image.sh [tag]        # tag default: kirocrew-dev:arm64
#
# Stages the host's kiro-cli into docker/.dev-build/ so the COPY in
# dev.Dockerfile resolves inside a context that is just docker/ (the
# repo-root .dockerignore allowlists only the wheel + entrypoint.sh), builds
# against the Harbor bases + intranet sources dev.Dockerfile pins, and
# removes the staging dir again. Requires docker buildx/BuildKit (default
# since Docker 23) for COPY --chmod.
set -eu

TAG="${1:-kirocrew-dev:arm64}"
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
KIRO_CLI="${KIRO_CLI_SRC:-$HOME/.local/bin/kiro-cli}"

if [ ! -x "$KIRO_CLI" ]; then
    echo "[build-dev] no kiro-cli at $KIRO_CLI — set KIRO_CLI_SRC to an" \
         "aarch64 build of it, or install one to ~/.local/bin/kiro-cli." >&2
    exit 1
fi
# The build box is native arm64; the staged binary must match it (a gnu/x86
# kiro-cli would only fail later, at first agent session).
if ! file -b "$KIRO_CLI" | grep -q aarch64; then
    echo "[build-dev] $KIRO_CLI is not an aarch64 binary; refusing to bake it" \
         "into an arm64 image." >&2
    exit 1
fi

mkdir -p "$HERE/.dev-build"
cp "$KIRO_CLI" "$HERE/.dev-build/kiro-cli"
# cleanup even on build failure
trap 'rm -rf "$HERE/.dev-build"' EXIT

docker build -f "$HERE/dev.Dockerfile" -t "$TAG" "$HERE"
echo "[build-dev] built $TAG"
