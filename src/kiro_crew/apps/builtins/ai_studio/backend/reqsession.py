"""需求会话（RFC rfc-ai-studio-req-flow §9.3）：一个工作区一个写需求助手会话。

以前左栏只是拿 `ai-studio-<id>` 建一个普通聊天 slot：会话不在工作区目录里跑，
也没告诉任何人它是写需求的。这个文件把它变成 RFC 说的「需求会话」——slot 的
`project` 指向工作区目录（`chat_runner` 用它当 CLI 的 cwd），标题写「需求：〈项目名〉」，
第一次创建时把首条提示语发给会话，让它去读工作区里的 `.claude/agents/requirement-writer.md`
并按它工作。

开会话的写法照抄 Spec Builder（`apps/builtins/spec_builder/backend/runtime.py`
的 `_ensure_worker_slot` 与 `_dispatch_turn`），不复用它的 `.kiro/specs` 存储和批准流。

为什么没有 agent 字段：`§9.3` 里「设 agent = requirement-writer」靠的是工作区里那份
`.claude/settings.local.json`（V1 实测边界 1），而 ACP-2085 的调研结论是**工作区里不许有
那份文件**——Claude ACP 适配器一见到它就整份扣住 `mcpServers` 不发，需求会话反而拿不到
Crew 的 MCP 工具。所以 agent 身份只走首条提示语这条路（V1 的退路），提示语里只报工作区
路径和图谱目录，不教它工序——§9.3 边界 2：Crew 的人格提示词压在 agent 正文上面，
再往里加指令等于给竞争加砝码。

为什么不设 `unattended`：它是 `_ChatSlot` 的**只读属性**（`bool(_app) and not _human_seen`），
写不进去，也不该写。需求会话是人在网页上盯着聊的前台会话；slot 带 `_app='ai-studio'`，
在人第一次发消息之前它的批准窗口是 180 秒，人一发就回到正常窗口（`_human_seen` 由
dashboard 的用户路由置位并持久）。**不许**为了少点批准把它标成后台或用 yolo。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from kiro_crew.apps.builtins.ai_studio.backend import projects

logger = logging.getLogger(__name__)

APP_NAME = "ai-studio"

#: slot key 的前缀。和左栏以前自己建的 `ai-studio-<id>` 刻意不同名：老 slot 里躺着的
#: 是「谁都可能写过」的普通对话，而这个 key 下的 slot 由本模块建、由本模块管。
SLOT_PREFIX = "ai-studio-req-"

#: 工作区里写需求助手的说明文件（模板仓自带，见 RFC §9.2）。
WRITER_AGENT_FILE = Path(".claude/agents/requirement-writer.md")

#: 项目记录里「首条提示语已经发过」的标记。有了它，第二次进页面只是重新挂上同一个
#: 会话，不会再发一遍开场白。
STARTED_FLAG = "reqSessionStarted"


class ReqSessionError(Exception):
    """A refused requirement-session open, with the HTTP status the route maps."""

    def __init__(self, message: str, code: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def slot_key(project_id: str) -> str:
    return f"{SLOT_PREFIX}{project_id}"


def first_prompt(project: dict, ws: Path) -> str:
    """开场白，一字不差（RFC §9.3 V1 退路：让它先读 agent 文件，不教工序）。"""
    name = str(project.get("name") or "")
    if (ws / WRITER_AGENT_FILE).is_file():
        return (
            f"你在工作区「{name}」（目录 {ws}）。"
            "先完整读 .claude/agents/requirement-writer.md，之后完全按它工作。\n"
            "需求图谱放 docs/需求图谱/，需求标准在 docs/需求标准/。现在先问我这次要做什么页面。"
        )
    return (
        f"你在工作区「{name}」（目录 {ws}）。"
        "工作区里没有写需求助手的说明，请告诉用户「这个工作区缺少写需求助手，请联系管理员」。"
    )


def resolve_workspace(project: dict, project_path: Path) -> Path:
    """这个项目的会话该在哪个目录里跑，不存在就抛 409。

    和 `requirements.workspace_dir` 的**唯一**区别是缺失的处置：读需求页时退回项目
    目录没有害处（读不到图谱就是空列表），而在这里退回去等于开一个会话让它去写一个
    根本不存在的工作区——它会把文件写进 ai-studio 自己的记录目录里。所以缺就是缺，
    原样报 409，不猜。
    """
    raw = project.get("workspaceDir")
    if isinstance(raw, str) and raw.strip():
        candidate = Path(raw)
        if not candidate.is_dir():
            raise ReqSessionError(
                f"workspace directory is missing: {candidate}", "workspace_missing", 409
            )
        return candidate
    return project_path


def update_project(project_id: str, **fields: Any) -> dict:
    """把 *fields* 并进项目记录（读 project.json → 合并 → 原子写回）。

    `projects.py` 没有更新入口（它是只增的文档存储），本单不许改它，所以更新写在这里。
    原子写靠 tmp + `os.replace`，和 `projects.py` 里每一处写一样：崩在写中间不许留下
    一个解析不了的 project.json。
    """
    if not project_id:
        raise ReqSessionError("project not found", "project_not_found", 404)
    record = projects.get_project(project_id)
    if record is None:
        raise ReqSessionError("project not found", "project_not_found", 404)
    path = projects.projects_root() / project_id / "project.json"
    data = dict(record)
    data.update(fields)
    try:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".project-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        raise ReqSessionError(
            f"could not update the project: {exc}", "store_write_failed", 503
        ) from exc
    return data


def _dispatch_turn(state: Any, slot: Any, message: str) -> Any:
    """把一轮发给会话。Spec Builder 的同名私有函数是这个动作的既有实现（本单不许改
    那个 app，所以照它的写法在这里做一遍）：忙就排队，空就起一个 `_run_chat` 任务。

    dashboard 的导入放在函数里：`dashboard.server` 会导入 app 的 routes 模块，模块级
    导入会成环（spec_builder 的 `_dispatch_turn` 同一个理由）。
    """
    if getattr(slot, "running", False):
        try:
            from kiro_crew.dashboard.session_control import containment_meta

            slot.queue_append(message, meta=containment_meta(state, slot))
        except Exception:
            logger.debug("queue_append failed", exc_info=True)
        _push_slots(state)
        return None

    from kiro_crew.dashboard.chat_runner import _run_chat

    # bounded_chat_turn applies the configured turn ceiling off the loop, the way
    # every other app-spawned turn does (spec_builder's _dispatch_turn).
    try:
        from kiro_crew.dashboard.turn_dispatch import bounded_chat_turn
    except Exception:  # pragma: no cover - the resolver is always present in prod
        bounded_chat_turn = None  # type: ignore[assignment]

    slot.append("user", message)
    run_chat = _run_chat(state, slot, message)
    coro = (
        bounded_chat_turn(run_chat)
        if bounded_chat_turn is not None
        else asyncio.wait_for(run_chat, timeout=1800.0)
    )
    task = asyncio.create_task(coro)
    slot.task = task
    background = getattr(state, "_background_tasks", None)
    if isinstance(background, set):
        background.add(task)
        task.add_done_callback(background.discard)
    _push_slots(state)
    return task


#: 正在发开场白的项目 id。真跑时踩到的：同一个项目被并发打开两次（开两个标签、
#: 或首屏重试），两边都在对方写 `reqSessionStarted` 之前读完了 project.json，
#: 于是开场白发了两遍，助手回两段一模一样的话。标记落盘之前有一整个 agent turn
#: 的窗口，光靠那个标记挡不住并发。
#:
#: 这是**进程内**的闸，不是持久判据（持久判据仍是 project.json 里那个标记），
#: 网关重启后它自动清空——那时也不会有并发。
_starting: "set[str]" = set()


def _push_slots(state: Any) -> None:
    push = getattr(state, "push_slots_update", None)
    if callable(push):
        push()


def edit_notice(page: str, diff: str) -> str:
    """直改通知的正文（RFC §5 ``DocDirectEdited``：需求上下文把 diff 发给会话）。

    照派工单原文一字不差。两点约定：
      * **只给 diff，不给全文**：一版渲染出来的需求文档是几十 KB，塞进一句话会把
        助手的上下文顶掉，而它要落的只是改动的那几行；
      * **「落不进去的地方问我」是硬要求**：图谱是事实源，助手不能把落不进去的改动
        自己编个说法塞进去，那等于让它替用户改需求。
    """
    return (
        f"用户在网页上直接改了需求页「{page}」的文档，改动如下（diff）。"
        f"请把这些改动落回 docs/需求图谱/{page}.json，落不进去的地方问我。\n{diff}"
    )


async def send_to_req_session(
    state: Any,
    project: dict,
    ws: Path,
    text: str,
    *,
    dispatch: Callable[[Any, Any, str], Any] | None = None,
) -> dict:
    """往这个项目的需求会话发一条消息，返回 ``{"slotKey", "created"}``。

    和 ``ensure_req_session`` 的唯一区别是**发什么**：那条发开场白（且只发一次），
    这条发平台生成的通知（直改的 diff 等），每次都发。会话正忙时不丢消息也不并发
    起第二个 turn —— ``_dispatch_turn`` 自己会排队（这是它比裸 ``_run_chat`` 值钱的地方）。

    会话**只保证存在，不保证已开场**：开场白是打开左栏时才发的，而用户可能先在中栏
    改了文档。所以这里复用 ``ensure_req_session`` 把顺序摆正 —— 真跑里直改通知排在
    开场白之前，助手会先收到一段 diff 再收到「现在先问我这次要做什么页面」，答非所问。
    于是本函数**不许**换成「直接拿 slot 发一条」：那样并发打开左栏时开场白会重发。
    """
    opened = await ensure_req_session(state, project, ws, dispatch=dispatch)
    run_turn = dispatch if dispatch is not None else _dispatch_turn
    slot = state.get_or_create_slot(name=opened["slotKey"], app=APP_NAME)
    run_turn(state, slot, text)
    return opened


async def ensure_req_session(
    state: Any, project: dict, ws: Path, *, dispatch: Callable[[Any, Any, str], Any] | None = None
) -> dict:
    """幂等：保证这个项目有一个需求会话，返回 ``{"slotKey", "created"}``。

    `created` 说的是**首条提示语发没发过**（判据：项目记录里的 `reqSessionStarted`），
    不是 slot 是否新建——slot 可能早被别的入口建出来了，那第一次走到这里仍然要发开场白。
    """
    run_turn = dispatch if dispatch is not None else _dispatch_turn
    project_id = str(project.get("id") or "")
    # Read off the LOOP and off the STORE, before anything is created or sent:
    # the flag lives in project.json, so the caller's dict is not the authority
    # (a handler that read the record before a previous turn's write would
    # otherwise re-send the opening prompt forever). And a prompt that went out
    # against a project that does not exist could never be recorded as sent, so
    # every later call would send it again — hence 404 here, not at the write.
    record = await asyncio.to_thread(projects.get_project, project_id)
    if record is None:
        raise ReqSessionError("project not found", "project_not_found", 404)
    key = slot_key(project_id)
    slot = state.get_or_create_slot(name=key, app=APP_NAME)
    created = not bool(record.get(STARTED_FLAG))
    try:
        # 工作区目录 = 会话里 CLI 的 cwd（chat_runner 用 slot.project）。不设它，助手
        # 就在网关自己的工作目录里写文件，写到别人家去（spec_builder 同一条理由）。
        slot.project = str(ws)
        title = f"需求：{record.get('name') or project.get('name') or project_id}"
        if getattr(slot, "title", "") != title:
            slot.title = title
            push_title = getattr(state, "push_slot_title", None)
            if callable(push_title):
                push_title(slot.key, title)
    except Exception:  # pragma: no cover - the slot always takes these attrs
        logger.debug("requirement slot scoping failed for %s", key, exc_info=True)
    # The persisted flag alone does not hold: the window between "read the flag"
    # and "write the flag" spans a `to_thread`, and two opens of the SAME project
    # land in it routinely (React StrictMode runs the mount effect twice in dev,
    # and a first paint that retries does it for real). Both saw no flag, both
    # sent the opening prompt, and the assistant answered twice with the same
    # question — which is what the live run showed. Check-and-set with no await
    # in between, so only one of them can win.
    if created and project_id in _starting:
        created = False
    if created:
        _starting.add(project_id)
        try:
            run_turn(state, slot, first_prompt(record, ws))
            await asyncio.to_thread(update_project, project_id, **{STARTED_FLAG: True})
        finally:
            _starting.discard(project_id)
    return {"slotKey": key, "created": created}
