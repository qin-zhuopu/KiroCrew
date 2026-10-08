"""需求页（RFC rfc-ai-studio-req-flow §9.4）：读工作区 docs/需求图谱/*.json，调需求标准 v34 命令出文档和判定。

只读层：列页、取一页（图谱 + 渲染出的 markdown + 判定），全部通过外部
``jc fe reqdoc`` 子进程拿结果，因此和 ``projects.py``/``graph.py`` 一样是同步
纯文件 I/O + 子进程，routes 用 ``asyncio.to_thread`` 调。

命令约定（实测 2026-10-08，``jc fe reqdoc --help``）：

* ``check <图谱>`` 永远回 JSON 信封 ``{"success":..,"data":{..}}``；不合格也是
  ``success:true`` + ``data.verdict="不齐"`` + ``data.errors``，判定是数据不是错误。
* ``render <图谱>`` 只在「全齐 / 可以开工但有已知缺口」时出文档；不齐时是
  ``{"success":false,"errorType":"BusinessError",..}`` 退出码 20 —— 这一种本页
  把 markdown 置 None，不抛错（图谱本身仍然是可读的，判定条要显示它）。
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQ_DIR = "docs/需求图谱"
DEFAULT_CMD = "jc fe reqdoc"
VERDICTS = ("不齐", "可以开工但有已知缺口", "全齐")

#: One subprocess call's ceiling. ``jc`` loads a node CLI and reads the frame
#: repo, so a healthy call is ~1s; this only exists to stop a wedged child from
#: holding an aiohttp worker thread.
_CMD_TIMEOUT_S = 60


class RequirementError(Exception):
    """A refused requirement-page read, with the HTTP status the route maps."""

    def __init__(self, message: str, code: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def workspace_dir(project: dict[str, Any], project_path: Path) -> Path:
    """工作区目录：project.json 里有 workspaceDir（绝对路径且存在）就用它，否则用项目目录本身。

    只读一个新字段，不改 ``projects.py`` 的任何行为：需求图谱住在被开发的前端仓
    里（那里才有 docs/需求图谱），而项目目录是 ai-studio 自己的记录目录。
    """
    raw = project.get("workspaceDir")
    if isinstance(raw, str) and raw:
        candidate = Path(raw)
        if candidate.is_absolute() and candidate.is_dir():
            return candidate
    return project_path


def reqdoc_cmd() -> list[str]:
    """环境变量 AI_STUDIO_REQDOC_CMD（shlex 拆分），没设用 DEFAULT_CMD。"""
    raw = os.environ.get("AI_STUDIO_REQDOC_CMD", "").strip()
    if not raw:
        return shlex.split(DEFAULT_CMD)
    parts = shlex.split(raw)
    return parts or shlex.split(DEFAULT_CMD)


def _frame_args() -> list[str]:
    """AI_STUDIO_REQDOC_FRAME 有值时给两条命令都追加 --frame <值>。"""
    frame = os.environ.get("AI_STUDIO_REQDOC_FRAME", "").strip()
    return ["--frame", frame] if frame else []


def _run(args: list[str], timeout: int = _CMD_TIMEOUT_S) -> dict[str, Any]:
    """跑 reqdoc_cmd() + args（外加 --frame 若有），读 stdout 的 JSON 信封返回 data。

    命令不存在 503 / 超时 504 / 信封不是 JSON 或 success!=true 502。唯一放行的
    非 success 情况是「图谱不合格」（BusinessError + 退出码 20）：那是一条判定，
    由调用方按 return_envelope 读原文，不是失败。
    """
    argv = [*reqdoc_cmd(), *args, *_frame_args()]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RequirementError(
            f"requirement command not found: {argv[0]}", "reqdoc_cmd_unavailable", 503
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RequirementError(
            f"requirement command timed out after {timeout}s", "reqdoc_timeout", 504
        ) from exc
    except OSError as exc:
        raise RequirementError(
            f"requirement command could not run: {exc}", "reqdoc_cmd_unavailable", 503
        ) from exc
    try:
        envelope = json.loads(proc.stdout)
    except ValueError as exc:
        raise RequirementError(
            "requirement command answered with no json envelope", "reqdoc_failed", 502
        ) from exc
    if not isinstance(envelope, dict):
        raise RequirementError("bad requirement command envelope", "reqdoc_failed", 502)
    if not envelope.get("success"):
        # 「图谱不合格，没生成文档」是 render 的正常判定（BusinessError/20），
        # 调用方要的是信封原文里的 message，不是 502。
        if _is_graph_unqualified(envelope, proc.returncode):
            return envelope
        raise RequirementError(
            str(envelope.get("message") or "requirement command failed"), "reqdoc_failed", 502
        )
    data = envelope.get("data")
    return data if isinstance(data, dict) else {}


def _is_graph_unqualified(envelope: dict[str, Any], returncode: int) -> bool:
    return envelope.get("errorType") == "BusinessError" and returncode == 20


def graph_hash(path: Path) -> str:
    """sha256(文件字节) 前 16 位十六进制。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _page_file(ws: Path, page: str) -> Path:
    return ws / REQ_DIR / f"{page}.json"


def _page_name_ok(page: str) -> bool:
    """页名即文件名：不许带路径分隔符、不许 ``..``，且必须以字母/数字/中文开头。

    两个 GET 的 ``{page}`` 直接来自 URL，这里不守住就是任意路径读取。
    """
    if not page or "/" in page or "\\" in page or ".." in page:
        return False
    first = page[0]
    if first.isascii():
        return first.isalnum()
    # 非 ASCII：只放行中日韩汉字区间（真页名就是中文），其余（标点、代理对、
    # 空白）一律拒。
    return "一" <= first <= "鿿"


def _str_list(src: dict[str, Any], key: str) -> list[str]:
    """check 的 errors/missing 原样是字符串数组，但 CLI 是外部进程：字段缺失或
    类型不对都不能让读层崩，退化成空数组（判定本身仍按 verdict 走）。"""
    raw = src.get(key)
    return [str(x) for x in raw] if isinstance(raw, list) else []


def _iso_utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def list_pages(ws: Path) -> list[dict[str, Any]]:
    """列 ws/REQ_DIR/*.json（按文件名排序），每个跑一次 check 出判定。

    目录不存在 → ``[]``（新项目还没写需求图谱，这是正常空态，不是错误）。
    """
    req_dir = ws / REQ_DIR
    if not req_dir.is_dir():
        return []
    pages: list[dict[str, Any]] = []
    for path in sorted(req_dir.glob("*.json")):
        if not path.is_file():
            continue
        check = _run(["check", str(path)])
        missing = _str_list(check, "missing")
        errors = _str_list(check, "errors")
        verdict = check.get("verdict") if check.get("verdict") in VERDICTS else VERDICTS[0]
        pages.append(
            {
                "page": path.stem,
                "graphHash": graph_hash(path),
                "verdict": verdict,
                "missingCount": len(missing) + len(errors),
                "updatedAt": _iso_utc(path.stat().st_mtime),
            }
        )
    return pages


def _tiers(raw: Any) -> dict[str, list[str]]:
    src = raw if isinstance(raw, dict) else {}
    out: dict[str, list[str]] = {}
    for key in ("api", "ui", "parts"):
        items = src.get(key)
        out[key] = [str(x) for x in items] if isinstance(items, list) else []
    return out


def get_page(ws: Path, page: str) -> dict[str, Any]:
    """一页需求：图谱原文 + 判定（check）+ 文档（render）。

    render 因图谱不合格失败时 markdown=None（判定条要显示「不齐」，文档本来就不
    该有）。devState/stale 是本步的常量占位：直改与开发状态是第 3、4 步。
    """
    if not _page_name_ok(page):
        raise RequirementError("page not found", "page_not_found", 404)
    path = _page_file(ws, page)
    if not path.is_file():
        raise RequirementError("page not found", "page_not_found", 404)
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RequirementError(f"graph unreadable: {exc}", "graph_invalid_json", 422) from exc
    try:
        graph = json.loads(raw_text)
    except ValueError as exc:
        raise RequirementError(f"graph json unreadable: {exc}", "graph_invalid_json", 422) from exc
    check = _run(["check", str(path)])
    markdown: str | None = None
    rendered = _run(["render", str(path)])
    if not _is_graph_unqualified(rendered, 20):
        md = rendered.get("markdown")
        markdown = md if isinstance(md, str) else None
    missing = _str_list(check, "missing")
    errors = _str_list(check, "errors")
    verdict = check.get("verdict") if check.get("verdict") in VERDICTS else VERDICTS[0]
    return {
        "page": page,
        "graph": graph,
        "markdown": markdown,
        "graphHash": graph_hash(path),
        "verdict": verdict,
        "errors": errors,
        "missing": missing,
        "tiers": _tiers(check.get("tiers")),
        "devState": "editing",
        "stale": False,
    }
