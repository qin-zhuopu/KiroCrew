# A builtin app's routes stay 404 until BUILTIN_NAMES lists it, and a proxied dev domain 403s POSTs only

## Symptom

Two failures while wiring the AI Studio project backend, neither readable from its error:

1. `GET /api/apps/ai-studio/projects` returned `{"error": "not found"}` (404) even
   though the package imported cleanly, `hasattr(ai_studio, "register_routes")`
   was `True` in a REPL, and the same handler code passed every route test under
   `aiohttp.test_utils`. Restarting the gateway changed nothing.
2. Once routes served, `GET /api/apps/ai-studio/projects` from the browser
   worked, but the very same session's `POST` returned
   `403 CSRF check failed: request origin not allowed.` — a plain-text body with
   no JSON `code`, from middleware, not from the handler. Reads all worked, every
   write failed, and nothing in the handler's code path was involved.

## Root cause

1. The gateway's builtin-route scan
   (`dashboard/routes/system.py`, `for _builtin_name in BUILTIN_NAMES`)
   iterates the **hardcoded list** in `kiro_crew/apps/builtins/__init__.py`.
   A package that exists on disk but is absent from that list is never imported
   at startup — the `hasattr(register_routes)` check never runs, the routes are
   silently never mounted, and every probe of the REPL (which imports the
   package directly, bypassing the scan) says everything is fine. `ai_studio`
   was simply missing from the list.
2. `check_origin` (`dashboard/origin.py`) validates the browser `Origin`
   against `app["allowed_origins"]`, built by `build_allowed_origins`
   (`dashboard/urls.py`) from loopback defaults + `dashboard_url` config +
   `KIROCREW_CORS_ORIGINS`. The CSRF middleware guards only mutating methods
   (`_CSRF_SAFE_METHODS` = GET/HEAD/OPTIONS skip it) — which is exactly why GET
   200'd while POST 403'd. The dev domain `https://kiro-dev.gb10.zhuopu.net`
   was in none of the origin sources, and Host validation passed anyway because
   `build_allowed_hosts` matches on hostname only (port/scheme-independent),
   masking how narrow the origin set was.

## Fix

1. Added `"ai_studio"` to `BUILTIN_NAMES`, and declared
   `backend.routes: "backend.routes:register_routes"` in `app.json` for parity
   with `issue_radar` / `personal_shopper` (the in-gateway apps carry both:
   the package re-export for the scan, the manifest field for the
   route-registry/hook-reconcile path).
2. Relaunched the dev gateway with
   `KIROCREW_CORS_ORIGINS=https://kiro-dev.gb10.zhuopu.net`. (This is
   dev-home-only env, not a repo change — production origins come from the
   `dashboard_url` config path.)

## How to avoid

- When a new builtin's routes 404 on a running gateway: first check
  `kiro_crew.apps.builtins.BUILTIN_NAMES` membership — not the handler, not the
  manifest. A REPL import proves the module is importable, which was never the
  question; only the scan mounts routes.
- When browser reads work but writes 403 with the plain-text CSRF body: the
  Origin is not in `allowed_origins`, and the asymmetry is by design (CSRF skips
  safe methods). Check `build_allowed_origins`'s inputs — `dashboard_url`,
  `KIROCREW_CORS_ORIGINS`, `KIROCREW_ALLOWED_LOOPBACK_PORTS` — before suspecting
  the handler or the app's permission manifest.
- A third trap found while verifying the same feature end-to-end: on the dev
  domain the page rendered but every `/api/*` call returned an empty **502**,
  while `curl` against the gateway succeeded. The vite `/api` proxy target is
  `http://localhost:${process.env.KIROCREW_PORT || 5476}` (`vite.config.ts`) —
  read when vite STARTS. The gateway had been relaunched on 6777 but the vite
  process still pointed at 5476, so the proxy died silently. Restart vite with
  the same `KIROCREW_PORT` the gateway uses.
- And a long-lived vite dev server re-runs its dependency optimizer and
  re-stamps `?t=` on chunks; in-flight module requests then `ERR_FAILED`, the
  SPA caches the load-failure shell, and "Clear cache and retry" keeps failing
  until the optimizer settles. `rm -rf website/node_modules/.vite` + restart is
  the clean exit; warm the big chat chunks before an E2E run.
- Related note with the frontend-side traps from the same feature:
  [20260922-154851-ai-studio-tiptap.md](20260922-154851-ai-studio-tiptap.md).
