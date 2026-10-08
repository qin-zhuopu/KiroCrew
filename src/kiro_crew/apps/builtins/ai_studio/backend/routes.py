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
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiohttp import web

from kiro_crew.apps.builtins.ai_studio.backend import (
    devruns,
    devserver,
    graph,
    projects,
    publish,
    requirements,
)
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


async def _handle_publish_jobs(request: web.Request) -> web.StreamResponse:
    # T8 (§〇-2 发布历史列表): the project's release-jobs, newest first —
    # the release-job detail page renders its whole history from this one
    # read (pinning the running job to the top is the frontend's sort).
    # A transparent pass-through of ``publish.list_jobs``: the job fields
    # are the store's (id/version/form/status/ts, plus commitHash when the
    # publish trigger wrote one), and the detail page reads nothing else
    # into them.
    project_id = request.query.get("project", "")
    try:
        jobs = await asyncio.to_thread(publish.list_jobs, project_id)
    except publish.PublishError as exc:
        return _error(str(exc), exc.code, exc.status)
    return web.json_response({"jobs": jobs})


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


async def _handle_graph(request: web.Request) -> web.StreamResponse:
    # GET /graph[?project_id=…]: the requirement graph mapped to the
    # StudioGraph wire shape (ACP-847). The PoC's data source is the bundled
    # real graph file; project_id is accepted for shape parity with the
    # other routes but the mapping itself is project-independent.
    name = request.query.get("graph", "knowledge-doc-upload-v1")
    try:
        doc = await asyncio.to_thread(graph.load_graph, name)
        studio = await asyncio.to_thread(graph.to_studio_graph, doc)
    except graph.GraphError as exc:
        return _error(str(exc), exc.code, exc.status)
    return web.json_response({"graphId": doc.get("graphId"), "graph": studio})


async def _handle_freeze(request: web.Request) -> web.StreamResponse:
    # POST /projects/{id}/freeze: one immutable record per version label;
    # a duplicate freezes at the store (FreezeError → 409, ACP-847).
    project_id = request.match_info["project_id"]
    body = await _body(request)
    version = body.get("version")
    doc_name = body.get("docName")
    if not isinstance(version, str) or not isinstance(doc_name, str) or not doc_name:
        return _error("version and docName are required", "freeze_fields_required", 400)
    try:
        rec = await asyncio.to_thread(
            graph.freeze,
            project_id,
            version,
            doc_name,
            str(body.get("notes", "")),
            str(body.get("graph", "knowledge-doc-upload-v1")),
        )
    except graph.FreezeError as exc:
        return _error(str(exc), exc.code, 409)
    except graph.GraphError as exc:
        return _error(str(exc), exc.code, exc.status)
    except OSError:
        logger.exception("ai-studio freeze write failed")
        return _error("could not write the freeze record", "store_write_failed", 503)
    return web.json_response({"freeze": rec}, status=201)


async def _handle_freeze_list(request: web.Request) -> web.StreamResponse:
    project_id = request.match_info["project_id"]
    records = await asyncio.to_thread(graph.list_freezes, project_id)
    return web.json_response({"freezes": records})


async def _handle_distill(request: web.Request) -> web.StreamResponse:
    # POST /projects/{id}/distill: compare the committed doc with the graph's
    # promise and record the candidates (T7, ACP-851). Proposal only — the
    # graph does not move here.
    project_id = request.match_info["project_id"]
    body = await _body(request)
    graph_name = str(body.get("graph", "knowledge-doc-upload-v1"))
    doc_name = str(body.get("docName", "requirements.md"))
    release_version = str(body.get("releaseVersion", ""))
    try:
        rec = await asyncio.to_thread(
            graph.distill, project_id, graph_name, doc_name, release_version
        )
    except graph.GraphError as exc:
        return _error(str(exc), exc.code, exc.status)
    except OSError:
        logger.exception("ai-studio distill write failed")
        return _error("could not write the distill record", "store_write_failed", 503)
    return web.json_response({"distillation": rec}, status=201)


async def _handle_distill_list(request: web.Request) -> web.StreamResponse:
    project_id = request.match_info["project_id"]
    records = await asyncio.to_thread(graph.list_distills, project_id)
    return web.json_response({"distillations": records})


async def _handle_devrun_start(request: web.Request) -> web.StreamResponse:
    # POST /projects/{id}/dev-runs: run the four phases through the bgdd
    # gate (T7 step 4). The gate subprocess is long — it runs off the event
    # loop and the record lands complete with the response, because a
    # half-written 'running' record nobody owns is a stuck spinner.
    project_id = request.match_info["project_id"]
    body = await _body(request)
    design_version = str(body.get("designVersion", "v1"))
    release_version = str(body.get("releaseVersion", ""))
    try:
        rec = await asyncio.to_thread(devruns.run_dev, project_id, design_version, release_version)
    except devruns.DevRunError as exc:
        return _error(str(exc), exc.code, exc.status)
    except OSError:
        logger.exception("ai-studio dev run write failed")
        return _error("could not write the dev run record", "store_write_failed", 503)
    return web.json_response({"run": rec}, status=201)


async def _handle_devrun_list(request: web.Request) -> web.StreamResponse:
    project_id = request.match_info["project_id"]
    try:
        records = await asyncio.to_thread(devruns.list_runs, project_id)
    except devruns.DevRunError as exc:
        return _error(str(exc), exc.code, exc.status)
    return web.json_response({"runs": records})


async def _handle_devrun_get(request: web.Request) -> web.StreamResponse:
    project_id = request.match_info["project_id"]
    run_id = request.match_info["run_id"]
    try:
        rec = await asyncio.to_thread(devruns.get_run, project_id, run_id)
    except devruns.DevRunError as exc:
        return _error(str(exc), exc.code, exc.status)
    return web.json_response({"run": rec})


async def _requirements_target(request: web.Request) -> Path | web.Response:
    # Shared prologue for the two requirement reads: the project must exist and
    # its workspace (the repo that actually holds docs/需求图谱) must resolve.
    # Returning the error response instead of raising keeps the handlers a
    # straight line.
    project_id = request.match_info["project_id"]
    record = await asyncio.to_thread(projects.get_project, project_id)
    if record is None:
        return _error("project not found", "project_not_found", 404)
    ws = requirements.workspace_dir(record, projects.projects_root() / project_id)
    return ws


async def _handle_requirements_list(request: web.Request) -> web.StreamResponse:
    # GET /projects/{id}/requirements (RFC §9.4 B1): the workspace's pages with
    # their verdicts. A missing docs/需求图谱 is an empty list, not a 404 — the
    # right-hand tab has a legitimate empty state.
    target = await _requirements_target(request)
    if isinstance(target, web.Response):
        return target
    try:
        pages = await asyncio.to_thread(requirements.list_pages, target)
    except requirements.RequirementError as exc:
        return _error(str(exc), exc.code, exc.status)
    return web.json_response({"pages": pages})


async def _handle_requirement_page(request: web.Request) -> web.StreamResponse:
    # GET /projects/{id}/requirements/{page} (RFC §9.4 B2): graph + verdict +
    # rendered doc, read-only. Runs off the loop because each read spawns two
    # reqdoc subprocesses.
    target = await _requirements_target(request)
    if isinstance(target, web.Response):
        return target
    page = request.match_info["page"]
    try:
        result = await asyncio.to_thread(requirements.get_page, target, page)
    except requirements.RequirementError as exc:
        return _error(str(exc), exc.code, exc.status)
    return web.json_response(result)


async def _handle_regen(request: web.Request) -> web.StreamResponse:
    # POST /projects/{id}/regen: render the acceptance doc FROM the graph
    # into the draft layer (graph→doc direction of the BGDD loop, ACP-847).
    project_id = request.match_info["project_id"]
    body = await _body(request)
    graph_name = str(body.get("graph", "knowledge-doc-upload-v1"))
    doc_name = str(body.get("docName", "requirements.md"))
    try:
        result = await asyncio.to_thread(graph.regen, project_id, graph_name, doc_name)
    except graph.GraphError as exc:
        return _error(str(exc), exc.code, exc.status)
    except OSError:
        logger.exception("ai-studio regen write failed")
        return _error("could not write the regen draft", "store_write_failed", 503)
    return web.json_response(result, status=201)


async def _dev_server_target(request: web.Request) -> devserver.DevServer | web.Response:
    # Shared prologue for the four dev-server routes (RFC §9.6): the project must
    # exist and its workspace (where .ai-studio/dev-server.json lives) must
    # resolve. The DevServer itself is process-cached by dev_server_for — the
    # "starting" fact lives on the object, so a fresh instance per request would
    # report a launching project as stopped and let a second click spawn a second
    # set of processes.
    project_id = request.match_info["project_id"]
    record = await asyncio.to_thread(projects.get_project, project_id)
    if record is None:
        return _error("project not found", "project_not_found", 404)
    ws = requirements.workspace_dir(record, projects.projects_root() / project_id)
    return devserver.dev_server_for(record, ws)


async def _handle_dev_server_get(request: web.Request) -> web.StreamResponse:
    # GET /projects/{id}/dev-server: the recomputed truth (pid alive + URL 200),
    # never the state file alone. Cheap enough to poll every 2s from the top bar.
    target = await _dev_server_target(request)
    if isinstance(target, web.Response):
        return target
    try:
        view = await asyncio.to_thread(target.status)
    except OSError:
        logger.exception("ai-studio dev-server status read failed")
        return _error("could not read the dev server state", "store_write_failed", 503)
    return web.json_response(view)


async def _handle_dev_server_start(request: web.Request) -> web.StreamResponse:
    # POST /projects/{id}/dev-server/start: validates the domain rules inline
    # (a bad 代号 or a missing 工号 is a 400 with zero processes spawned) and then
    # hands the six-step chain to a background thread, answering `starting` at
    # once — an install is minutes long and no HTTP handler may wait for it.
    target = await _dev_server_target(request)
    if isinstance(target, web.Response):
        return target
    try:
        view = await asyncio.to_thread(target.start)
    except devserver.DevServerError as exc:
        return _error(str(exc), exc.code, exc.status)
    return web.json_response(view, status=202)


async def _handle_dev_server_stop(request: web.Request) -> web.StreamResponse:
    # POST /projects/{id}/dev-server/stop: kill the process groups, drop the
    # gateway conf (+reload), release the ports. Runs inline — it is bounded by
    # the 5s SIGTERM grace, not by a package install.
    target = await _dev_server_target(request)
    if isinstance(target, web.Response):
        return target
    try:
        view = await asyncio.to_thread(target.stop)
    except devserver.DevServerError as exc:
        return _error(str(exc), exc.code, exc.status)
    return web.json_response(view)


async def _handle_dev_server_log(request: web.Request) -> web.StreamResponse:
    # GET /projects/{id}/dev-server/log?lines=50: the tail of the merged
    # stdout/stderr of both children, which is where a failed step's real error
    # is (the route's `message` is one line by design).
    target = await _dev_server_target(request)
    if isinstance(target, web.Response):
        return target
    raw = request.query.get("lines", "50")
    try:
        lines = int(raw)
    except ValueError:
        lines = 50
    tail = await asyncio.to_thread(target.log_tail, lines)
    return web.json_response({"lines": tail})


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
    app.router.add_get(
        f"{_BASE}/projects/{{project_id}}/requirements",
        _require_enabled(_handle_requirements_list),
    )
    app.router.add_get(
        f"{_BASE}/projects/{{project_id}}/requirements/{{page}}",
        _require_enabled(_handle_requirement_page),
    )
    # RFC §9.6: the dev-server control. ``dev-server/log`` and the bare
    # ``dev-server`` cannot collide — the log route carries a further segment.
    app.router.add_get(
        f"{_BASE}/projects/{{project_id}}/dev-server",
        _require_enabled(_handle_dev_server_get),
    )
    app.router.add_post(
        f"{_BASE}/projects/{{project_id}}/dev-server/start",
        _require_enabled(_handle_dev_server_start),
    )
    app.router.add_post(
        f"{_BASE}/projects/{{project_id}}/dev-server/stop",
        _require_enabled(_handle_dev_server_stop),
    )
    app.router.add_get(
        f"{_BASE}/projects/{{project_id}}/dev-server/log",
        _require_enabled(_handle_dev_server_log),
    )
    app.router.add_get(f"{_BASE}/graph", _require_enabled(_handle_graph))
    app.router.add_post(f"{_BASE}/projects/{{project_id}}/freeze", _require_enabled(_handle_freeze))
    app.router.add_get(
        f"{_BASE}/projects/{{project_id}}/freezes", _require_enabled(_handle_freeze_list)
    )
    app.router.add_post(f"{_BASE}/projects/{{project_id}}/regen", _require_enabled(_handle_regen))
    app.router.add_post(
        f"{_BASE}/projects/{{project_id}}/distill", _require_enabled(_handle_distill)
    )
    app.router.add_get(
        f"{_BASE}/projects/{{project_id}}/distills", _require_enabled(_handle_distill_list)
    )
    app.router.add_post(
        f"{_BASE}/projects/{{project_id}}/dev-runs", _require_enabled(_handle_devrun_start)
    )
    app.router.add_get(
        f"{_BASE}/projects/{{project_id}}/dev-runs", _require_enabled(_handle_devrun_list)
    )
    app.router.add_get(
        f"{_BASE}/projects/{{project_id}}/dev-runs/{{run_id}}", _require_enabled(_handle_devrun_get)
    )
    app.router.add_post(f"{_BASE}/publish", _require_enabled(_handle_publish_trigger))
    app.router.add_get(f"{_BASE}/publish/records", _require_enabled(_handle_publish_records))
    app.router.add_get(f"{_BASE}/publish/preview", _require_enabled(_handle_publish_preview))
    # The literal ``publish/jobs`` cannot collide with the
    # ``publish/{deployment_id}/log`` route: that one carries a further segment.
    app.router.add_get(f"{_BASE}/publish/jobs", _require_enabled(_handle_publish_jobs))
    app.router.add_get(
        f"{_BASE}/publish/{{deployment_id}}/log",
        _require_enabled(_handle_publish_log),
    )
