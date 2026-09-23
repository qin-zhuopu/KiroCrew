"""The AI Studio publish store: release-jobs, releases and per-version form.

Layout (under the project directory this module shares with ``projects.py``)::

    <data home>/ai-studio/projects/<project-id>/
        publish/records/<stamp>-<n>.json   # one release record per file
        publish/jobs/<jobId>.json          # one release-job per file

Two concepts, never merged (the publish acceptance doc pins this): a
**release-job** is one execution of the publish button — an id, a status, a
log; a failed job produces nothing outward. A **release** is the outward fact
a *successful* job creates — the version serving at a URL in a form. The
sidebar's published states and the "latest published hash" are derived from
releases, never from jobs.

Each record is one small JSON file, appended never rewritten: the records
endpoint is a directory scan sorted by timestamp, the same no-cache,
plain-sync-I/O posture ``projects.py`` takes (routes call it through
``asyncio.to_thread``; tests drive it with ``KIROCREW_HOME`` at tmp_path).

Form judgment (``preview_version``) reads the project's **git tag** for the
version — the owner's decision: the tag's annotation names the form
(``full`` / ``demo``, 完整版 / 演示版), and NO acceptance record is
consulted. The project directory IS the project's git repository (dev commits
and version tags land there). No repository, no tag, or an annotation naming
neither form reads as ``rejected`` with a reason, never as an error — the
publish view renders the reason inline rather than a failed request.
"""

from __future__ import annotations

import json
import re
import secrets
import subprocess
import time
from pathlib import Path
from typing import Any

from kiro_crew.apps.builtins.ai_studio.backend import projects

#: Hard cap on stored per-project record files — a bound on the directory
#: scan, not a security boundary.
MAX_RECORDS = 500

#: Tokens in a tag annotation that name a form. 完整版/演示版 are what the
#: acceptance doc calls the two forms; full/demo are their ascii spellings.
_FORM_FULL = ("full", "完整版")
_FORM_DEMO = ("demo", "演示版")

_VERSION_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class PublishError(Exception):
    """A refused publish-store operation, with the HTTP status to map."""

    def __init__(self, message: str, code: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def _project_dir(project_id: str) -> Path:
    """The project directory, 404ing through ``PublishError`` when absent."""
    if projects.get_project(project_id) is None:
        raise PublishError("project not found", "project_not_found", 404)
    return projects.projects_root() / project_id


def _records_dir(project_dir: Path) -> Path:
    return project_dir / "publish" / "records"


def _jobs_dir(project_dir: Path) -> Path:
    return project_dir / "publish" / "jobs"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _stamp(now: float) -> str:
    # Same shape as projects._stamp: UTC fixed-width so lexical order is
    # chronological order; milliseconds break same-second ties.
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime(now)) + f"-{int(now % 1 * 1000):03d}"


# ---------------------------------------------------------------------------
# release records
# ---------------------------------------------------------------------------


def record_release(
    project_id: str,
    *,
    version: str,
    commit_hash: str,
    form: str,
    requirement_version: str,
    jira_task_ids: list[str],
    url: str,
    deployment_id: str,
    status: str = "success",
) -> dict[str, Any]:
    """Append one release record and return it.

    The caller (the publish trigger) supplies every field: this store is the
    durability layer, not the policy. ``requirement_version`` is the frozen
    requirements version the release is traceable to, ``jira_task_ids`` the
    task ids bound to the project at trigger time — both ride on the record
    so B3's traceability assertions read one file.
    """
    project_dir = _project_dir(project_id)
    now = time.time()
    record: dict[str, Any] = {
        "deploymentId": deployment_id,
        "version": version,
        "commitHash": commit_hash,
        "form": form,
        "requirementVersion": requirement_version,
        "jiraTaskIds": list(jira_task_ids),
        "status": status,
        "url": url,
        "ts": now,
    }
    base = _stamp(now)
    path = _records_dir(project_dir) / f"{base}.json"
    n = 1
    while path.exists():
        path = _records_dir(project_dir) / f"{base}-{n}.json"
        n += 1
    try:
        _write_json(path, record)
    except OSError as exc:
        raise PublishError("could not write the record", "store_write_failed", 503) from exc
    return record


def list_release_records(project_id: str) -> list[dict[str, Any]]:
    """The project's release records, newest first.

    A record file that fails to parse or lacks an id is skipped, not raised:
    one damaged file must not take the whole publish view down (the same
    tolerate-and-skip read ``projects`` applies to history snapshots).
    """
    project_dir = _project_dir(project_id)
    records_dir = _records_dir(project_dir)
    if not records_dir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(records_dir.iterdir()):
        if not path.is_file() or not path.name.endswith(".json"):
            continue
        record = _read_json(path)
        if record is None or not isinstance(record.get("version"), str):
            continue
        out.append(record)
    out.sort(key=lambda r: r.get("ts") or 0, reverse=True)
    return out[:MAX_RECORDS]


def latest_release(project_id: str) -> dict[str, Any] | None:
    """The newest ``status=="success"`` record, or None (nothing published).

    The "latest published hash" comparison and the per-version published
    states both derive from this — a failed or superseded job never counts.
    """
    for record in list_release_records(project_id):
        if record.get("status") == "success":
            return record
    return None


# ---------------------------------------------------------------------------
# release-jobs
# ---------------------------------------------------------------------------


def record_job(
    project_id: str,
    *,
    version: str,
    form: str,
    status: str = "running",
    commit_hash: str | None = None,
) -> dict[str, Any]:
    """Create one release-job (one execution of the publish button).

    ``commit_hash`` rides on the job since the publish trigger (B2): the
    same-hash-in-progress 409 keys on it, so the concurrency check never has
    to guess which running job a repeat trigger belongs to.
    """
    project_dir = _project_dir(project_id)
    now = time.time()
    # The stamp alone is only second+ms wide, and the release-job id IS the
    # filename: two publishes inside the same millisecond (a double click, a
    # retried request) would collide and one job would silently swallow the
    # other. A random suffix breaks the tie; the exists() retry covers the
    # astronomically unlikely suffix clash too.
    jobs_dir = _jobs_dir(project_dir)
    jobs_dir.mkdir(parents=True, exist_ok=True)
    path = jobs_dir / f"job-{_stamp(now)}.json"
    while path.exists():
        path = jobs_dir / f"job-{_stamp(now)}-{secrets.token_hex(4)}.json"
    job: dict[str, Any] = {
        "id": path.stem,
        "version": version,
        "form": form,
        "status": status,
        "ts": now,
    }
    if commit_hash is not None:
        job["commitHash"] = commit_hash
    try:
        _write_json(path, job)
    except OSError as exc:
        raise PublishError("could not write the job", "store_write_failed", 503) from exc
    return job


def update_job_status(project_id: str, job_id: str, status: str) -> dict[str, Any] | None:
    """Move one job to ``running|success|failed`` (the three states the
    release-job page renders); None when the id names no job."""
    if not job_id or "/" in job_id or "\\" in job_id or job_id in (".", ".."):
        return None
    path = _jobs_dir(_project_dir(project_id)) / f"{job_id}.json"
    job = _read_json(path)
    if job is None:
        return None
    job["status"] = status
    try:
        _write_json(path, job)
    except OSError as exc:
        raise PublishError("could not write the job", "store_write_failed", 503) from exc
    return job


def list_jobs(project_id: str) -> list[dict[str, Any]]:
    """The project's release-jobs, newest first (running ones the page pins
    to the top, which is a frontend sort over this order)."""
    project_dir = _project_dir(project_id)
    jobs_dir = _jobs_dir(project_dir)
    if not jobs_dir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(jobs_dir.iterdir()):
        if not path.is_file() or not path.name.endswith(".json"):
            continue
        job = _read_json(path)
        if job is None or not isinstance(job.get("id"), str):
            continue
        out.append(job)
    out.sort(key=lambda j: j.get("ts") or 0, reverse=True)
    return out


# ---------------------------------------------------------------------------
# per-version form judgment (B1)
# ---------------------------------------------------------------------------


def _tag_annotation(project_dir: Path, version: str) -> str | None:
    """The tag ``<version>``'s annotation text, or None when absent.

    Read through ``git for-each-ref`` (plumbing, stable output) rather than a
    ref parse: an annotated tag's ``contents`` is its message — the 标注 the
    owner's decision names. A lightweight tag carries no annotation, and its
    ``contents`` is the commit message, which is not a form annotation; the
    token scan below simply finds nothing there, which is the honest
    ``rejected`` reading of "no annotation".
    """
    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(project_dir),
                "for-each-ref",
                f"refs/tags/{version}",
                "--format=%(contents)",
            ],
            capture_output=True,
            encoding="utf-8",
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _form_from_annotation(annotation: str) -> str | None:
    lowered = annotation.lower()
    if any(token in lowered for token in _FORM_FULL):
        return "full"
    if any(token in lowered for token in _FORM_DEMO):
        return "demo"
    return None


def preview_version(project_id: str, version: str) -> dict[str, Any]:
    """B1: the form one version may publish as, from its git tag annotation.

    ``version`` is a bare tag name (validated, so it cannot traverse the
    ref namespace). Returns ``{"form": "full"|"demo"|"rejected", "reason":
    <非空>}`` — a rejected form is a *verdict*, not an error, because the
    publish view renders the reason inline on the version row.
    """
    project_dir = _project_dir(project_id)
    name = (version or "").strip()
    if not _VERSION_SAFE.match(name) or len(name) > 80:
        raise PublishError("version must be a bare tag name", "invalid_version", 400)

    annotation = _tag_annotation(project_dir, name)
    form = _form_from_annotation(annotation) if annotation else None
    if form == "full":
        return {"form": "full", "reason": "完整版通过验收（git tag 标注为完整版）"}
    if form == "demo":
        return {"form": "demo", "reason": "完整版未通过验收（git tag 标注为演示版），仅可发布演示版"}
    if annotation is None:
        return {"form": "rejected", "reason": f"验收未通过：版本 {name} 无 git tag 标注"}
    return {"form": "rejected", "reason": f"验收未通过：版本 {name} 的 tag 标注无法识别（未注明完整版或演示版）"}


# ---------------------------------------------------------------------------
# publish trigger (B2): idempotent on the latest success hash, 409 on a
# same-hash job already running, otherwise a new release-job
# ---------------------------------------------------------------------------

#: The publish domain template (08 §〇). The operator segment is supplied per
#: trigger — T3 takes it from the JWT ``sub``; until then the route passes its
#: dev default.
URL_TEMPLATE = "{version}-{app}-{operator}.gb10.jereh-pe.cn"

#: The operator segment the route uses until T3 owns the JWT ``sub`` read.
DEFAULT_OPERATOR = "dev"

#: Task md files bind their FILE NAME to the Jira issue: the DAG拆解 agent
#: writes ``tasks/<TASK-ID>.md`` and writes the issue key back into it, so
#: the stem IS the id in both directions (owner 拍板, breakdown T2).
TASKS_DIRNAME = "tasks"

#: The frozen requirements version a release traces to is the project's
#: newest committed ``requirements.md`` snapshot stamp — the requirements
#: commit the project currently sits at (B3 ``requirementVersion``).
_REQUIREMENTS_DOC = "requirements.md"


def publish_url(project_id: str, version: str, operator: str = DEFAULT_OPERATOR) -> str:
    """The URL a successful release of ``version`` serves at (08 §〇 模板)."""
    project = projects.get_project(project_id)
    app = projects.slug(project["name"]) if project else "app"
    return URL_TEMPLATE.format(version=version, app=app or "app", operator=operator or "dev")


def _jira_task_ids(project_dir: Path) -> list[str]:
    """The task ids bound to the project: the stems of ``tasks/*.md``.

    A file that fails to stat is skipped, not raised — the record's
    traceability must not hinge on one damaged file.
    """
    tasks_dir = project_dir / TASKS_DIRNAME
    if not tasks_dir.is_dir():
        return []
    out = []
    for path in sorted(tasks_dir.iterdir()):
        if path.is_file() and path.suffix == ".md" and path.stem:
            out.append(path.stem)
    return out


def _requirement_version(project_dir: Path) -> str:
    """The newest committed ``requirements.md`` snapshot stamp, or ''."""
    snap_dir = project_dir / "versions" / _REQUIREMENTS_DOC
    if not snap_dir.is_dir():
        return ""
    stamps = sorted(p.stem for p in snap_dir.iterdir() if p.is_file() and p.suffix == ".md")
    return stamps[-1] if stamps else ""


def trigger_publish(
    project_id: str,
    version: str,
    commit_hash: str,
    *,
    operator: str = DEFAULT_OPERATOR,
) -> dict[str, Any]:
    """B2: the publish button's backend.

    - ``commitHash`` equals the newest **success** record's hash → nothing
      new is created: the existing ``deploymentId`` comes back with
      ``idempotent: true`` (D2 — re-publishing the latest hash produces no
      new instance and no new record).
    - any other hash, including one published before but no longer latest →
      a normal new release (D3's rollback-style re-publish).
    - the same hash already publishing → 409 ``publish_in_progress``.

    The job this returns runs through :func:`_execute_job`, whose current
    body is the MINIMAL executor (record success in place). **T3 takeover
    point**: only that function changes — real build, stop-old-start-new and
    the live domain all land there; the idempotency, 409 and record-field
    semantics above are already final.
    """
    project_dir = _project_dir(project_id)
    name = (version or "").strip()
    if not _VERSION_SAFE.match(name) or len(name) > 80:
        raise PublishError("version must be a bare tag name", "invalid_version", 400)
    if not isinstance(commit_hash, str) or not commit_hash.strip() or len(commit_hash) > 80:
        raise PublishError("commitHash is required", "invalid_commit_hash", 400)
    commit_hash = commit_hash.strip()

    verdict = preview_version(project_id, name)
    if verdict["form"] == "rejected":
        # A rejected row never renders a button (08 §二 C1); a direct POST
        # for one is refused for the same reason the row is inert.
        raise PublishError(verdict["reason"], "form_rejected", 400)
    form = verdict["form"]

    latest = latest_release(project_id)
    if latest is not None and latest.get("commitHash") == commit_hash:
        return {
            "deploymentId": latest.get("deploymentId"),
            "version": name,
            "commitHash": commit_hash,
            "status": latest.get("status", "success"),
            "idempotent": True,
        }

    running = [
        j
        for j in list_jobs(project_id)
        if j.get("status") == "running"
        and j.get("version") == name
        and j.get("commitHash") == commit_hash
    ]
    if running:
        raise PublishError(
            "this hash is already publishing", "publish_in_progress", 409
        )

    job = record_job(project_id, version=name, form=form, commit_hash=commit_hash)
    return _execute_job(project_dir, job, operator=operator)


def _execute_job(project_dir: Path, job: dict[str, Any], *, operator: str) -> dict[str, Any]:
    """Drive one release-job to its terminal state and, on success, write the
    release record.

    **T3 takeover point** (see :func:`trigger_publish`): this minimal body
    publishes in place — real build, instance replacement and the domain
    binding replace everything below this line, keeping the signature.
    """
    project_id = project_dir.name
    version = job["version"]
    try:
        record = record_release(
            project_id,
            version=version,
            commit_hash=job.get("commitHash", ""),
            form=job["form"],
            requirement_version=_requirement_version(project_dir),
            jira_task_ids=_jira_task_ids(project_dir),
            url=publish_url(project_id, version, operator),
            deployment_id=job["id"],
        )
    except PublishError:
        update_job_status(project_id, job["id"], "failed")
        raise
    update_job_status(project_id, job["id"], "success")
    return {
        "deploymentId": record["deploymentId"],
        "version": version,
        "commitHash": record["commitHash"],
        "status": "success",
        "idempotent": False,
        "job": {**job, "status": "success"},
    }
