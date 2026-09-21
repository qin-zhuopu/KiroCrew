# Linux server ops: the dev stack behind a reverse proxy

How this fork's dev stack runs on a shared Linux server: the editable-install
gateway, the Vite dev server, the container reverse proxy that publishes them on
a domain, the AppArmor profile the OS sandbox needs on Ubuntu >= 23.10, and the
backend choice for hosts without a Kiro account.

## Topology

```
browser ──HTTPS──▶ nginx-proxy (container)
                     │  VIRTUAL_HOST auto-discovery on the proxy network
                     ▼
                  web-gateways (nginx container, one conf.d file per domain)
                     │  proxy_pass http://<bridge-gateway-ip>:<port>
                     ├──────────────────────▶ vite dev server   host :3000
                     └──────────────────────▶ kirocrew gateway  host :6777
```

- One domain belongs to exactly ONE proxy registration across the fleet. If two
  containers register the same `VIRTUAL_HOST`, nginx-proxy round-robins between
  them and roughly half the requests — including token exchanges — land on the
  wrong backend, which reads as intermittent auth failure. Check with
  `docker inspect` for `VIRTUAL_HOST` before claiming a domain.
- The proxy reaches the host through the bridge gateway IP (e.g. `10.244.2.1` for
  the proxy network), so both servers must bind non-loopback and the config must
  carry that IP.

## Bring-up

From the repo root (after `bash minimal_install.sh` has built the frontend and
created `.venv`):

```bash
# gateway — MUST launch through the venv launcher script, see AppArmor below
KIROCREW_HOME=$PWD/.kirocrew-dev KIROCREW_BIND=0.0.0.0 KIROCREW_PORT=6777 \
KIROCREW_CORS_ORIGINS=https://<dashboard-domain> \
setsid .venv/bin/kirocrew gateway --no-open >> .kirocrew-dev/logs/gateway.log 2>&1 < /dev/null & disown

# vite dev server (config overlay below)
(cd website && KIROCREW_PORT=6777 setsid npx vite --config vite.kirodev.config.ts \
  >> ../.kirocrew-dev/logs/vite.log 2>&1 < /dev/null & disown)
```

- `KIROCREW_BIND=0.0.0.0` widens only the TCP bind; token auth, the CSRF origin
  check, and the Host barrier still apply.
- `KIROCREW_CORS_ORIGINS` adds the public origin to the CSRF allowlist
  (`build_allowed_origins` in `dashboard/urls.py`). Without it every
  domain-originated mutating request fails the origin check.
- Restart the gateway by PID off the listener, not `pkill -f` (the pattern matches
  the invoking shell too): `ss -tlnp | grep 6777` names it.
- The gateway inherits `ANTHROPIC_*` and similar env at launch; export
  endpoint vars before starting it, not after.

## Vite allowedHosts overlay

Vite >= 6.2 refuses requests whose `Host` is not loopback unless allowlisted, and
there is no CLI flag for it — dev access through a proxy domain 403s. This fork
carries `website/vite.kirodev.config.ts` with the deployment domain allowlisted;
on another host, edit the `allowedHosts` entry to match it:

```ts
import { defineConfig } from 'vite'
import baseConfig from './vite.config'
const base = baseConfig as unknown as Record<string, unknown>
export default defineConfig({
  ...base,
  server: {
    ...(base.server as Record<string, unknown>),
    host: '0.0.0.0',
    allowedHosts: ['<dashboard-domain>'],
  },
})
```

## AppArmor: the OS sandbox on Ubuntu >= 23.10

`kernel.apparmor_restrict_unprivileged_userns=1` (Ubuntu default) blocks the
user-namespace + mount-namespace pair `sandbox.py` needs; every agent spawn then
fails closed with `unshare(CLONE_NEWNS) … EPERM`. The fix is a per-app profile
granting `userns` — never the kernel-wide sysctl:

```bash
.venv/bin/kirocrew sandbox install-profile --path "$PWD/.venv/bin/kirocrew"
```

- The profile (`/etc/apparmor.d/kirocrew-launcher`) ATTACHES to the launcher
  script, and the kernel applies an attachment at `execve()`. Launching via
  `python -m kiro_crew` skips the launcher and runs unconfined — always exec
  `.venv/bin/kirocrew`.
- Path validation refuses group/world-writable directories anywhere on the path
  and shared interpreters. If it rejects, tighten the directory modes
  (`chmod g-w <dir>`) rather than moving the install.
- Verify a running gateway is covered:
  `PID=$(ss -tlnp | grep 6777 | grep -oE 'pid=[0-9]+' | cut -d= -f2); sudo cat /proc/$PID/attr/current`
  — expect `kirocrew-launcher (unconfined)`.

## Dashboard access

- Dashboard login is a token, not a password:
  `KIROCREW_HOME=$PWD/.kirocrew-dev .venv/bin/kirocrew token --port 6777`
  mints a short-lived URL; open it ONCE through the public domain, the session
  cookie (~20 h) is bound to that host+port, and later visits need no token.
- With the Vite overlay a `/?token=…` request is completed by the
  `kirocrew-token-proxy` plugin, which sets the cookie and redirects — the raw
  `kirocrew token` output names the gateway port, swap it to the vite port when
  logging into the dev surface.

## Backend without a Kiro account

`agent.acp_backend` selects the harness (`''` = kiro, plus `claude`, `kas`,
`codex`, `goose`, `opencode`, `pi`). The Kiro backend has no API-key path — its
`profileArn` comes only from a Kiro sign-in (dashboard login flow). On a host
without a Kiro account, use the claude backend:

```bash
.venv/bin/kirocrew config set agent.acp_backend claude
```

It spawns `claude-agent-acp` (install with
`npm i -g @agentclientprotocol/claude-agent-acp`) and authenticates through the
`ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` the gateway process already
carries; the endpoint's model-name mapping decides which model answers. Never
hardcode a model id in config for this — `model: auto` resolves through the
endpoint.

## Stop

```bash
kill $(ss -tlnp | grep 6777 | grep -oE 'pid=[0-9]+' | cut -d= -f2)   # gateway
pkill -f 'vite.kirodev.config'                                       # vite
```

`.venv/bin/kirocrew sandbox remove-profile` removes the AppArmor grant.
