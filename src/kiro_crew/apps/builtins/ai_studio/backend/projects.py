"""The AI Studio project store: one directory per project on disk.

Layout (all paths under ``config_dir()``, which honours ``KIROCREW_HOME``)::

    <data home>/ai-studio/projects/<project-id>/
        project.json          # identity: id, name, description, createdAt
        docs/requirements.md  # seeded at creation, edited by the workbench
        docs/workflow.md
        docs/ui-spec.md
        drafts/requirements.md.md            # current autosave draft
        drafts/requirements.md/…ts.md        # per-record draft history
        versions/requirements.md/…ts.md      # full snapshot per commit

Two layers sit beside ``docs/`` because they answer two different questions.
``drafts/`` is the uncommitted scratch: one current file the autosave
overwrites, plus a record per distinct content since the last commit, so the
editor can show "what did I change since I committed" and roll back to any of
it. It is throwaway by construction — committing deletes it. ``versions/`` is
the committed trail: each save writes the content it is committing as a
timestamped snapshot, so the history is a plain ascending list whose row N
diffs against row N-1, and the first row has no predecessor and therefore
reads as wholly added. ``docs/<name>.md`` keeps its existing meaning as the
committed content, so every reader that is not about history (the sidebar,
the chat's context, the next project GET) is untouched by this layer.

A directory that parses as ``project.json`` IS a project — listing reads the
per-project files and nothing else, so a stray directory (a half-finished
create after a crash, a hand-made folder) never appears as a ghost project
with an empty name. Conversely the create path writes ``project.json`` LAST:
a project is visible exactly when its docs already exist, so nothing can ever
open a project whose documents are missing.

This module is deliberately synchronous, plain-Python file I/O: the routes
call it through ``asyncio.to_thread`` (the same off-loop pattern every other
handler in this codebase uses for disk), and tests exercise it with nothing
but a tmp_path. No caches — the store is small, the reads are a directory
scan of already-open files, and an invalidation bug here would mean the
sidebar lying about what exists.
"""

from __future__ import annotations

import difflib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

#: Hard caps on caller-supplied text. Not a security boundary (the caller is
#: an authenticated dashboard session) — they bound the directory scan and
#: keep a project.json a human can read.
MAX_NAME_LEN = 120
MAX_DESCRIPTION_LEN = 2000

_NAME_SAFE = re.compile(r"[^a-z0-9]+")


class ProjectError(Exception):
    """A refused project operation, with the HTTP status the route should map."""

    def __init__(self, message: str, code: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def projects_root() -> Path:
    """The agreed directory: ``<data home>/ai-studio/projects``.

    Resolved per call, never memoised at import: ``config_dir()`` keys its own
    memo on ``KIROCREW_HOME``, and a module-level constant would freeze the
    home a test fixture sets up after import.
    """
    from kiro_crew.config.paths import config_dir

    return config_dir() / "ai-studio" / "projects"


def _slug(name: str) -> str:
    """Filesystem-safe id fragment from a display name.

    Slugs are for humans browsing the data home only — nothing parses them
    back — so a name that survives no transformation (pure emoji, pure CJK
    with the unidecode-free regex) degrades to an empty fragment and the
    caller's timestamp suffix carries the uniqueness.
    """
    return _NAME_SAFE.sub("-", name.lower()).strip("-")[:40]


def _project_json_path(project_dir: Path) -> Path:
    return project_dir / "project.json"


def _read_project(project_dir: Path) -> dict[str, Any] | None:
    """One project record, or None when the directory is not a project.

    A corrupt or non-object ``project.json`` reads as "not a project" rather
    than raising: one hand-edited file must not take the whole list page down,
    and a project the list cannot name would be unopenable anyway (the route
    404s on the same predicate, so list and detail never disagree).
    """
    try:
        raw = _project_json_path(project_dir).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not data["id"]:
        return None
    return data


def list_projects() -> list[dict[str, Any]]:
    root = projects_root()
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        record = _read_project(entry)
        if record is not None:
            out.append(record)
    out.sort(key=lambda p: p.get("createdAt") or 0, reverse=True)
    return out


def get_project(project_id: str) -> dict[str, Any] | None:
    """One record by id, or None.

    The directory name is the id and the id is looked up as a single literal
    path component: ``_read_project`` failing on a traversal attempt (an id
    containing ``/`` never names an existing dir here, and a ``..`` segment
    would have to survive ``create`` first — which it cannot) reads as absence,
    so a forged id 404s exactly like an unknown one and reveals nothing.
    """
    if not project_id or "/" in project_id or "\\" in project_id or project_id in (".", ".."):
        return None
    return _read_project(projects_root() / project_id)


def list_docs(project_id: str) -> list[dict[str, str]]:
    """The project's docs as ``{name, content}``, filename order.

    Content travels whole: these are design documents, small by nature, and
    the workbench edits them as one buffer — a paging protocol here would be
    ceremony around a file the editor holds in memory regardless.
    """
    project = get_project(project_id)
    if project is None:
        return []
    docs_dir = projects_root() / project_id / "docs"
    if not docs_dir.is_dir():
        return []
    out: list[dict[str, str]] = []
    for path in sorted(docs_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".md":
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        out.append({"name": path.name, "content": content})
    return out


def _checked_doc_name(project_id: str, name: str) -> str:
    """Validate a caller-supplied doc name against a stored project.

    The doc name is free caller input, and the one place that keeps it from
    becoming a traversal is this check — reject any path separator, any
    leading dot, anything that is not ``name.md``. Every entry point below
    (save, draft, the two history reads) routes through here so a new caller
    cannot forget the fence.
    """
    if get_project(project_id) is None:
        raise ProjectError("project not found", "project_not_found", 404)
    base = name.strip()
    if (
        not base
        or "/" in base
        or "\\" in base
        or base.startswith(".")
        or not base.lower().endswith(".md")
        or len(base) > 80
    ):
        raise ProjectError("doc name must be a bare .md file name", "invalid_doc_name", 400)
    return base


def _stamp(now: float) -> str:
    """Sortable filename stamp for a snapshot (UTC, second + ms granularity).

    UTC and fixed-width so lexical order IS chronological order regardless of
    the operator's locale or timezone; the milliseconds separate autosave
    records written within one second (the store has no clock to make that
    collision impossible, so the filename carries the tie-break).
    """
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime(now)) + f"-{int(now % 1 * 1000):03d}"


def _snapshot_path(base: Path, doc_base: str, now: float) -> Path:
    """A collision-free snapshot path under ``base/<doc name>/``.

    One directory per doc; an existing stamp gets ``-1``, ``-2`` appended
    (retry until free) so two writes landing in the same millisecond both
    survive, and the suffix sorts after the bare stamp, keeping the tie
    order stable.
    """
    doc_dir = base / doc_base
    doc_dir.mkdir(parents=True, exist_ok=True)
    stem = _stamp(now)
    path = doc_dir / f"{stem}.md"
    n = 1
    while path.exists():
        path = doc_dir / f"{stem}-{n}.md"
        n += 1
    return path


def _read_snapshots(base: Path, doc_base: str) -> list[dict[str, Any]]:
    """Snapshots of one doc as ``{name, content, ts}``, oldest first.

    ``ts`` is the file's mtime — the wall-clock truth even when a collision
    suffix pushed the filename's stamp a step behind. Reads tolerate a half-
    written file by skipping it: a history list missing one entry beats a
    500 on the whole panel.
    """
    doc_dir = base / doc_base
    if not doc_dir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(doc_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".md":
            continue
        try:
            content = path.read_text(encoding="utf-8")
            ts = path.stat().st_mtime
        except OSError:
            continue
        out.append({"name": path.name, "content": content, "ts": ts})
    out.sort(key=lambda s: s["ts"])
    return out


def _unified_diff(old: str, new: str) -> str:
    """Unified diff of two whole-document contents (possibly empty)."""
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile="previous",
            tofile="current",
        )
    )


def save_doc(project_id: str, name: str, content: str) -> dict[str, str]:
    """Commit one doc: promote the draft into ``docs/`` and snapshot it.

    The semantics the editor's Save button carries. A current draft, if any,
    is promoted into ``docs/`` instead of being overwritten by the request
    body — the draft is the autosaved truth of the buffer, and a commit whose
    request raced a later keystroke must not roll the buffer back; with no
    draft (an API caller, a pre-autosave client) the request body is what
    gets written. The committed content then lands in ``versions/`` as a
    full-text snapshot: the trail lists every commit, row N diffs against
    row N-1, and the first row reads as a whole-document addition. Finally
    the doc's whole drafts layer — the current file and its per-record trail
    — is deleted: since the last commit, nothing is uncommitted.
    """
    base = _checked_doc_name(project_id, name)
    project_dir = projects_root() / project_id
    docs_dir = project_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    doc_path = docs_dir / base

    draft_path = project_dir / "drafts" / f"{base}.md"
    try:
        draft_content: str | None = draft_path.read_text(encoding="utf-8")
    except OSError:
        draft_content = None
    final = draft_content if draft_content is not None else content

    old_content = ""
    try:
        old_content = doc_path.read_text(encoding="utf-8")
    except OSError:
        pass

    doc_path.write_text(final, encoding="utf-8")

    # Only a real change gets a version row: re-committing identical content
    # would store a second snapshot whose diff-vs-predecessor is empty, which
    # is a row the panel cannot show and the trail does not need (the same
    # dedup the draft record applies).
    if final != old_content:
        _snapshot_path(project_dir / "versions", base, time.time()).write_text(
            final, encoding="utf-8"
        )

    shutil.rmtree(project_dir / "drafts" / base, ignore_errors=True)
    try:
        draft_path.unlink(missing_ok=True)
    except OSError:
        pass
    return {"name": base, "content": final}


def save_draft(project_id: str, name: str, content: str) -> dict[str, Any]:
    """Autosave the buffer: overwrite the current draft, append a record.

    Two files answer two questions. ``drafts/<doc>.md`` is what a reopen
    restores — always the latest word, so the autosave overwrites it. The
    timestamped record under ``drafts/<doc-stem>/`` is the change history
    since the last commit, and it deduplicates: content identical to the
    newest record writes no file (the autosave fires on a ~2s debounce, and
    a caret that keeps moving would otherwise fill the disk with the same
    buffer — the footer count must mean "the text changed", not "a tick
    passed"). A first draft for a doc is always recorded, even when it
    equals the committed content, so the panel has a row to show.
    """
    base = _checked_doc_name(project_id, name)
    drafts_dir = projects_root() / project_id / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    current = drafts_dir / f"{base}.md"
    current.write_text(content, encoding="utf-8")

    records = _read_snapshots(drafts_dir, base)
    deduped = bool(records) and records[-1]["content"] == content
    record: dict[str, Any] | None = None
    if not deduped:
        path = _snapshot_path(drafts_dir, base, time.time())
        path.write_text(content, encoding="utf-8")
        record = {"name": path.name, "content": content, "ts": path.stat().st_mtime}
    return {"name": base, "content": content, "deduped": deduped, "record": record}


def list_draft_versions(project_id: str, name: str) -> list[dict[str, Any]]:
    """Draft records since the last commit, newest first.

    The panel wants the most recent on top, so the store's oldest-first read
    is reversed at the boundary; the content rides along because the diff
    view needs the old buffer and a second round trip per row would be a
    fetch storm for a three-row panel.
    """
    base = _checked_doc_name(project_id, name)
    drafts_dir = projects_root() / project_id / "drafts"
    return list(reversed(_read_snapshots(drafts_dir, base)))


def list_versions(project_id: str, name: str) -> list[dict[str, Any]]:
    """Committed versions with the diff against their predecessor.

    Row N's diff is version N vs version N-1 (empty baseline for the first,
    which reads as a whole-document addition — the honest shape, not an
    error). Oldest first matches commit order; the UI displays the list as
    given, newest version last.
    """
    base = _checked_doc_name(project_id, name)
    versions_dir = projects_root() / project_id / "versions"
    snapshots = _read_snapshots(versions_dir, base)
    out: list[dict[str, Any]] = []
    previous = ""
    for snap in snapshots:
        out.append(
            {
                "name": snap["name"],
                "ts": snap["ts"],
                "size": len(snap["content"]),
                "diff": _unified_diff(previous, snap["content"]),
            }
        )
        previous = snap["content"]
    return out


def create_project(name: str, description: str) -> dict[str, Any]:
    """Create a project directory with its identity file and seed docs.

    Id uniqueness: the timestamp suffix is what separates same-name projects
    (an id that collides raises the OS error, which the caller surfaces as a
    retryable 503 — the honest reading of "I just made that path" is a retry,
    not a data loss).
    """
    name = name.strip()
    if not name:
        raise ProjectError("project name is required", "name_required", 400)
    if len(name) > MAX_NAME_LEN:
        raise ProjectError("project name is too long", "name_too_long", 400)
    description = description.strip()[:MAX_DESCRIPTION_LEN]
    fragment = _slug(name)
    suffix = time.strftime("%y%m%d-%H%M%S")
    project_id = f"{fragment + '-' if fragment else ''}p{suffix}"
    root = projects_root()
    root.mkdir(parents=True, exist_ok=True)
    project_dir = root / project_id
    docs_dir = project_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=False)
    try:
        for doc_name, template in SEED_DOCS.items():
            (docs_dir / doc_name).write_text(
                template.replace("{name}", name).replace("{description}", description),
                encoding="utf-8",
            )
        record = {
            "id": project_id,
            "name": name,
            "description": description,
            "createdAt": time.time(),
        }
        _project_json_path(project_dir).write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError:
        # Roll the half-built directory back so the failed create leaves no
        # directory for the list to trip over (it would not appear anyway —
        # the identity file is what makes a project — but leaving litter in
        # the data home over a retryable failure is its own mess).
        import shutil

        shutil.rmtree(project_dir, ignore_errors=True)
        raise
    return record


#: Documents every new project starts with. ``{name}`` / ``{description}``
#: interpolate from the create request; keep the shape matching what the
#: workbench's Docs tool lists (requirements / workflow / ui-spec).
SEED_DOCS: dict[str, str] = {
    "requirements.md": (
        "# {name} 需求说明\n\n"
        "> {description}\n\n"
        "## 目标\n\n"
        "- （待补充：这个项目要解决什么问题）\n\n"
        "## 范围\n\n"
        "- 包含：\n"
        "- 不包含：\n\n"
        "## 关键流程\n\n"
        "1. （待补充：主要业务流程与状态流转）\n\n"
        "## 验收标准\n\n"
        "- [ ] （待补充）\n"
    ),
    "workflow.md": (
        "# {name} 流程设计\n\n"
        "## 阶段划分\n\n"
        "| 阶段 | 负责人 | 产出 |\n"
        "| --- | --- | --- |\n"
        "| 需求确认 |  | requirements.md |\n\n"
        "## 流转规则\n\n"
        "- （待补充：各阶段之间的进入/退出条件）\n"
    ),
    "ui-spec.md": (
        "# {name} 界面设计\n\n"
        "## 页面清单\n\n"
        "- （待补充：页面与入口）\n\n"
        "## 交互说明\n\n"
        "- （待补充：关键交互与状态）\n"
    ),
}
