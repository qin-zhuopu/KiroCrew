"""需求页（RFC rfc-ai-studio-req-flow §9.4）：读工作区 docs/需求图谱/*.json，调需求标准 v34 命令出文档和判定。

列页、取一页（图谱 + 渲染出的 markdown + 判定），判定全部通过外部
``jc fe reqdoc`` 子进程拿结果，因此和 ``projects.py``/``graph.py`` 一样是同步
纯文件 I/O + 子进程，routes 用 ``asyncio.to_thread`` 调。

第 4 步（ACP-2104）在这层加了两件**写**事，都只往工作区的 ``.ai-studio/`` 追加账本，
**从不改图谱**（图谱是助手的产物，事实源只有一条写入路径 = 会话写文件）：

* ``direct_edit``：把用户在网页上改的文档算成 diff 记账（RFC §5 ``DocDirectEdited``）。
  它比的是**文档**的 hash（``docHash``），因为直改的并发对象是文档不是图谱；
  记账后由 routes 把 diff 发给需求会话，落回图谱是助手的事。
* ``start``：复判通过后记一条开工请求（RFC §6 R2）。它比的是**图谱**的 hash，
  因为「这页能不能开发」说的是图谱，前端显示的判定可能已经过期。

命令约定（实测 2026-10-08，``jc fe reqdoc --help``）：

* ``check <图谱>`` 永远回 JSON 信封 ``{"success":..,"data":{..}}``；不合格也是
  ``success:true`` + ``data.verdict="不齐"`` + ``data.errors``，判定是数据不是错误。
* ``render <图谱>`` 只在「全齐 / 可以开工但有已知缺口」时出文档；不齐时是
  ``{"success":false,"errorType":"BusinessError",..}`` 退出码 20 —— 这一种本页
  把 markdown 置 None，不抛错（图谱本身仍然是可读的，判定条要显示它）。
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REQ_DIR = "docs/需求图谱"
DEFAULT_CMD = "jc fe reqdoc"
VERDICTS = ("不齐", "可以开工但有已知缺口", "全齐")

#: 直改与开工请求两本追加账本（RFC §9.4：追加写、一行一条、不进 Git）。放在工作区
#: 的 ``.ai-studio/`` 下，和 ``devserver`` 的状态文件同一目录。
DIRECT_EDITS_FILE = ".ai-studio/direct-edits.jsonl"
START_REQUESTS_FILE = ".ai-studio/start-requests.jsonl"

#: One subprocess call's ceiling. ``jc`` loads a node CLI and reads the frame
#: repo, so a healthy call is ~1s; this only exists to stop a wedged child from
#: holding an aiohttp worker thread.
_CMD_TIMEOUT_S = 60


class RequirementError(Exception):
    """A refused requirement-page read, with the HTTP status the route maps.

    ``details`` exists for the one refusal whose answer IS data: 422 ``not_ready``
    carries the verdict and the gap list (RFC §10 验收 11), which the route merges
    into the error body so the frontend redraws the bar without a second read.
    """

    def __init__(
        self, message: str, code: str, status: int, details: Optional[dict[str, Any]] = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.details: dict[str, Any] = dict(details or {})


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


# ---------------------------------------------------------------------------
# 直改与开工请求（第 4 步，ACP-2104）：两本追加账本
# ---------------------------------------------------------------------------


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    """追加一行 JSON（父目录不存在就建）。

    写坏（磁盘满、目录被占）就原样抛 OSError，由 routes 报 503：一条没记上的直改
    等于用户的改动凭空消失，绝不能装成成功。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读一本账本。文件不存在 = 还没发生过（空列表）；单行坏了跳过，不牵连同文件里
    其余的记录（追加写没有格式保证，崩在读上是把小故障放大成整页打不开）。"""
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


#: ``jc fe reqdoc render`` 在每份文档上盖一个 ``生成时间：<ISO>``
#: （``reqstd-v34/render.js`` 的 ``generatedAt``，CLI 没有关掉它的开关），所以同一张
#: 图谱两次渲染出来的文本不一样。实测 2026-10-09 真跑时它让 ``docHash`` 每 5 秒换
#: 一次值 —— 于是〔保存〕永远 409，直改功能一次都成功不了。
#: 只吃「生成时间：<ISO 时间戳>」这一段。不写成 ``[^\n]*``：需求文档里真的可能
#: 出现「生成时间」这四个字（某个表的列就叫生成时间，规则里也可能写「生成时间：
#: 系统自动填」），那种是需求内容，删掉它等于把用户改的东西从底稿里抹掉。
_STAMP_RE = re.compile(r"生成时间：[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.+\-Z]*")


def stable_doc(markdown: Optional[str]) -> str:
    """去掉渲染时间戳之后的文档正文（``doc_hash``、diff、前端都吃这个）。

    凭据要比的是**需求内容**，不是「这份视图是几点渲染的」。留着那一串有三处连带
    伤害：``docHash`` 每 5 秒换一个值，〔保存〕永远 409；用户没改一个字，diff 里
    也会有一条「生成时间」的改动发给需求会话（助手会照着它去改图谱，而图谱里没有
    这一行）；前端拿输入缓冲和新读到的正文比「有没有未保存改动」，时间戳会让每次
    轮询都判定成有改动。幂等：再来一次不会多删。
    """
    return _STAMP_RE.sub("", markdown or "")


def doc_hash(markdown: Optional[str]) -> str:
    """sha256(去时间戳后的文档 utf-8 字节) 前 16 位十六进制；None（图谱不合格、没
    文档）按空串算。

    和 ``graph_hash`` 同算法，区别只在喂什么：那个是文件字节（图谱），这个是渲染
    出来的文本。文本本身每渲染一次都会变一次（见 ``_STAMP_RE``），所以先过
    ``stable_doc`` —— 去掉那一行之后它才是稳定的，才够格当乐观并发控制的凭据。
    """
    return hashlib.sha256(stable_doc(markdown).encode("utf-8")).hexdigest()[:16]


def _as_lines(text: str) -> list[str]:
    """切成「带行尾」的行，且**保证最后一行有行尾**。

    ``splitlines(True)`` 对没有结尾换行的文本会留下裸的最后一行，而 diff 的行是拼接
    出来的：旧文档的最后一行没有 ``\\n`` 时，它会在输出里和新增的第一行**粘成一行**
    （``-旧末行+新末行``），人读不出那是两处改动。补上换行只多一个空 context 行，
    换来的是 diff 永远按行对齐。
    """
    lines = text.splitlines(True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    return lines


def _unified_diff(old: str, new: str) -> str:
    """unified diff（旧 → 新，上下文 2 行）。``lineterm="\\n"`` 是给 ``---/+++`` 两行
    补分隔符（它们不带行尾），正文行的行尾来自 ``_as_lines``。"""
    return "".join(
        difflib.unified_diff(
            _as_lines(old),
            _as_lines(new),
            n=2,
            lineterm="\n",
            fromfile="当前文档",
            tofile="改后文档",
        )
    )


def direct_edit(ws: Path, page: str, base_doc_hash: str, markdown: str) -> dict[str, Any]:
    """用户在网页上直接改了需求文档：比对 → 算 diff → 记账（RFC §5 DocDirectEdited）。

    本函数**不改图谱也不改任何文件**（除了追加自己的账本）：文档是图谱的视图，改视图
    不等于改需求，落回图谱是写需求助手的活（routes 把返回的 diff 发进需求会话）。

    三个出口：
      * 当前文档的 hash 不等于 ``base_doc_hash`` → 409。编辑器里躺着的是旧视图，
        在它上面保存会把别人（通常是助手刚落回的那次）的改动覆盖掉。
      * diff 为空 → ``{"changed": False}`` 且不记账：没改动就没有待落回的东西，
        记一条空的会把判定条永久钉在「改动待落回需求」上。
      * 否则追加一行 + ``{"changed": True, "diff": …, "pending": True}``。
    """
    doc = get_page(ws, page)
    current = doc_hash(doc["markdown"])
    if current != base_doc_hash:
        raise RequirementError("文档已被别人改过，请刷新", "doc_changed", 409)
    # 两边都过 stable_doc 再算 diff：``doc["markdown"]`` 已经去过时间戳，但 ``markdown``
    # 是前端传来的，万一它把整份文档重渲染了一遍（带上自己的时间戳），不去掉就会
    # 把「生成时间」当成用户的改动发给会话。幂等，重复过没有副作用。
    diff = _unified_diff(stable_doc(doc["markdown"]), stable_doc(markdown))
    if not diff:
        return {"changed": False}
    row = {"at": _utc_now(), "page": page, "baseDocHash": base_doc_hash, "diff": diff}
    _append_jsonl(ws / DIRECT_EDITS_FILE, row)
    return {"changed": True, "diff": diff, "pending": True}


def start(ws: Path, page: str, graph_hash_value: str) -> dict[str, Any]:
    """〔开始开发〕的复判 + 记开工请求（RFC §6 R2、§9.4）。

    不信前端：判定在这里**当场重跑一次**（``get_page`` 里就是那两条 reqdoc 命令），
    前端的判定是 5 秒前读的，而「这页能不能开工」必须以点下按钮那一刻的图谱为准。
    """
    doc = get_page(ws, page)
    current = str(doc["graphHash"])
    if current != graph_hash_value:
        raise RequirementError("需求刚刚变了", "graph_changed", 409)
    verdict = str(doc["verdict"])
    if verdict == VERDICTS[0]:
        err = RequirementError("需求不齐", "not_ready", 422)
        # 判定与缺口一起带给前端（RFC §10 验收 11：422 要附 verdict、missing），
        # 前端据此重画判定条，不用为这几个字再跑一次请求
        err.details = {"verdict": verdict, "missing": doc["missing"]}
        raise err
    row = {"at": _utc_now(), "page": page, "graphHash": current, "verdict": verdict}
    _append_jsonl(ws / START_REQUESTS_FILE, row)
    return {"ok": True, "page": page, "graphHash": current, "verdict": verdict}


def _parse_iso(value: Any) -> float:
    """把写进去的 UTC ISO 串读回成 epoch 秒；读不懂给 0（当最早）。"""
    if not isinstance(value, str) or not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _last_row(rows: list[dict[str, Any]], at_key: str) -> dict[str, Any] | None:
    """``at`` 最大的那一条。记账是 JSONL 追加，但外部进程也可能改过这文件，所以
    「最后」按时间戳算而不是按行序（同值时取靠后那条，仍是后写的）。"""
    best: dict[str, Any] | None = None
    best_at = 0.0
    for row in rows:
        at = _parse_iso(row.get(at_key))
        if best is None or at >= best_at:
            best, best_at = row, at
    return best


def _edit_pending(ws: Path, page: str, graph_mtime: float) -> bool:
    """**这一页**最后一次直改是否还没落回图谱（RFC §7 B5：落回之前判定条说「改动待落
    回需求」）。

    判据是「直改记录的时间 晚于 图谱文件的 mtime」：助手把改动落回图谱就是重写那个
    json，mtime 一定跳到直改之后，于是这一句自己会好。两个方向都保守 —— 时间戳读不懂
    当 0（判成已落回，宁可不拦），图谱文件刚被 touch（mtime 变新）也会判成已落回。

    必须按 page 过滤：一个工作区四本图谱共用一本直改账，不筛就会在改了「设备分类」
    之后把另外三页一起钉成「改动待落回需求」，并且连带把它们的〔开始开发〕也禁掉。
    没有 ``page`` 字段的旧行归不了属，不参与任何一页的判定（宁可少拦，不误拦到别人
    的页上）。
    """
    rows = [r for r in _read_jsonl(ws / DIRECT_EDITS_FILE) if r.get("page") == page]
    last = _last_row(rows, "at")
    if last is None:
        return False
    return _parse_iso(last.get("at")) > graph_mtime


def _dev_state(ws: Path, page: str, current_hash: str) -> dict[str, Any]:
    """需求页的开发状态（派工单第 2 步的三档）。

    本页最后一条开工请求的 graphHash 还等于当前图谱 → ``started``（已开工，没重改）；
    有记录但 hash 变了 → ``editing`` + ``changedAfterStart``（R3：开工请求作废标记，
    不删记录，界面要能说「需求改了，要重新点开始开发」）；没记录 → ``editing``。
    """
    rows = [r for r in _read_jsonl(ws / START_REQUESTS_FILE) if r.get("page") == page]
    last = _last_row(rows, "at")
    if last is None:
        return {"devState": "editing"}
    if last.get("graphHash") == current_hash:
        return {"devState": "started"}
    return {"devState": "editing", "changedAfterStart": True}


def get_page(ws: Path, page: str) -> dict[str, Any]:
    """一页需求：图谱原文 + 判定（check）+ 文档（render）+ 两个状态位。

    render 因图谱不合格失败时 markdown=None（判定条要显示「不齐」，文档本来就不
    该有）。三个状态位：
      * ``docHash``：当前文档的 hash，直改要拿它当乐观并发凭据；
      * ``pendingEdit``：直改还没落回图谱（判定条显示「改动待落回需求」，B5）；
      * ``devState``：``editing`` / ``started``，外加作废标记 ``changedAfterStart``。
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
        # 去掉渲染时间戳再出去（见 ``_STAMP_RE``）。三个下游都靠它稳定：
        # ``docHash``（乐观并发凭据）、发给会话的 diff、以及前端的「有没有未保存
        # 改动」判定 —— 留着时间戳，用户刚打一个字，下一次 5 秒轮询就会把「你的
        # 未保存修改已保留」点亮，而那其实是渲染器自己改了个日期。
        markdown = stable_doc(md) if isinstance(md, str) else None
    missing = _str_list(check, "missing")
    errors = _str_list(check, "errors")
    verdict = check.get("verdict") if check.get("verdict") in VERDICTS else VERDICTS[0]
    current = graph_hash(path)
    # mtime 在算 hash 的同一批 stat 里取：直改有没有落回，比的就是它
    graph_mtime = path.stat().st_mtime
    state = _dev_state(ws, page, current)
    return {
        "page": page,
        "graph": graph,
        "markdown": markdown,
        "graphHash": current,
        "docHash": doc_hash(markdown),
        "verdict": verdict,
        "errors": errors,
        "missing": missing,
        "tiers": _tiers(check.get("tiers")),
        "pendingEdit": _edit_pending(ws, page, graph_mtime),
        "devState": state["devState"],
        "changedAfterStart": bool(state.get("changedAfterStart", False)),
        "stale": False,
    }
