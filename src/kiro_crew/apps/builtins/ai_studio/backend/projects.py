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
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable

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


def slug(name: str) -> str:
    """Public read of :func:`_slug` for callers outside this module that need
    the same filesystem-safe fragment (the publish URL's app segment)."""
    return _slug(name)


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
    """Commit one doc: write the buffer, snapshot it, clear its drafts.

    The semantics the editor's Commit button carries. The request body IS
    the buffer at click time — newer than or equal to anything the ~2s
    autosave debounce managed to persist — so it is authoritative and the
    draft file is not consulted for content. The committed content lands in
    ``versions/`` as a full-text snapshot (only when it actually differs from
    what ``docs/`` held: a same-content re-commit would store a row whose
    diff-vs-predecessor is empty, the same dedup the draft record applies),
    so the trail lists every change, row N diffs against row N-1, and the
    first row reads as a whole-document addition. Finally the doc's whole
    drafts layer — the current file and its per-record trail — is deleted:
    since the last commit, nothing is uncommitted.
    """
    base = _checked_doc_name(project_id, name)
    project_dir = projects_root() / project_id
    docs_dir = project_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    doc_path = docs_dir / base

    old_content = ""
    try:
        old_content = doc_path.read_text(encoding="utf-8")
    except OSError:
        pass

    doc_path.write_text(content, encoding="utf-8")

    if content != old_content:
        _snapshot_path(project_dir / "versions", base, time.time()).write_text(
            content, encoding="utf-8"
        )

    shutil.rmtree(project_dir / "drafts" / base, ignore_errors=True)
    try:
        (project_dir / "drafts" / f"{base}.md").unlink(missing_ok=True)
    except OSError:
        pass
    return {"name": base, "content": content}


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


def list_draft_docs(project_id: str) -> list[dict[str, Any]]:
    """Every doc with a current draft: ``{name, content, changed}``.

    The project-level commit reads this to know which docs are uncommitted
    (the drafts layer is the truth: the autosave persists even after the tab
    closes, so the top bar cannot derive the answer from open editors alone).
    ``changed`` compares the draft against the committed doc — a draft saved
    with content identical to the last commit still counts as a draft (the
    project-level commit clears it), but the summary should not show it as a
    pending change. File-name convention from ``save_draft``: the current
    draft is ``<doc>.md.md``, so a bare ``<doc>.md`` in the drafts directory
    is the per-record history directory, never a current draft.
    """
    project = get_project(project_id)
    if project is None:
        return []
    drafts_dir = projects_root() / project_id / "drafts"
    if not drafts_dir.is_dir():
        return []
    docs_dir = projects_root() / project_id / "docs"
    out: list[dict[str, Any]] = []
    for path in sorted(drafts_dir.iterdir()):
        if not path.is_file() or not path.name.endswith(".md.md"):
            continue
        doc_name = path.name[: -len(".md")]
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        committed = ""
        try:
            committed = (docs_dir / doc_name).read_text(encoding="utf-8")
        except OSError:
            pass
        out.append({"name": doc_name, "content": content, "changed": content != committed})
    return out


def list_draft_versions(project_id: str, name: str) -> list[dict[str, Any]]:
    """Draft records since the last commit, newest first.

    The panel wants the most recent on top, so the store's oldest-first read
    is reversed at the boundary; the content rides along because the diff
    view needs the old buffer and a second round trip per row would be a
    fetch storm for a three-row panel. ``time`` is epoch seconds (the key
    name the editor's StudioDraftVersion type reads).
    """
    base = _checked_doc_name(project_id, name)
    drafts_dir = projects_root() / project_id / "drafts"
    return [
        {"name": r["name"], "content": r["content"], "time": r["ts"]}
        for r in reversed(_read_snapshots(drafts_dir, base))
    ]


def list_versions(project_id: str, name: str) -> list[dict[str, Any]]:
    """Committed versions with the diff against their predecessor.

    Each row's diff is that version vs the one committed before it (empty
    baseline for the first, which reads as a whole-document addition — the
    honest shape, not an error). Newest first, matching the draft-history
    list and what the editor's version panel renders top-down; ``time`` is
    epoch seconds (the editor keys and labels rows by it, and its commit
    order is the display order).
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
                "time": snap["ts"],
                "size": len(snap["content"]),
                "diff": _unified_diff(previous, snap["content"]),
            }
        )
        previous = snap["content"]
    return list(reversed(out))


def create_project(
    name: str, description: str, code: str | None = None, template: str | None = None
) -> dict[str, Any]:
    """Create a project directory with its identity file and seed docs.

    Id uniqueness: the timestamp suffix is what separates same-name projects
    (an id that collides raises the OS error, which the caller surfaces as a
    retryable 503 — the honest reading of "I just made that path" is a retry,
    not a data loss).

    A ``code`` makes the project a WORKSPACE (ACP-2085, RFC §9.1): the code
    becomes the id (the repo name and the dev URL are both built from it, so two
    projects sharing one code would be two owners fighting over one directory —
    hence the 409 rather than a suffix), the record starts at
    ``status: "creating"`` with the four derive steps pending, and NO seed docs
    are written: a workspace's documents come from the template repo it is
    cloned from, so three hand-written files in front of it would be documents
    the clone has to overwrite. Without a ``code`` nothing here changes — the id
    keeps its timestamp shape and the three seed docs keep landing.
    """
    name = name.strip()
    if not name:
        raise ProjectError("project name is required", "name_required", 400)
    if len(name) > MAX_NAME_LEN:
        raise ProjectError("project name is too long", "name_too_long", 400)
    description = description.strip()[:MAX_DESCRIPTION_LEN]
    root = projects_root()
    root.mkdir(parents=True, exist_ok=True)

    if code is not None:
        from kiro_crew.apps.builtins.ai_studio.backend import workspace

        code = workspace.check_code(code)
        if any(p.get("code") == code for p in list_projects()):
            raise ProjectError("代号已被占用", "code_taken", 409)
        project_id = code
    else:
        fragment = _slug(name)
        suffix = time.strftime("%y%m%d-%H%M%S")
        project_id = f"{fragment + '-' if fragment else ''}p{suffix}"

    project_dir = root / project_id
    try:
        project_dir.mkdir(parents=True, exist_ok=False)
        if code is None:
            docs_dir = project_dir / "docs"
            docs_dir.mkdir(parents=True, exist_ok=True)
            for doc_name, seed in SEED_DOCS.items():
                (docs_dir / doc_name).write_text(
                    seed.replace("{name}", name).replace("{description}", description),
                    encoding="utf-8",
                )
        record: dict[str, Any] = {
            "id": project_id,
            "name": name,
            "description": description,
            "createdAt": time.time(),
        }
        if code is not None:
            record.update(_workspace_fields(code, template))
        _project_json_path(project_dir).write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError:
        # Roll the half-built directory back so the failed create leaves no
        # directory for the list to trip over (it would not appear anyway —
        # the identity file is what makes a project — but leaving litter in
        # the data home over a retryable failure is its own mess).
        shutil.rmtree(project_dir, ignore_errors=True)
        raise
    return record


def _workspace_fields(code: str, template: str | None = None) -> dict[str, Any]:
    """The fields that turn a plain project record into a workspace record.

    Lives here (and reads :mod:`workspace` lazily, the same way
    :func:`projects_root` reads ``config_dir``) because the two modules need
    each other: the job writes through :func:`update_project`, and the create
    path needs the step names — a top-level ``import workspace`` would be a
    cycle. One function so a create and a later read cannot disagree about what
    "nothing has run yet" looks like.
    """
    from kiro_crew.apps.builtins.ai_studio.backend import workspace

    return {
        "code": code,
        "template": template or workspace.template_url(),
        "status": workspace.STATUS_CREATING,
        "failedStep": None,
        "message": None,
        "workspaceDir": None,
        "repoUrl": None,
        "steps": [
            {"name": name, "state": workspace.STEP_PENDING, "message": None}
            for name in workspace.STEPS
        ],
    }


#: 回收站目录名。删除是**移动**不是删除，所以一个项目坏不了、也还能找回。
TRASH_DIR = ".trash"


def _trash_name(project_id: str, now: float) -> str:
    """回收站里的那一个目录名：``<代号>-<时间戳>``。

    时间戳是 UTC 定宽的，所以同一代号删两次落两个目录（第二次不会覆盖第一次，
    「可找回」才有意义）。项目名是中文的，进目录名会变成八进制乱码，所以用 id
    —— 工作区的 id 就是代号，本来就是 ASCII。
    """
    return f"{project_id}-{_stamp(now)}"


def _move_into_trash(src: Path, trash_root: Path, name: str) -> Path:
    """把 ``src`` 移进 ``trash_root/<name>``，返回落地路径。

    先建回收站目录再 ``rename``：同一文件系统上是原子的（不存在「半个项目」），
    跨设备会 ``EXDEV`` 报错而不是静默复制一半 —— 那比慢一点严重得多。
    """
    trash_root.mkdir(parents=True, exist_ok=True)
    dest = trash_root / name
    n = 1
    while dest.exists():
        dest = trash_root / f"{name}-{n}"
        n += 1
    src.rename(dest)
    return dest


def delete_project(
    project_id: str,
    *,
    now: float | None = None,
    stop_servers: Callable[[dict[str, Any], Path], None] | None = None,
) -> dict[str, Any]:
    """删除一个项目：工作区目录与项目记录目录都**移到回收站**，返回
    ``{"deleted": True, "trash": <工作区落地路径>}``。

    三步的顺序是契约（派工单 ACP-2206）：先停服务器，再看开发在不在跑，最后才动
    目录。反过来就是「进程还在写一个已经被移走的目录」，而 vite 的 pid 与网关卡
    到的域名会跟着目录一起进回收站，外面再也清不掉（``devserver.stop`` 的判据就是
    为这种泄漏写的）。

    开发在跑（``.ai-studio/dev-run.json`` 的 ``runState == "running"``）时 409：
    这一条是**读文件的判定**，不是 ``_loop_alive()`` —— 路由层的 ``DevRun`` 缓存在
    这里用不上，而且网关重启后「文件写着 running」正是孤儿，``DevRun.get`` 会把它
    判成失败，但删除这条路上没人去读那个看板，所以按文件如实拦下让人先去看一眼。

    远端个人仓**不删**（RFC 定的）：本地目录进回收站是廉价可逆的，删远端是不可逆
    的，两者不该是同一个按钮。

    ``stop_servers`` 是外部世界的注入点（真版见路由）：单测因此不碰进程、不碰网关。
    """
    record = get_project(project_id)
    if record is None:
        raise ProjectError("project not found", "project_not_found", 404)
    project_dir = projects_root() / project_id
    # 与读侧同一个谓词：``requirements.workspace_dir`` 决定 .ai-studio/ 在哪，删除
    # 若自己另算一套，「记录目录里有 dev-run.json 而工作区里没有」这种现场就会一边
    # 判在跑一边判没在跑。
    from kiro_crew.apps.builtins.ai_studio.backend import requirements

    ws = requirements.workspace_dir(record, project_dir)

    if stop_servers is not None:
        stop_servers(record, ws)

    if _dev_run_state(ws) == "running":
        raise ProjectError("开发进行中，先等它结束", "dev_running", 409)

    stamp = time.time() if now is None else now
    name = _trash_name(project_id, stamp)
    # 一个普通项目（没 workspaceDir）的 ``ws`` 就是记录目录本身，工作区也可能被记在
    # 记录目录里面。这两种情况下**只移一次**：移外层时内层跟着走，再移第二次会因为
    # 源目录已经不在而抛 FileNotFoundError —— 列表页每张卡片都有删除按钮，老项目
    # 就成了 503。
    inner = ws == project_dir or project_dir in ws.parents
    # 先移工作区，后移记录：反过来一旦工作区没移成，项目就从列表里消失了，那份代码
    # 变成没有记录的孤儿，再点删除只会 404。像现在这样坏，记录还在、看板还在，删除
    # 可以重来一次（工作区不在了就跳过，把记录移走了结）。
    result: dict[str, Any] = {"deleted": True}
    if not inner and ws.is_dir():
        result["trash"] = str(_move_into_trash(ws, _workspaces_root() / TRASH_DIR, name))
    record_trash = _move_into_trash(project_dir, projects_root() / TRASH_DIR, name)
    if "trash" in result:
        result["recordTrash"] = str(record_trash)
    else:
        # 没挪工作区（普通项目）：回收站里就一处，`trash` 报它就是全部答案
        result["trash"] = str(record_trash)
    return result


def _workspaces_root() -> Path:
    """工作区的根（环境变量 ``AI_STUDIO_WORKSPACES_ROOT``）。

    懒导入：:mod:`workspace` 顶层 import 本模块（派生要写记录），模块级 import 就是
    循环 —— 和 :func:`_workspace_fields` 读它是同一个理由。
    """
    from kiro_crew.apps.builtins.ai_studio.backend import workspace

    return workspace.workspaces_root()


def _dev_run_state(ws: Path) -> str:
    """工作区 ``.ai-studio/dev-run.json`` 里的 ``runState``，读不到就是空串。

    自己读而不是调 ``devdag.DevRun.get``：后者带孤儿改判逻辑，会把 running 改成
    failed 落盘 —— 删除一条路径不该顺手改写别人的开发状态。这里只要一个事实。
    """
    try:
        raw = json.loads((ws / ".ai-studio" / "dev-run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(raw, dict):
        return ""
    state = raw.get("runState")
    return state if isinstance(state, str) else ""


def update_project(project_id: str, **fields: Any) -> dict[str, Any]:
    """Merge ``fields`` into one project record and write it back atomically.

    The workspace job's only writer: it rewrites the record several times while
    the dashboard polls the same file every 2 seconds, so the write is
    temp-file + ``os.replace`` — a reader sees either the whole old record or the
    whole new one. A torn write would read back as "not a project"
    (:func:`_read_project` returns None on a ValueError), which at the route
    layer is a 404 on a workspace that is very much alive.

    ``fields`` is not a whitelist and this is not a security boundary: the
    callers are this package's own background job and handlers, and reaching a
    key takes a code change, not caller text.
    """
    project_dir = projects_root() / project_id
    record = _read_project(project_dir)
    if record is None:
        raise ProjectError("project not found", "project_not_found", 404)
    record.update(fields)
    target = _project_json_path(project_dir)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)
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
