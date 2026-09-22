"""The AI Studio project store: one directory per project on disk.

Layout (all paths under ``config_dir()``, which honours ``KIROCREW_HOME``)::

    <data home>/ai-studio/projects/<project-id>/
        project.json          # identity: id, name, description, createdAt
        docs/requirements.md  # seeded at creation, edited by the workbench
        docs/workflow.md
        docs/ui-spec.md

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

import json
import re
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


def save_doc(project_id: str, name: str, content: str) -> dict[str, str]:
    """Write one doc file, creating or replacing it.

    ``name`` is constrained to a bare ``*.md`` basename: a stored project id
    already came from ``create`` or the list, but the doc name is free caller
    input, and the one place that keeps it from becoming a traversal is this
    check — reject any path separator, any leading dot, anything that is not
    ``name.md``.
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
    docs_dir = projects_root() / project_id / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / base).write_text(content, encoding="utf-8")
    return {"name": base, "content": content}


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
