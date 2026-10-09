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
import threading
from functools import partial, wraps
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiohttp import web

from kiro_crew.apps.builtins.ai_studio.backend import (
    accept,
    devdag,
    devruns,
    devserver,
    graph,
    prodserver,
    projects,
    publish,
    reqsession,
    requirements,
    workspace,
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
    # The 工号 rides along because the new-workspace dialog shows it read-only
    # (RFC §7 A2: it comes from the login, the user cannot type it) and it is
    # also what the dev domain will be built from — showing it before the create
    # is the only way an operator can see the URL they are about to get.
    records = await asyncio.to_thread(projects.list_projects)
    return web.json_response({"projects": records, "staffId": devserver.staff_id()})


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
    # A `code` in the body is what makes this a WORKSPACE create (ACP-2085):
    # the record is written synchronously so the caller has an id to poll, and
    # the four derive steps (clone → personal repo → push → dev server) run in a
    # background thread. Returning 201 with `status: "creating"` is the whole
    # contract — a clone of a monorepo is minutes long and no HTTP handler may
    # wait for it, and the dialog's progress bar reads the record, not this body.
    code = body.get("code")
    template = body.get("template")
    if code is not None and not isinstance(code, str):
        return _error("code must be a string", "bad_code", 400)
    if template is not None and not isinstance(template, str):
        return _error("template must be a string", "bad_template", 400)
    try:
        record = await asyncio.to_thread(projects.create_project, name, description, code, template)
    except (projects.ProjectError, workspace.WorkspaceError) as exc:
        return _error(str(exc), exc.code, exc.status)
    except FileExistsError:
        # The id timestamp collided inside the same second; retrying is right.
        return _error("project id collided, retry", "project_id_collision", 503)
    except OSError:
        logger.exception("ai-studio project create failed")
        return _error("could not write the project", "store_write_failed", 503)
    if code is not None:
        workspace.start_job(record["id"])
    return web.json_response({"project": record}, status=201)


async def _handle_workspace_retry(request: web.Request) -> web.StreamResponse:
    # POST /projects/{id}/retry: re-run the failed step in the background. The
    # 409 is decided here, from the record, BEFORE the thread starts — answering
    # 202 and then discovering "not failed" inside the thread would leave the
    # dialog watching a job that was never started. WorkspaceJob.retry re-checks
    # the same predicate for its own safety (a caller that skipped this route).
    project_id = request.match_info["project_id"]
    record = await asyncio.to_thread(projects.get_project, project_id)
    if record is None:
        return _error("project not found", "project_not_found", 404)
    if record.get("status") != workspace.STATUS_FAILED:
        return _error("当前不是失败状态", "not_failed", 409)
    workspace.start_job(project_id, retry=True)
    return web.json_response({"project": record}, status=202)


def _stop_both_servers(record: dict[str, Any], ws: Path) -> None:
    """删工作区前先停两套服务器；「没在运行」不是失败，是本来就没活儿。

    ``stop()`` 在真没东西可清时抛 409 not_running（那正是停止按钮的语义），而删除
    一个从来没起过服务器的工作区是常态 —— 所以这里只吞这一个 code，其余原样上抛，
    让调用方看见「停了但没停干净」。吞掉全部异常就是拿一个删不掉的工作区换一个不报
    错的按钮：进程、端口、网关卡到的 conf 会跟着目录一起进回收站（那两个类的 stop
    判据整段写的就是这种泄漏）。
    """
    for factory, error_type in (
        (devserver.dev_server_for, devserver.DevServerError),
        (prodserver.prod_server_for, prodserver.ProdServerError),
    ):
        try:
            factory(record, ws).stop()
        except error_type as exc:
            if exc.code != "not_running":
                raise


async def _handle_project_delete(request: web.Request) -> web.StreamResponse:
    # DELETE /projects/{id} (ACP-2206): move the workspace AND the record into
    # .trash, never rm. Order is the contract: stop the servers first (a live
    # vite holding a directory we just moved is a leak nothing on screen can
    # clean), then refuse while a development run is in flight, then move.
    # The remote personal repo stays (RFC) — the local move is cheap and
    # reversible, deleting the remote is not, and one button must not do both.
    project_id = request.match_info["project_id"]
    # keyword-only on the store side (``now`` and ``stop_servers`` are both test
    # seams), so the thread gets a partial rather than a positional guess.
    do_delete = partial(projects.delete_project, project_id, stop_servers=_stop_both_servers)
    try:
        result = await asyncio.to_thread(do_delete)
    except (projects.ProjectError, workspace.WorkspaceError) as exc:
        return _error(str(exc), exc.code, exc.status)
    except OSError:
        logger.exception("ai-studio project delete failed")
        return _error("could not move the project to the trash", "store_write_failed", 503)
    return web.json_response(result)


async def _handle_workspace_log(request: web.Request) -> web.StreamResponse:
    # GET /projects/{id}/workspace-log?lines=80: the tail of the derive command's
    # merged output. It lives next to project.json and NOT in the workspace,
    # because the moment it matters most is a failed clone — when the workspace
    # directory may not exist at all.
    project_id = request.match_info["project_id"]
    if await asyncio.to_thread(projects.get_project, project_id) is None:
        return _error("project not found", "project_not_found", 404)
    raw = request.query.get("lines", "80")
    try:
        lines = int(raw)
    except ValueError:
        lines = 80
    tail = await asyncio.to_thread(workspace.log_tail, project_id, lines)
    return web.json_response({"lines": tail})


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


async def _requirements_ws_and_record(
    request: web.Request,
) -> tuple[Path, dict[str, Any]] | web.Response:
    # The prologue both requirement reads and both writes need: the project must
    # exist and its workspace (the repo that actually holds docs/需求图谱) must
    # resolve. Returning the error response instead of raising keeps the handlers
    # a straight line. The record comes along because the direct-edit route has
    # to name the project to the 需求会话 — reading it twice would let the two
    # reads disagree about which workspace the notice is about.
    project_id = request.match_info["project_id"]
    record = await asyncio.to_thread(projects.get_project, project_id)
    if record is None:
        return _error("project not found", "project_not_found", 404)
    ws = requirements.workspace_dir(record, projects.projects_root() / project_id)
    return ws, record


async def _requirements_target(request: web.Request) -> Path | web.Response:
    target = await _requirements_ws_and_record(request)
    return target[0] if isinstance(target, tuple) else target


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


def _req_error(exc: requirements.RequirementError) -> web.Response:
    # One error body for every requirement write: the store already decided the
    # status by data (a stale docHash is a 409, an unqualified graph a 422) and the
    # frontend switches on `code`, never on the Chinese prose.
    if not exc.details:
        return _error(str(exc), exc.code, exc.status)
    # 422 ``not_ready`` answers WITH data (RFC §10 验收 11): the verdict and the
    # gaps the on-the-spot check found, so the bar redraws from the refusal it got
    # instead of from what it was displaying. Named fields, not a merged bag — the
    # body's shape is then readable here rather than wherever a detail was set.
    missing = exc.details.get("missing")
    return web.json_response(
        {
            "error": str(exc),
            "code": exc.code,
            "verdict": exc.details.get("verdict"),
            "missing": [str(x) for x in missing] if isinstance(missing, list) else [],
        },
        status=exc.status,
    )


async def _handle_requirement_direct_edit(request: web.Request) -> web.StreamResponse:
    # POST /projects/{id}/requirements/{page}/direct-edit (RFC §9.4, §7 B5): the
    # user edited the GENERATED document in the editor. The doc is a view of the
    # graph, so this does not "save a doc" — it records the change and hands the
    # diff to the 需求会话, which lands it back into the graph (the graph stays the
    # single writer-writable source of truth; this route never touches the json).
    target = await _requirements_ws_and_record(request)
    if isinstance(target, web.Response):
        return target
    ws, record = target
    state = request.app.get("state")
    if state is None:  # pragma: no cover - the dashboard always sets it
        # Refused BEFORE the ledger row: an edit nobody can be told about would
        # pin the bar at 「改动待落回需求」 with no one to land it.
        return _error("dashboard state is unavailable", "state_unavailable", 503)
    body = await _body(request)
    base = body.get("baseDocHash")
    markdown = body.get("markdown")
    if not isinstance(base, str) or not isinstance(markdown, str):
        return _error("baseDocHash and markdown are required", "base_doc_hash_required", 400)
    page = request.match_info["page"]
    try:
        result = await asyncio.to_thread(requirements.direct_edit, ws, page, base, markdown)
    except requirements.RequirementError as exc:
        return _req_error(exc)
    except OSError:
        logger.exception("ai-studio direct-edit ledger write failed")
        return _error("could not write the direct-edit record", "store_write_failed", 503)
    if not result.get("changed"):
        # nothing to tell anyone: an identical save is not a change request
        return web.json_response(result)
    try:
        await reqsession.send_to_req_session(
            state, record, ws, reqsession.edit_notice(page, str(result.get("diff") or ""))
        )
    except reqsession.ReqSessionError as exc:
        return _error(str(exc), exc.code, exc.status)
    except Exception:
        # The ledger row already landed, so the bar's 「改动待落回需求」 is the true
        # statement either way; failing the request here would throw away a save
        # the user made and could not re-make from a reloaded view.
        logger.exception("ai-studio direct-edit notice could not reach the session")
    return web.json_response(result)


async def _handle_requirement_start(request: web.Request) -> web.StreamResponse:
    # POST /projects/{id}/requirements/{page}/start (RFC §9.4, §7 B6): 开始开发.
    # The verdict is re-run HERE (requirements.start re-reads the graph and shells
    # to `check`), because the frontend's bar is a 5-second-old observation and
    # R2 makes the record's graphHash the hash THIS check used. Task splitting and
    # dispatching are another work stream's job — this route's whole product is
    # the append-only start-requests row.
    target = await _requirements_target(request)
    if isinstance(target, web.Response):
        return target
    body = await _body(request)
    graph_hash_value = body.get("graphHash")
    if not isinstance(graph_hash_value, str) or not graph_hash_value:
        return _error("graphHash is required", "graph_hash_required", 400)
    try:
        result = await asyncio.to_thread(
            requirements.start, target, request.match_info["page"], graph_hash_value
        )
    except requirements.RequirementError as exc:
        return _req_error(exc)
    except OSError:
        logger.exception("ai-studio start-request ledger write failed")
        return _error("could not write the start request", "store_write_failed", 503)
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


async def _handle_req_session(request: web.Request) -> web.StreamResponse:
    # POST /projects/{id}/req-session (RFC §9.3): hand the left column the
    # workspace's 需求会话. Idempotent — the first call creates the slot, scopes it
    # at the workspace and sends the opening prompt; every later call returns the
    # same key and sends nothing. The frontend mounts ChatEmbed on the returned
    # key instead of minting its own slot, which is the whole point: a slot the
    # browser named has no `project`, so the assistant would write files into the
    # gateway's directory instead of the workspace's.
    project_id = request.match_info["project_id"]
    record = await asyncio.to_thread(projects.get_project, project_id)
    if record is None:
        return _error("project not found", "project_not_found", 404)
    state = request.app.get("state")
    if state is None:  # pragma: no cover - the dashboard always sets it
        return _error("dashboard state is unavailable", "state_unavailable", 503)
    try:
        # resolve_workspace runs in the thread with the read it depends on: a
        # recorded workspaceDir that has since been deleted is a 409 there, and
        # `ensure_req_session` never sees a directory it would write into the
        # wrong place.
        ws = await asyncio.to_thread(
            reqsession.resolve_workspace, record, projects.projects_root() / project_id
        )
        result = await reqsession.ensure_req_session(state, record, ws)
    except reqsession.ReqSessionError as exc:
        return _error(str(exc), exc.code, exc.status)
    return web.json_response(result)


#: One :class:`devdag.DevRun` per project, for the lifetime of the gateway.
#:
#: The loop lives on the object, so a fresh instance per request would read a
#: running project's file as ``running`` with no loop attached and judge it a
#: restart orphan (failing a run that is very much alive), and a second
#: ``start`` would spawn a second loop over the same workspace. Same reasoning
#: as ``devserver._SERVERS``. Cleared wholesale by tests via
#: :func:`_dev_run_for`'s module global.
_DEV_RUNS: dict[str, devdag.DevRun] = {}


def _dev_run_for(project_id: str, record: dict[str, Any], ws: Path, state: Any) -> devdag.DevRun:
    run = _DEV_RUNS.get(project_id)
    if run is None:
        run = devdag.DevRun(state, record, ws)
        _DEV_RUNS[project_id] = run
    return run


async def _dev_target(
    request: web.Request,
) -> tuple[devdag.DevRun, dict[str, Any], Path] | web.Response:
    # Shared prologue for the seven dev/accept routes: the project must exist,
    # its workspace must resolve (that is where .ai-studio/ lives), and the
    # dashboard state must be reachable — a dev task IS a chat session, so
    # without it there is nothing to open one on.
    project_id = request.match_info["project_id"]
    record = await asyncio.to_thread(projects.get_project, project_id)
    if record is None:
        return _error("project not found", "project_not_found", 404)
    ws = requirements.workspace_dir(record, projects.projects_root() / project_id)
    state = request.app.get("state")
    if state is None:
        return _error("no chat state available to open a session", "state_unavailable", 503)
    return _dev_run_for(project_id, record, ws, state), record, ws


async def _handle_dev_start(request: web.Request) -> web.StreamResponse:
    # POST /projects/{id}/dev/start: build the plan and hand the serial loop to
    # the background. ``pages`` omitted = every page the verdict allows (全齐, or
    # 可以开工但有已知缺口 — a known gap is a recorded gap, not a blocker). A page
    # the caller NAMED is honoured as an explicit choice and only 不齐 refuses it
    # (422, with the page names), so the board's 不齐 guard can never be talked
    # out of by omitting the check client-side.
    target = await _dev_target(request)
    if isinstance(target, web.Response):
        return target
    run, _record, ws = target
    body = await _body(request)
    raw_pages = body.get("pages")
    try:
        pages = await asyncio.to_thread(_resolve_dev_pages, ws, raw_pages)
    except requirements.RequirementError as exc:
        return _error(str(exc), exc.code, exc.status)
    except DevPagesError as exc:
        return _error(str(exc), exc.code, exc.status)
    if not pages:
        return _error("no page's requirement is ready for development", "no_pages", 422)
    try:
        result = await run.start(pages)
    except devdag.DevDagError as exc:
        return _error(str(exc), exc.code, exc.status)
    except OSError as exc:
        logger.exception("ai-studio dev run start failed")
        return _error(f"could not start the development run: {exc}", "dev_run_write_failed", 503)
    return web.json_response(result, status=202)


class DevPagesError(Exception):
    """A page choice the workspace's own verdicts refuse (404 / 422)."""

    def __init__(self, message: str, code: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


#: 判定为这两种的页才允许开工。「可以开工但有已知缺口」里的缺口是**记着的**缺口，
#: 不是拦路的（RFC §9.4 的三档判定）；「不齐」才是。
DEV_READY_VERDICTS = ("全齐", "可以开工但有已知缺口")


def _resolve_dev_pages(ws: Path, raw_pages: Any) -> list[str]:
    """Validate the requested pages (or pick the allowed ones) against the verdicts.

    Sync on purpose: the caller wraps it in ``asyncio.to_thread``, because each
    verdict is a ``jc fe reqdoc`` subprocess and the gateway loop serves every
    other session while these run.
    """
    listed = requirements.list_pages(ws)
    by_page = {str(p.get("page")): p for p in listed}
    if isinstance(raw_pages, list) and raw_pages:
        pages = [str(p) for p in raw_pages]
        missing = [p for p in pages if p not in by_page]
        if missing:
            raise DevPagesError(f"需求页不存在：{'、'.join(missing)}", "page_not_found", 404)
        # name every 不齐 page, not just the first: the board has to mark them all
        not_ready = [p for p in pages if by_page[p].get("verdict") not in DEV_READY_VERDICTS]
        if not_ready:
            raise DevPagesError(
                f"不齐：还不能开发：{'、'.join(not_ready)}",
                "not_ready",
                422,
            )
        return pages
    return [
        page
        for page, entry in by_page.items()
        if entry.get("verdict") in DEV_READY_VERDICTS and page not in baseline_pages(ws)
    ]


#: 复制模板时就已经在的需求页 = 模板里**已经做好的页面**（它们的需求文档描述的是现状）。
#: 不点名时「拆分任务 / 开始开发」只拿新需求，不许把这些页重做一遍（2026-10-09 实战：
#: 不点名拆出了全部 21 页 42 个任务，第一个就去改模板现有的 AI场景台账）。
BASELINE_FILE = ".ai-studio/baseline-pages.json"


def baseline_pages(ws: Path) -> set[str]:
    try:
        data = json.loads((ws / BASELINE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(p) for p in data} if isinstance(data, list) else set()


async def _handle_dev_plan(request: web.Request) -> web.StreamResponse:
    # POST /projects/{id}/dev/plan: split the work into tasks (and Jira issues)
    # WITHOUT starting it (ACP-2085-S6). Same page rules as dev/start — omitted
    # = every page the verdicts allow, a named 不齐 page is a 422 — because the
    # split is the same decision dev/start makes when it has to auto-plan; two
    # sets of rules would let a page be splittable but undevelopable.
    target = await _dev_target(request)
    if isinstance(target, web.Response):
        return target
    run, _record, ws = target
    body = await _body(request)
    raw_pages = body.get("pages")
    try:
        pages = await asyncio.to_thread(_resolve_dev_pages, ws, raw_pages)
    except requirements.RequirementError as exc:
        return _error(str(exc), exc.code, exc.status)
    except DevPagesError as exc:
        return _error(str(exc), exc.code, exc.status)
    if not pages:
        return _error("no page's requirement is ready for development", "no_pages", 422)
    try:
        state = await run.plan(pages)
    except devdag.DevDagError as exc:
        return _error(str(exc), exc.code, exc.status)
    except OSError as exc:
        logger.exception("ai-studio dev plan write failed")
        return _error(f"could not write the development plan: {exc}", "dev_run_write_failed", 503)
    # the board's own read of what it just produced, so the client never has to
    # assume a shape plan() did not promise
    return web.json_response(state, status=201)


async def _handle_dev_dag(request: web.Request) -> web.StreamResponse:
    # GET /projects/{id}/dev/dag: the board's single read. ``get`` also owns the
    # restart-orphan verdict (a file left at running by a dead process), so the
    # UI never spins forever after a gateway restart.
    target = await _dev_target(request)
    if isinstance(target, web.Response):
        return target
    run, record, _ws = target
    # A copy: the merge below must not write into whatever the run returned (a
    # route must not mutate the object it is reading through).
    state = dict(run.get())
    # The parent link the board's header needs. A key and its URL are ONE fact,
    # so whichever key wins gets exactly its own link — a state carrying ACP-1
    # must never be paired with the record's URL. The record is the fallback
    # because ``ensure_parent`` writes the key into project.json while the
    # cached DevRun's last write may predate it; without this the header would
    # stay empty until a restart even though the issue exists.
    key = str(state.get("jiraParent") or record.get("jiraParent") or "")
    state.update(devdag.node_jira_view({"jiraParent": key}))
    return web.json_response(state)


async def _handle_dev_log(request: web.Request) -> web.StreamResponse:
    # GET /projects/{id}/dev/log?lines=100: the scheduler's own log, which is
    # where a failed node's reason is (the node's `message` is one line).
    target = await _dev_target(request)
    if isinstance(target, web.Response):
        return target
    run, _record, _ws = target
    try:
        lines = int(request.query.get("lines", "100"))
    except ValueError:
        lines = 100
    tail = await asyncio.to_thread(run.log_lines, lines)
    return web.json_response({"lines": tail})


async def _handle_accept_run(request: web.Request) -> web.StreamResponse:
    # POST /projects/{id}/accept/run: the workspace's own checks, exit codes
    # only. Off the loop — this is a pnpm typecheck plus a unit suite, minutes
    # long, and the gateway loop serves every other session.
    target = await _dev_target(request)
    if isinstance(target, web.Response):
        return target
    run, _record, ws = target
    state = run.get()
    try:
        record = await asyncio.to_thread(accept.run_accept, ws, state)
    except accept.AcceptError as exc:
        return _error(str(exc), exc.code, exc.status)
    except OSError:
        logger.exception("ai-studio accept record write failed")
        return _error("could not write the acceptance record", "store_write_failed", 503)
    return web.json_response({"record": record}, status=201)


async def _handle_accept_records(request: web.Request) -> web.StreamResponse:
    target = await _dev_target(request)
    if isinstance(target, web.Response):
        return target
    _run, _record, ws = target
    records = await asyncio.to_thread(accept.list_records, ws)
    return web.json_response({"records": records})


async def _handle_accept_fix(request: web.Request) -> web.StreamResponse:
    # POST /projects/{id}/accept/fix: hand a FAILED acceptance back to the
    # assistant (ACP-2210). The record is whatever the board's own read says is
    # newest (list_records is newest-first) rather than an id from the body:
    # the UI has exactly one candidate in view, and taking an id would let a
    # stale tab "fix" a record the operator has since re-run.
    target = await _dev_target(request)
    if isinstance(target, web.Response):
        return target
    run, _record, ws = target
    records = await asyncio.to_thread(accept.list_records, ws)
    if not records:
        return _error("no acceptance record to fix", "nothing_to_fix", 409)
    try:
        result = await run.fix(records[0])
    except devdag.DevDagError as exc:
        return _error(str(exc), exc.code, exc.status)
    except OSError as exc:
        logger.exception("ai-studio accept fix start failed")
        return _error(f"could not start the fix run: {exc}", "dev_run_write_failed", 503)
    return web.json_response(result, status=202)


async def _prod_server_target(request: web.Request) -> prodserver.ProdServer | web.Response:
    # Shared prologue for the four prod-server routes (ACP-2085-S5): the project
    # must exist and its workspace (where .ai-studio/prod-server.json lives) must
    # resolve. ``prod_server_for`` caches the object process-wide because the
    # "deploying" fact lives on it — a fresh instance per request would report a
    # deploying project as stopped and let a second click spawn a second set.
    project_id = request.match_info["project_id"]
    record = await asyncio.to_thread(projects.get_project, project_id)
    if record is None:
        return _error("project not found", "project_not_found", 404)
    ws = requirements.workspace_dir(record, projects.projects_root() / project_id)
    return prodserver.prod_server_for(record, ws)


async def _handle_prod_server_get(request: web.Request) -> web.StreamResponse:
    # GET /projects/{id}/prod-server: the recomputed truth (pids alive AND the
    # stable URL answers 200), never the state file alone. Polled every 2s while
    # deploying; a build is minutes long so the poll is the only honest UI.
    target = await _prod_server_target(request)
    if isinstance(target, web.Response):
        return target
    try:
        view = await asyncio.to_thread(target.status)
    except OSError:
        logger.exception("ai-studio prod-server status read failed")
        return _error("could not read the prod server state", "store_write_failed", 503)
    return web.json_response(view)


async def _handle_prod_server_deploy(request: web.Request) -> web.StreamResponse:
    # POST /projects/{id}/prod-server/deploy: the acceptance gate is checked
    # SYNCHRONOUSLY (a 409 not_accepted is a refusal a human must read, not a
    # failure that appears after we already said 「部署中」), then the seven steps
    # hand off to a background thread — a build never blocks a request.
    target = await _prod_server_target(request)
    if isinstance(target, web.Response):
        return target
    try:
        view = await asyncio.to_thread(target.deploy)
    except prodserver.ProdServerError as exc:
        return _error(str(exc), exc.code, exc.status)
    return web.json_response(view, status=202)


async def _handle_prod_server_stop(request: web.Request) -> web.StreamResponse:
    # POST /projects/{id}/prod-server/stop: kill the process groups, drop the
    # gateway conf (+reload), release the ports. Inline — bounded by the SIGTERM
    # grace, not by a build.
    target = await _prod_server_target(request)
    if isinstance(target, web.Response):
        return target
    try:
        view = await asyncio.to_thread(target.stop)
    except prodserver.ProdServerError as exc:
        return _error(str(exc), exc.code, exc.status)
    return web.json_response(view)


async def _handle_prod_server_log(request: web.Request) -> web.StreamResponse:
    # GET /projects/{id}/prod-server/log?lines=80: the tail of the build output
    # and both children's merged stdout/stderr — the route's `message` is one
    # line by design, and a build failure's real error is never in one line.
    target = await _prod_server_target(request)
    if isinstance(target, web.Response):
        return target
    try:
        lines = int(request.query.get("lines", "80"))
    except ValueError:
        lines = 80
    tail = await asyncio.to_thread(target.log_tail, lines)
    return web.json_response({"lines": tail})


def _recover_interrupted_workspaces() -> None:
    """新网关起来时把上次没跑完的派生判成失败（ACP-2111）。

    线程而不是 ``await``：这是全盘扫项目目录 + 逐个改写，注册路径在事件循环上，
    一次同步的目录遍历就是卡住整个网关（no-blocking-call-on-event-loop）。daemon
    线程而不是 app 的 ``on_startup``：``hooks_integration`` 会按磁盘签名重跑钩子，
    一个 ``routes`` 的改动就能让 ``on_startup`` 再响一次；而这件事本身是幂等的
    （判完就是 failed，第二遍扫到的是零条），多跑一次不出错。异常只写日志：一个
    坏记录不许把路由注册带下来 —— 那等于让整条 ai-studio API 因为一次重启的
    残留而 404。
    """

    def _run() -> None:
        try:
            recovered = workspace.recover_interrupted()
            if recovered:
                logger.info("ai-studio recovered %d interrupted workspace(s)", recovered)
        except Exception:
            logger.warning("ai-studio workspace recovery failed", exc_info=True)

    threading.Thread(target=_run, daemon=True, name="ai-studio-workspace-recover").start()


def register_routes(app: web.Application) -> None:
    # 开机先收上次没跑完的派生，再挂路由：早一秒把谎话改过来，新建对话框就早一秒
    # 从「永远转圈」变成能点重试。放线程里，注册本身不被一次目录遍历拖住。
    _recover_interrupted_workspaces()
    app.router.add_get(f"{_BASE}/projects", _require_enabled(_handle_projects_list))
    app.router.add_post(f"{_BASE}/projects", _require_enabled(_handle_project_create))
    app.router.add_get(f"{_BASE}/projects/{{project_id}}", _require_enabled(_handle_project_get))
    # ACP-2206: the one write that removes anything. No path collision — this is
    # a DELETE on the same literal path as the GET/POST above, and aiohttp keys
    # its table by (method, path).
    app.router.add_delete(
        f"{_BASE}/projects/{{project_id}}", _require_enabled(_handle_project_delete)
    )
    app.router.add_post(
        f"{_BASE}/projects/{{project_id}}/retry", _require_enabled(_handle_workspace_retry)
    )
    app.router.add_get(
        f"{_BASE}/projects/{{project_id}}/workspace-log",
        _require_enabled(_handle_workspace_log),
    )
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
    # RFC §9.3: the workspace's 需求会话. A literal segment, so it cannot collide
    # with the ``requirements/{page}`` read above.
    app.router.add_post(
        f"{_BASE}/projects/{{project_id}}/req-session",
        _require_enabled(_handle_req_session),
    )
    # ACP-2104 (RFC §9.4, §7 B5/B6): the two requirement WRITES. Both are literal
    # segments below ``requirements/{page}``, so neither can be reached by the
    # ``{page}`` read above — the read has no further segment to give away.
    app.router.add_post(
        f"{_BASE}/projects/{{project_id}}/requirements/{{page}}/direct-edit",
        _require_enabled(_handle_requirement_direct_edit),
    )
    app.router.add_post(
        f"{_BASE}/projects/{{project_id}}/requirements/{{page}}/start",
        _require_enabled(_handle_requirement_start),
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
    # ACP-2085-S4: the development board and its acceptance run. The literal
    # ``dev/start`` / ``dev/dag`` / ``dev/log`` cannot collide with the
    # ``dev-server`` family (a further segment each) or with ``dev-runs``.
    # ACP-2085-S6: ``dev/plan`` splits the work (and the Jira issues) apart from
    # running it. Same non-collision argument as above: the literal ``dev/plan``
    # shares no path with ``dev/start`` / ``dev/dag`` / ``dev/log`` / dev-server.
    app.router.add_post(
        f"{_BASE}/projects/{{project_id}}/dev/plan",
        _require_enabled(_handle_dev_plan),
    )
    app.router.add_post(
        f"{_BASE}/projects/{{project_id}}/dev/start",
        _require_enabled(_handle_dev_start),
    )
    app.router.add_get(
        f"{_BASE}/projects/{{project_id}}/dev/dag",
        _require_enabled(_handle_dev_dag),
    )
    app.router.add_get(
        f"{_BASE}/projects/{{project_id}}/dev/log",
        _require_enabled(_handle_dev_log),
    )
    app.router.add_post(
        f"{_BASE}/projects/{{project_id}}/accept/run",
        _require_enabled(_handle_accept_run),
    )
    app.router.add_post(
        f"{_BASE}/projects/{{project_id}}/accept/fix",
        _require_enabled(_handle_accept_fix),
    )
    app.router.add_get(
        f"{_BASE}/projects/{{project_id}}/accept/records",
        _require_enabled(_handle_accept_records),
    )
    # ACP-2085-S5: the production server. ``prod-server`` is a literal segment
    # distinct from ``dev-server`` (they differ at the 5th character), and
    # ``prod-server/deploy`` / ``/stop`` / ``/log`` carry a further segment, so
    # nothing here can be reached by another route.
    app.router.add_get(
        f"{_BASE}/projects/{{project_id}}/prod-server",
        _require_enabled(_handle_prod_server_get),
    )
    app.router.add_post(
        f"{_BASE}/projects/{{project_id}}/prod-server/deploy",
        _require_enabled(_handle_prod_server_deploy),
    )
    app.router.add_post(
        f"{_BASE}/projects/{{project_id}}/prod-server/stop",
        _require_enabled(_handle_prod_server_stop),
    )
    app.router.add_get(
        f"{_BASE}/projects/{{project_id}}/prod-server/log",
        _require_enabled(_handle_prod_server_log),
    )
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
