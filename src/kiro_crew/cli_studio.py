"""``kirocrew studio`` -- the operator backend for AI Studio releases.

The dashboard gives a user two buttons: 〔确认需求，开始开发〕 and 〔确认发布〕. The
second one IS the gateway's ``prod-server/deploy`` (cut a version, then release it)
and its behaviour is unchanged. This command is the finer grain the UI deliberately
does not show: cut a version WITHOUT releasing, plus read what a release left behind.
All three subcommands go through the gateway's HTTP API and never import the backend:
the "a deploy is in flight" fact lives on an in-process object
(``prodserver.ProdServer._busy_gen``), so a second process that built its own
``ProdServer`` would route around the gate that refuses a concurrent deploy and would
really spawn a second pair of processes onto the same two ports and the same domain.

The three subcommands:

* ``kirocrew studio version <project>`` → POST ``.../prod-server/version`` (cut only)
* ``kirocrew studio release <project>`` → POST ``.../prod-server/deploy`` (release)
* ``kirocrew studio status <project>``  → GET  ``.../prod-server``

Gateway URL: ``--gateway`` > ``KIROCREW_GATEWAY_URL`` > ``http://127.0.0.1:6790``.

Authentication copies the existing way a CLI reaches ``/api/apps/**``
(:func:`kiro_crew.app_lifecycle_client.toggle_app` is the same two steps): those
routes are NOT in ``dashboard.server._MIXED_INTERNAL_API_PATHS``, so
``X-Internal-Secret`` does not authenticate them -- they accept a dashboard token --
and a CLI holds no browser cookie. What it holds is the owner-only 0600 local secret,
so it mints a short-lived token from ``GET /api/token/local`` and presents it as
``?token=``. A failed mint is not fatal: the business request is sent anyway, because
the gateway's own 401/403 says more precisely why than this CLI can guess.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from kiro_crew import cli_help
from kiro_crew.loopback_http import loopback_urlopen

#: Fallback when neither ``--gateway`` nor the environment variable is set. 6790 is
#: the port this AI Studio stack's gateway listens on; it is deliberately NOT
#: ``kirocrew gateway``'s default port, which is read from config -- resolving the
#: config here would hang the slack/numpy chain (~1.1 s) off one ``kirocrew studio``
#: call, which is what ``test_cli_lazy_imports.py`` exists to keep impossible. Point
#: at another gateway with ``--gateway`` / ``KIROCREW_GATEWAY_URL`` rather than adding
#: a second guess here.
DEFAULT_GATEWAY = "http://127.0.0.1:6790"

#: The app's prefix on the gateway, the same literal as ``_BASE`` in
#: ``ai_studio/backend/routes.py``.
_APP_BASE = "/api/apps/ai-studio"

#: The only hosts this command hands its local credential to (and the only ones whose
#: unix socket it looks up). A ``--gateway`` on another machine has no use for this
#: machine's secret, so sending it there is a leak, not a shortcut.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

#: One request's ceiling. ``release`` is the heaviest and still answers 202: the
#: acceptance gate is checked synchronously and the seven steps hand off to a gateway
#: thread, so a minutes-long build is never waited for on this hop. The 30 s is
#: headroom for the git calls and the ledger write on slow disk.
_REQUEST_TIMEOUT_S = 30.0

#: Life of the minted token: long enough for this one command, dead soon after.
_TOKEN_TTL = "2m"

#: Subcommand → ``(method, path template, one-line description)``. One body runs all
#: three; these are the only three differences.
_SUBCOMMANDS: dict[str, tuple[str, str, str]] = {
    "version": ("POST", f"{_APP_BASE}/projects/{{project}}/prod-server/version", "cut a version"),
    "release": ("POST", f"{_APP_BASE}/projects/{{project}}/prod-server/deploy", "release"),
    "status": ("GET", f"{_APP_BASE}/projects/{{project}}/prod-server", "read the state"),
}


class StudioRefusal(Exception):
    """Work this command refuses to do: bad arguments, a bad URL, or a gateway refusal.

    Carries the exit code so no helper has to print-and-return. 1 means the gateway
    refused -- a real answer about the project -- and 2 means the command line itself
    was wrong, which is the difference a script branches on.
    """

    def __init__(self, message: str, code: int = 2) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def register_studio_parser(sub: argparse._SubParsersAction) -> None:
    """Wire ``kirocrew studio`` into the top-level parser, the way bench is wired."""
    parser = cli_help.add_command(
        sub,
        "studio",
        description=(
            "AI Studio release backend: cut a version without releasing, release, or "
            "read the state. All three call the gateway's HTTP API, so what they say "
            "about a deploy in flight is the same answer the dashboard sees."
        ),
    )
    _add_gateway_flag(parser)
    studio_sub = parser.add_subparsers(dest="studio_action", required=True)
    for name, (_method, _path, doing) in _SUBCOMMANDS.items():
        one = studio_sub.add_parser(name, help=doing)
        one.add_argument("project", help="AI Studio project id (the id on the project card)")
        # SUPPRESS, not a second default: the flag is repeated on the subparser so
        # ``kirocrew studio version p1 --gateway X`` works (options last is the hand
        # people reach for), but a subparser re-applies its OWN default for every dest
        # it declares, which would silently erase a --gateway given to the main
        # command. SUPPRESS means "absent from the namespace unless typed".
        _add_gateway_flag(one, default=argparse.SUPPRESS)


def _add_gateway_flag(parser: argparse.ArgumentParser, default: Any = None) -> None:
    parser.add_argument(
        "--gateway",
        default=default,
        help=f"gateway URL (default: $KIROCREW_GATEWAY_URL, else {DEFAULT_GATEWAY})",
    )


def studio_cmd(args: argparse.Namespace) -> int:
    """Run one ``kirocrew studio`` subcommand and return the process exit code.

    Success: stdout carries ONLY the JSON body the gateway returned -- no banner, no
    prose -- because the contract is ``json.loads(stdout)``. Failure: stdout is empty,
    the reason goes to stderr, and the code says whose fault it was.
    """
    try:
        return _studio_dispatch(args)
    except StudioRefusal as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return exc.code


def _studio_dispatch(args: argparse.Namespace) -> int:
    action = getattr(args, "studio_action", None)
    if action not in _SUBCOMMANDS:
        raise StudioRefusal("usage: kirocrew studio {version|release|status} <project>")
    project = str(getattr(args, "project", "") or "").strip()
    if not project:
        raise StudioRefusal("missing project id")
    method, path_template, doing = _SUBCOMMANDS[action]
    base = gateway_base(getattr(args, "gateway", None))
    url = base + path_template.format(project=urllib.parse.quote(project, safe=""))
    status, payload = _request(method, url)
    if not 200 <= status < 300:
        # The gateway's refusal is ``{"error", "code"}`` (``routes._error``). That
        # ``error`` string IS the human answer (「先通过验收…」, 「部署正在进行中」);
        # paraphrasing it here would replace a reason with a guess about it. The
        # ``code`` rides along because a script branches on it while the operator
        # reads the sentence, and exit 1 cannot carry both on its own.
        message = _failure_message(payload, status)
        code = _failure_code(payload)
        if code and code not in message:
            message = f"{message} [{code}]"
        raise StudioRefusal(f"{doing} failed: {message}", 1)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def gateway_base(raw: str | None = None) -> str:
    """``--gateway`` / environment / default → a base URL with no trailing slash.

    Only ``http``/``https`` with a host survives: a mistyped value (a scheme-less
    ``127.0.0.1:6790``) reaches urllib as ``ValueError: unknown url type``, and a
    traceback there never tells the operator which word they left out.
    """
    value = (raw or os.environ.get("KIROCREW_GATEWAY_URL") or DEFAULT_GATEWAY).strip()
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise StudioRefusal(f"bad gateway URL: {value!r} (spell it http://127.0.0.1:6790)")
    return value.rstrip("/")


def _request(method: str, url: str) -> tuple[int, Any]:
    """Send one request → ``(status, decoded body)``.

    Mint-then-call, in that order and for a reason: the business route authenticates a
    dashboard token only, so calling it bare returns 401 ``Token required`` -- useless
    to an operator whose actual problem is that the local secret could not be read
    (gateway not running, wrong port). The mint step is what reports that.
    """
    token = _local_token(url)
    if token:
        url = f"{url}?{urllib.parse.urlencode({'token': token})}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method=method)
    try:
        with _urlopen(req, _gateway_socket(url)) as response:
            return int(getattr(response, "status", 200) or 200), _read_json(response)
    except urllib.error.HTTPError as exc:
        # The gateway ANSWERED (4xx/5xx): its status and body are the verdict, not a
        # transport failure. HTTPError subclasses URLError, so this arm must come first.
        return int(exc.code), _read_json(exc)
    except (urllib.error.URLError, OSError) as exc:
        # Nothing answered at all (nobody on the port, DNS, a reset): the URL belongs in
        # the message because "wrong --gateway" and "gateway died" look identical
        # otherwise, and only one of them is a typo.
        raise StudioRefusal(f"gateway did not answer ({url}): {getattr(exc, 'reason', exc)}", 1)


def _local_token(url: str) -> str:
    """Local secret → a short-lived dashboard token; empty string when unavailable.

    Reads the secret only for a loopback host (:data:`_LOOPBACK_HOSTS`). Failing to
    mint is not an error -- see :func:`_request` -- but it is not silent either, since
    a 401 is the only thing the operator would otherwise see.
    """
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    port = _port_of(url)
    if host not in _LOOPBACK_HOSTS or port is None:
        return ""
    secret = _local_secret(port)
    if not secret:
        return ""
    mint = urllib.request.Request(
        f"http://{host}:{port}/api/token/local?ttl={_TOKEN_TTL}",
        headers={"X-Local-Secret": secret},
    )
    try:
        with _urlopen(mint, _gateway_socket(url)) as response:
            payload = _read_json(response)
    except Exception as exc:
        print(
            f"note: could not mint a gateway token ({type(exc).__name__}); " "retrying without one",
            file=sys.stderr,
        )
        return ""
    token = payload.get("token") if isinstance(payload, dict) else None
    return token if isinstance(token, str) else ""


# -- the seam to the outside world: a test replaces _urlopen and nothing real runs


def _urlopen(req: urllib.request.Request, socket_path: str | None = None):
    """The transport: prefer the gateway's 0600 unix socket, whose peer the kernel proves.

    Wrapped rather than calling :func:`loopback_urlopen` inline so a test can stand in
    for it. The contract under test is method + path + gateway status → stdout + exit
    code; a real socket would add nothing to that and would make the suite depend on a
    running gateway.
    """
    return loopback_urlopen(req, timeout=_REQUEST_TIMEOUT_S, unix_socket_path=socket_path)


def _local_secret(port: int) -> str:
    from kiro_crew.config.loader import read_local_secret

    return read_local_secret(port)


def _gateway_socket(url: str) -> str | None:
    """That gateway's unix socket path, or None (``loopback_urlopen`` falls back to TCP).

    Imported inside the function because ``dashboard.urls`` is an expensive chain (see
    its own docstring); a non-loopback ``--gateway`` must not go looking for a local
    socket at all.
    """
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host not in _LOOPBACK_HOSTS:
        return None
    port = _port_of(url)
    if port is None:
        return None
    try:
        from kiro_crew.dashboard.urls import dashboard_socket_path

        return str(dashboard_socket_path(port))
    except Exception:
        return None


def _port_of(url: str) -> int | None:
    """The URL's port, its scheme default when unset, None when unparseable.

    None means "send no credential", which is the safe direction for a URL this
    command cannot make sense of.
    """
    parsed = urllib.parse.urlsplit(url)
    try:
        return parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None


def _read_json(response: Any) -> Any:
    """Body → JSON; anything that is not JSON comes back as text, never as a raise.

    Non-JSON is often the only clue available: something answering in front of the
    gateway (a reverse proxy, a stale port owner) returns HTML, and showing that text
    beats a ``JSONDecodeError``.
    """
    try:
        raw = response.read()
    except Exception:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _failure_message(payload: Any, status: int) -> str:
    """The refusal's sentence: ``error``, else ``message``, else ``code``, else status."""
    if isinstance(payload, dict):
        for key in ("error", "message", "code"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(payload, str) and payload.strip():
        return payload.strip()
    return f"HTTP {status}"


def _failure_code(payload: Any) -> str:
    """The refusal's stable id (``not_accepted``, ``already_deploying``), "" if absent."""
    if isinstance(payload, dict):
        value = payload.get("code")
        if isinstance(value, str):
            return value.strip()
    return ""
