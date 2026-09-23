"""AI Studio project HTTP routes.

Mounted at ``/api/apps/ai-studio/`` (the per-app namespace every builtin
backend uses; the frontend reaches it through the scoped app api, whose
allowlist the manifest declares). Shape follows crew_companion: every handler
runs behind ``_require_enabled`` so a disabled app answers 403 instead of
serving its data, and every error is a ``{"error", "code"}`` body at a
literal status (the static error-code contract scan).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from functools import wraps
from typing import Any, Awaitable, Callable

from aiohttp import web

from kiro_crew.apps.builtins.ai_studio.backend import projects, publish
from kiro_crew.apps.manager import is_app_enabled

logger = logging.getLogger(__name__)

APP_NAME = "ai-studio"
_BASE = f"/api/apps/{APP_NAME}"

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def _forbidden(message: str, code: str) -> web.Response:
    return web.json_response({"error": message, "code": code}, status=403)


def _error(message: str, code: str, status: int) -> web.Response:
    # The status is computed, which the error-code contract scan would flag
    # as `dynamic_status` UNLESS the body is a transparent dict carrying a
    # `code` — which it is, so this is compliant for every status the store
    # and the handlers can return (400/404/503). One helper because the store
    # already decided
    # the status by data (a bad name is a 400, a missing project a 404), and
    # re-spelling each as its own literal helper would fork one message path
    # into three for no gate benefit.
    return web.json_response({"error": message, "code": code}, status=status)


def _require_enabled(handler: Handler) -> Handler:
    """403 while the app is disabled (a synchronous installed.json read, run
    off the loop — same reasoning as crew_companion's wrapper)."""

    @wraps(handler)
    async def _wrapped(request: web.Request) -> web.StreamResponse:
        if not await asyncio.to_thread(is_app_enabled, APP_NAME):
            return _forbidden("ai-studio is disabled", "app_disabled")
        return await handler(request)

    return _wrapped


async def _body(request: web.Request) -> dict[str, Any]:
    try:
        parsed = await request.json()
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def _handle_projects_list(request: web.Request) -> web.StreamResponse:
    records = await asyncio.to_thread(projects.list_projects)
    return web.json_response({"projects": records})


async def _handle_project_get(request: web.Request) -> web.StreamResponse:
    project_id = request.match_info["project_id"]
    record = await asyncio.to_thread(projects.get_project, project_id)
    if record is None:
        return _error("project not found", "project_not_found", 404)
    docs = await asyncio.to_thread(projects.list_docs, project_id)
    return web.json_response({"project": record, "docs": docs})


async def _handle_project_create(request: web.Request) -> web.StreamResponse:
    body = await _body(request)
    name = body.get("name")
    description = body.get("description")
    if not isinstance(name, str) or not isinstance(description, str):
        return _error("name and description are required", "name_required", 400)
    try:
        record = await asyncio.to_thread(projects.create_project, name, description)
    except projects.ProjectError as exc:
        return _error(str(exc), exc.code, exc.status)
    except FileExistsError:
        # The id timestamp collided inside the same second; retrying is right.
        return _error("project id collided, retry", "project_id_collision", 503)
    except OSError:
        logger.exception("ai-studio project create failed")
        return _error("could not write the project", "store_write_failed", 503)
    return web.json_response({"project": record}, status=201)


async def _handle_doc_save(request: web.Request) -> web.StreamResponse:
    # Semantics since the draft layer: this is COMMIT, not overwrite — the
    # store snapshots the committed content into versions/ and clears the
    # doc's drafts (see projects.save_doc).
    project_id = request.match_info["project_id"]
    body = await _body(request)
    name = body.get("name")
    content = body.get("content")
    if not isinstance(name, str) or not isinstance(content, str):
        return _error("name and content are required", "invalid_doc", 400)
    try:
        doc = await asyncio.to_thread(projects.save_doc, project_id, name, content)
    except projects.ProjectError as exc:
        return _error(str(exc), exc.code, exc.status)
    except OSError:
        logger.exception("ai-studio doc save failed")
        return _error("could not write the document", "store_write_failed", 503)
    return web.json_response({"doc": doc})


async def _handle_doc_draft(request: web.Request) -> web.StreamResponse:
    project_id = request.match_info["project_id"]
    body = await _body(request)
    name = body.get("name")
    content = body.get("content")
    if not isinstance(name, str) or not isinstance(content, str):
        return _error("name and content are required", "invalid_doc", 400)
    try:
        draft = await asyncio.to_thread(projects.save_draft, project_id, name, content)
    except projects.ProjectError as exc:
        return _error(str(exc), exc.code, exc.status)
    except OSError:
        logger.exception("ai-studio draft save failed")
        return _error("could not write the draft", "store_write_failed", 503)
    return web.json_response({"draft": draft})


async def _handle_project_drafts(request: web.Request) -> web.StreamResponse:
    # Project-level read for the workspace top bar: which docs hold an
    # uncommitted draft (the project-wide commit iterates this and commits
    # each). One read for the summary and the commit loop's work list.
    project_id = request.match_info["project_id"]
    if await asyncio.to_thread(projects.get_project, project_id) is None:
        return _error("project not found", "project_not_found", 404)
    try:
        drafts = await asyncio.to_thread(projects.list_draft_docs, project_id)
    except OSError:
        logger.exception("ai-studio draft list failed")
        return _error("could not read the drafts", "store_write_failed", 503)
    return web.json_response({"drafts": drafts})


async def _handle_doc_draft_versions(request: web.Request) -> web.StreamResponse:
    project_id = request.match_info["project_id"]
    name = request.match_info["doc_name"]
    try:
        records = await asyncio.to_thread(projects.list_draft_versions, project_id, name)
    except projects.ProjectError as exc:
        return _error(str(exc), exc.code, exc.status)
    # Key ``versions`` (not ``draftVersions``): the editor client types both
    # history reads the same shape, one key name for both endpoints.
    return web.json_response({"versions": records})


async def _handle_doc_versions(request: web.Request) -> web.StreamResponse:
    project_id = request.match_info["project_id"]
    name = request.match_info["doc_name"]
    try:
        versions = await asyncio.to_thread(projects.list_versions, project_id, name)
    except projects.ProjectError as exc:
        return _error(str(exc), exc.code, exc.status)
    return web.json_response({"versions": versions})


async def _handle_publish_records(request: web.Request) -> web.StreamResponse:
    # B3/B4: the release records of one project, newest first. The publish
    # view derives the per-version published/unpublished states and the
    # "latest published hash" (the newest success record's hash) from this
    # one read.
    project_id = request.query.get("project", "")
    try:
        records = await asyncio.to_thread(publish.list_release_records, project_id)
    except publish.PublishError as exc:
        return _error(str(exc), exc.code, exc.status)
    return web.json_response({"records": records})


async def _handle_publish_preview(request: web.Request) -> web.StreamResponse:
    # B1: per-version form judgment. A ``rejected`` form is a 200 verdict
    # body, not an error — the publish view renders the reason inline.
    project_id = request.query.get("project", "")
    version = request.query.get("version", "")
    try:
        verdict = await asyncio.to_thread(publish.preview_version, project_id, version)
    except publish.PublishError as exc:
        return _error(str(exc), exc.code, exc.status)
    return web.json_response(verdict)


def _jwt_sub(token: str) -> str | None:
    """The ``sub`` claim of a JWT payload, read WITHOUT verifying the
    signature or expiry — the dev-environment posture the owner pinned
    (拍板 2026-09-23). A malformed token yields None, never an error: the
    publish URL's operator segment is a convenience label, and a broken
    credential must not take the endpoint down.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload_b64 = parts[1]
    try:
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, TypeError):
        return None
    sub = payload.get("sub") if isinstance(payload, dict) else None
    return sub if isinstance(sub, str) and sub else None


def _operator_from_request(request: web.Request) -> str | None:
    """The publish URL's 工号, from the session identity the gateway already
    established: the ``Authorization: Bearer <jwt>`` ``sub`` claim first,
    then ``X-Forwarded-User``. None means no identity rode on the request
    and the store's dev default applies.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        sub = _jwt_sub(auth[len("Bearer ") :].strip())
        if sub:
            return sub
    forwarded = request.headers.get("X-Forwarded-User", "")
    return forwarded or None


async def _handle_publish_trigger(request: web.Request) -> web.StreamResponse:
    # B2: one POST per publish-button click. Idempotent on the latest
    # success hash (no new record, ``idempotent: true``), 409 on the same
    # hash already publishing, otherwise a new release-job run through the
    # real executor chain (T3: build → stop-old → start-new). The URL's
    # operator segment comes from the request's session identity (JWT
    # ``sub``, dev posture: no signature/expiry check — owner 2026-09-23).
    body = await _body(request)
    project_id = body.get("project")
    version = body.get("version")
    commit_hash = body.get("commitHash")
    if not isinstance(project_id, str) or not isinstance(version, str):
        return _error("project, version and commitHash are required", "invalid_publish", 400)
    operator = _operator_from_request(request) or publish.DEFAULT_OPERATOR
    hash_value = commit_hash if isinstance(commit_hash, str) else ""
    try:
        result = await asyncio.to_thread(
            publish.trigger_publish, project_id, version, hash_value, operator=operator
        )
    except publish.PublishError as exc:
        return _error(str(exc), exc.code, exc.status)
    return web.json_response(result, status=200 if result.get("idempotent") else 201)


#: How often the running-job log stream re-reads the log file. The executor
#: appends to a plain file, so the stream is a bounded poll of durable state
#: (SSE carries the push; the file is the source of truth T3 cannot lose).
_LOG_POLL_S = 0.2

#: Hard cap on one log stream's lifetime, so a job wedged in ``running``
#: releases the connection instead of holding it forever.
_LOG_STREAM_MAX_S = 600.0


async def _handle_publish_log(request: web.Request) -> web.StreamResponse:
    # T4 (§〇-2 后台日志流): the release-job's execution log. A running job
    # streams SSE frames that grow with the file ("边发边长"); a finished job
    # replays the full log in one final frame and closes — the frontend reads
    # both through the same EventSource code path.
    project_id = request.query.get("project", "")
    deployment_id = request.match_info["deployment_id"]
    try:
        text, status = await asyncio.to_thread(publish.job_log_snapshot, project_id, deployment_id)
    except publish.PublishError as exc:
        return _error(str(exc), exc.code, exc.status)

    response = web.StreamResponse(
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )
    await response.prepare(request)
    offset = 0
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _LOG_STREAM_MAX_S
    try:
        while True:
            new = text[offset:]
            offset = len(text)
            done = status != "running"
            if new or done:
                frame = json.dumps(
                    {
                        "lines": new.splitlines(),
                        "done": done,
                        "status": status,
                    },
                    ensure_ascii=False,
                )
                await response.write(f"data: {frame}\n\n".encode())
            if done or loop.time() >= deadline:
                break
            await asyncio.sleep(_LOG_POLL_S)
            text, status = await asyncio.to_thread(
                publish.job_log_snapshot, project_id, deployment_id
            )
    except (ConnectionResetError, asyncio.CancelledError):
        pass  # the tab closed mid-stream; nothing to answer
    return response


def register_routes(app: web.Application) -> None:
    app.router.add_get(f"{_BASE}/projects", _require_enabled(_handle_projects_list))
    app.router.add_post(f"{_BASE}/projects", _require_enabled(_handle_project_create))
    app.router.add_get(f"{_BASE}/projects/{{project_id}}", _require_enabled(_handle_project_get))
    app.router.add_get(
        f"{_BASE}/projects/{{project_id}}/drafts",
        _require_enabled(_handle_project_drafts),
    )
    app.router.add_post(f"{_BASE}/projects/{{project_id}}/docs", _require_enabled(_handle_doc_save))
    # The literal ``docs/draft`` segment cannot collide with the
    # ``docs/{doc_name}/…`` history routes: those carry a further segment.
    app.router.add_post(
        f"{_BASE}/projects/{{project_id}}/docs/draft",
        _require_enabled(_handle_doc_draft),
    )
    app.router.add_get(
        f"{_BASE}/projects/{{project_id}}/docs/{{doc_name}}/draft-versions",
        _require_enabled(_handle_doc_draft_versions),
    )
    app.router.add_get(
        f"{_BASE}/projects/{{project_id}}/docs/{{doc_name}}/versions",
        _require_enabled(_handle_doc_versions),
    )
    app.router.add_post(f"{_BASE}/publish", _require_enabled(_handle_publish_trigger))
    app.router.add_get(f"{_BASE}/publish/records", _require_enabled(_handle_publish_records))
    app.router.add_get(f"{_BASE}/publish/preview", _require_enabled(_handle_publish_preview))
    app.router.add_get(
        f"{_BASE}/publish/{{deployment_id}}/log",
        _require_enabled(_handle_publish_log),
    )
