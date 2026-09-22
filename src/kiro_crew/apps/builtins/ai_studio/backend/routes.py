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
import logging
from functools import wraps
from typing import Any, Awaitable, Callable

from aiohttp import web

from kiro_crew.apps.builtins.ai_studio.backend import projects
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


def register_routes(app: web.Application) -> None:
    app.router.add_get(f"{_BASE}/projects", _require_enabled(_handle_projects_list))
    app.router.add_post(f"{_BASE}/projects", _require_enabled(_handle_project_create))
    app.router.add_get(
        f"{_BASE}/projects/{{project_id}}", _require_enabled(_handle_project_get)
    )
    app.router.add_get(
        f"{_BASE}/projects/{{project_id}}/drafts",
        _require_enabled(_handle_project_drafts),
    )
    app.router.add_post(
        f"{_BASE}/projects/{{project_id}}/docs", _require_enabled(_handle_doc_save)
    )
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
