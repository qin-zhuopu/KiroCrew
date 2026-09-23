# KiroCrew DEV base image — runtime only, no baked code.
#
# Unlike docker/Dockerfile (which consumes the CI-built wheel), this image
# carries NO kiro_crew code and NO wheel: the source tree is bind-mounted at
# /workspace at runtime and installed editable into a venv on the named
# volume (docker/dev-bootstrap.sh). Change source on the host -> re-run
# docker exec <ctr> /workspace/docker/dev-run.sh -> the gateway restarts
# against your edits. Image and container stay untouched across iterations.
#
# Build (context is docker/ ON PURPOSE — the repo-root .dockerignore
# allowlists only the wheel + entrypoint.sh, so the kiro-cli binary staged by
# the build script must come from a context that includes it):
#   docker/build-dev-image.sh            (stages kiro-cli, builds, cleans up)
# or manually:
#   mkdir -p docker/.dev-build && cp ~/.local/bin/kiro-cli docker/.dev-build/
#   docker build -f docker/dev.Dockerfile -t kirocrew-dev:arm64 docker/
#
# Image-source discipline (intranet build, hard rules):
#   - FROM is always harbor.jereh.cn/base/... (both bases verified arm64
#     native on this host; no QEMU cross-build).
#   - apt: the base's deb.debian.org is swapped for mirrors.aliyun.com/debian
#     (Nexus has no Debian proxy — only an ubuntu one — and aliyun is a
#     domestic source reached DIRECT; never put intranet/domestic traffic on
#     the proxy).
#   - pip: PIP_INDEX_URL points at Nexus pypi-public; editable installs
#     happen inside dev-bootstrap.sh, not here.
#   - kiro-cli: COPYed from the host's aarch64 binary (~/.local/bin/kiro-cli),
#     which avoids any external download entirely.

# node 24, arm64 native from Harbor — the copy source for the node runtime.
# The node image's npm/npx are symlinks into /usr/local/lib/node_modules/npm,
# so that tree must come along to keep the relative links valid.
FROM harbor.jereh.cn/base/node:24-arm64 AS nodebin

FROM harbor.jereh.cn/base/python:3.12-slim-trixie-arm64

# Runtime toolset for agent sessions + the dev scripts:
#   git/ripgrep/curl/tini  — same agent runtime needs as the prod image;
#   procps                 — pkill, used by dev-run.sh to restart the gateway;
#   unzip + ca-certificates— base tooling (cert pinning for Nexus/aliyun).
# deb822 sources ship in trixie; rewrite the URI lines, keep suites/sections.
RUN set -eux; \
    sed -i -E \
      -e 's#^URIs: https?://deb\.debian\.org/debian$#URIs: https://mirrors.aliyun.com/debian#' \
      -e 's#^URIs: https?://(deb|security)\.debian\.org/debian-security$#URIs: https://mirrors.aliyun.com/debian-security#' \
      -e 's#^URIs: https?://security\.debian\.org/debian-security/?$#URIs: https://mirrors.aliyun.com/debian-security#' \
      /etc/apt/sources.list.d/debian.sources; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        procps \
        ripgrep \
        tini \
        unzip \
    ; rm -rf /var/lib/apt/lists/*

COPY --from=nodebin /usr/local/bin/node /usr/local/bin/node
COPY --from=nodebin /usr/local/bin/npm /usr/local/bin/npm
COPY --from=nodebin /usr/local/bin/npx /usr/local/bin/npx
COPY --from=nodebin /usr/local/lib/node_modules /usr/local/lib/node_modules

# kiro-cli — staged by docker/build-dev-image.sh from the host's aarch64
# build (same ELF class the prod image downloads).
COPY --chmod=755 .dev-build/kiro-cli /usr/local/bin/kiro-cli

# Non-root dev user, uid 1000 = the host user's uid on this machine, so the
# bind-mounted source tree is readable without chown games.
RUN useradd --create-home --uid 1000 --shell /bin/bash kirocrew \
    && mkdir -p /workspace \
    && chown kirocrew:kirocrew /workspace

# The venv lands on the /home/kirocrew named volume at first bootstrap;
# putting it on PATH up front means a plain `docker exec <ctr> kirocrew ...`
# uses the editable install as soon as it exists. PIP_INDEX_URL makes every
# pip call in the container intranet-sourced by construction.
ENV VIRTUAL_ENV=/home/kirocrew/venv \
    PATH=/home/kirocrew/venv/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
    PIP_INDEX_URL=https://nexus.jereh.cn/repository/pypi-public/simple \
    KIROCREW_BIND=0.0.0.0

USER kirocrew
WORKDIR /workspace

# Dev posture: the container is a sleep-forever host, NOT a service unit —
# services are started per-iteration via docker exec (see dev-run.sh). tini
# stays PID 1 to reap the trees those execs leave behind.
ENTRYPOINT ["tini", "--"]
CMD ["sleep", "infinity"]
