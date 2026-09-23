# Dev-in-container environment (bind-mounted source)

A **development** container shape for KiroCrew, distinct from the production
image in `docker/Dockerfile` (which bakes the CI-built wheel). Here the image
carries only the runtime; the source tree is bind-mounted at `/workspace` and
installed editable. Iterating on code means **edit the mounted tree on the
host, re-run one `docker exec`** — the image and the long-lived container
never change.

Two instances run side by side on this build host:

| Instance | Source (host) | Container | Volume (home) | Domain |
|---|---|---|---|---|
| Current trunk | this worktree (`/home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-docker-dev`) | `kirocrew-src-main` | `kirocrew-dev-home-main` | `https://kiro-ddev.gb10.zhuopu.net` |
| Original upstream | `/home/jereh/workplace/kirocrew-upstream` (mounted **read-only**) | `kirocrew-src-orig` | `kirocrew-dev-home-orig` | `https://kiro-dorig.gb10.zhuopu.net` |

Both containers sit on the `webproxy` network and are published by
`nginx-proxy` through `VIRTUAL_HOST` — **no host ports are exposed**. Inside
each container the gateway listens on 5476.

## Build the dev image

Native arch only (this host is arm64; never QEMU-cross — see the intranet
build rules). All inputs are intranet: Harbor bases, aliyun apt (domestic,
direct — no proxy), Nexus pypi for pip.

```bash
docker/build-dev-image.sh                 # -> kirocrew-dev:arm64
```

The script stages the host's `~/.local/bin/kiro-cli` (aarch64) into
`docker/.dev-build/` so `docker/dev.Dockerfile` can COPY it — the build
context is the `docker/` subtree because the repo-root `.dockerignore`
allowlists only the wheel and `entrypoint.sh`.

## Create the containers

Trunk instance (`/workspace` = live checkout; your edits are served):

```bash
docker volume create kirocrew-dev-home-main
docker run -d --name kirocrew-src-main \
  --network webproxy \
  --security-opt seccomp="$PWD/docker/seccomp/kirocrew-seccomp.json" \
  -v kirocrew-dev-home-main:/home/kirocrew \
  -v /home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-docker-dev:/workspace \
  -e VIRTUAL_HOST=kiro-ddev.gb10.zhuopu.net -e VIRTUAL_PORT=5476 \
  -e KIROCREW_CORS_ORIGINS=https://kiro-ddev.gb10.zhuopu.net \
  -e KIROCREW_BIND=0.0.0.0 -e KIROCREW_PORT=5476 \
  -e KIROCREW_HOME=/home/kirocrew/.kirocrew-docker \
  -e KIROCREW_ALLOW_UNSANDBOXED=1 \
  kirocrew-dev:arm64
```

Upstream reference instance (source mounted `:ro` — nothing is ever written
into `kirocrew-upstream`). Because `pip install -e` always writes
`*.egg-info` into the project root, an editable install cannot target a
read-only tree; the trick is a one-time snapshot **inside the home volume**
(`KIROCREW_DEV_SRC`), and the harness scripts are copied into that snapshot
since upstream doesn't contain them:

```bash
docker volume create kirocrew-dev-home-orig
docker run -d --name kirocrew-src-orig \
  --network webproxy \
  --security-opt seccomp="$PWD/docker/seccomp/kirocrew-seccomp.json" \
  -v kirocrew-dev-home-orig:/home/kirocrew \
  -v /home/jereh/workplace/kirocrew-upstream:/workspace:ro \
  -e VIRTUAL_HOST=kiro-dorig.gb10.zhuopu.net -e VIRTUAL_PORT=5476 \
  -e KIROCREW_CORS_ORIGINS=https://kiro-dorig.gb10.zhuopu.net \
  -e KIROCREW_BIND=0.0.0.0 -e KIROCREW_PORT=5476 \
  -e KIROCREW_HOME=/home/kirocrew/.kirocrew-docker \
  -e KIROCREW_ALLOW_UNSANDBOXED=1 \
  kirocrew-dev:arm64
# one-time snapshot (skip .git and website/; upstream dist is prebuilt in src/)
docker exec kirocrew-src-orig sh -c \
  'mkdir -p /home/kirocrew/upstream-src && tar -C /workspace --exclude=./.git --exclude=./website -cf - . | tar -C /home/kirocrew/upstream-src -xf -'
docker cp docker/dev-bootstrap.sh kirocrew-src-orig:/home/kirocrew/upstream-src/docker/dev-bootstrap.sh
docker cp docker/dev-run.sh       kirocrew-src-orig:/home/kirocrew/upstream-src/docker/dev-run.sh
```

To re-snapshot upstream after a `git pull` there, re-run the tar, re-copy
the two scripts, and re-run bootstrap + dev-run (below).

## Bootstrap once, (re)start on every edit

```bash
# one-time per container: create the venv on the home volume, pip install -e
docker exec kirocrew-src-main sh /workspace/docker/dev-bootstrap.sh
docker exec -e KIROCREW_DEV_SRC=/home/kirocrew/upstream-src kirocrew-src-orig \
  sh /home/kirocrew/upstream-src/docker/dev-bootstrap.sh

# every iteration: restart the gateway against the current source
docker exec kirocrew-src-main sh /workspace/docker/dev-run.sh
docker exec -e KIROCREW_DEV_SRC=/home/kirocrew/upstream-src kirocrew-src-orig \
  sh /home/kirocrew/upstream-src/docker/dev-run.sh
```

`dev-run.sh` kills the old gateway (`pkill -f 'kirocrew gateway'`), waits for
the port to free, then launches the production `docker/entrypoint.sh` — which
handles the credential env→file sync and first-run sandbox seeding — under
`setsid` with output redirected to `/home/kirocrew/gateway.log`, so closing
the `docker exec` client does not take the service down. Editing Python
source needs no reinstall (editable install); the restart picks it up.

Front-end assets: the gateway serves `src/kiro_crew/static/dist` from the
mounted tree. For the trunk container build it on the host
(`cd website && npm install && npm run build`, then `make frontend` to stage
`website/dist` into `src/kiro_crew/static/dist` — all git-ignored). The
upstream snapshot already ships a built `dist`.

## Log in to the dashboard

Dashboard links are minted from inside the container (they expire quickly, so
never fish old ones out of logs):

```bash
docker exec kirocrew-src-main kirocrew token --ttl 2h
# open the printed link, replacing the host with the instance domain:
#   https://kiro-ddev.gb10.zhuopu.net/?token=...
```

Chat sessions additionally need kiro-cli authenticated **inside the
container** (its credentials live on the home-volume):

```bash
docker exec -it kirocrew-src-main kiro-cli login
```

The login is interactive; do it once per container by hand. Verify the
result via `GET /api/kiro-prerequisite?token=...` (`authenticated` flips to
true).

## Sandbox posture: why `KIROCREW_ALLOW_UNSANDBOXED=1`

The intended posture is the container's own inner user-namespace sandbox,
with `docker/seccomp/kirocrew-seccomp.json` unblocking `unshare`/`clone`/
`mount`. Measured on this host: the seccomp profile is applied and `unshare
-Ur` succeeds, but the sandbox's probe dies at `mount(MS_REC|MS_PRIVATE)`
with EACCES — and the same `unshare -Ur mount -t tmpfs` fails **on the host
itself**, i.e. the kernel/AppArmor layer refuses mounts inside unprivileged
user namespaces; no seccomp profile can grant that. Widening caps
(`--privileged`) was out of scope for a dev harness. So both instances set
`KIROCREW_ALLOW_UNSANDBOXED=1` (same posture as the pre-existing
`kirocrew-docker`): the container itself remains the OS isolation boundary,
and the product's exec guard flows the opt-in through its audited path
(`sandbox=auto` + `sandbox_allow_unsandboxed_exec`). The custom seccomp
profile is still mounted — when the host's userns policy is fixed, drop the
env var, delete `config.json`, restart, and the inner sandbox returns.

## Housekeeping

- Trunk container mounts a **worktree**, not `main` itself, so `git pull` in
  the main checkout never disturbs a running dev gateway; point the mount at
  whichever checkout you are working in.
- Named volumes (`kirocrew-dev-home-{main,orig}`) hold the venv,
  `KIROCREW_HOME`, logs, and the upstream snapshot. `docker rm` the container
  and re-run `docker run` to recreate it without losing state; delete the
  volume only to reset the instance.
- `docker stop` pauses an instance; nothing else on this host shares these
  containers.
