"""开发运行的串行调度（ACP-2085-S4 第 2 步）。

一个 ``DevRun`` = 一个项目的一轮开发：把 ``devplan.build_plan`` 算出的任务逐个
跑完，每个任务**开一个助手会话**发一轮，看板上就是这些节点的状态。

和 07 设计文档（``raw/ai-studio-acceptance/07-dev-dag-two-phase.md``）的差别是
本步有意为之的最小可用版，别照文档把它「补全」：

* 只有一个阶段 ``full``：不做演示版/完整版两阶段、不打 git tag、不做回退、不接
  Jira（节点上的 ``jiraKey`` 只是任务 id 的字段名，跟 Jira 没有关系）。
* **串行**：同一个工作区目录一次只跑一个任务，不建 worktree，所以 §四 的
  worktree 隔离/复用断言在这一版不适用。
* 不用 ``TaskRunner``：这里就是一个几十行的循环，照 Spec Builder 的
  ``runtime._ensure_worker_slot`` + ``_dispatch_turn`` 的写法开会话发一轮。

状态落在 ``<工作区>/.ai-studio/dev-run.json``（一个项目一份），日志落在
``dev-run.log``。文件是**唯一真相**：网关重启后 ``get`` 读文件就能把看板画出来，
内存里的那个循环只是正在跑的那一轮的执行体。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from kiro_crew.apps.builtins.ai_studio.backend import devplan, jirasync

logger = logging.getLogger(__name__)

PHASE = "full"

#: 一个任务一轮的上限。写一页的前后端是分钟到小时级的活，取 40 分钟：再长就更
#: 像是会话卡住了（等一个没人点的批准、或者 ACP 层断了没报错），而卡住的会话占
#: 着整个串行队列，后面的任务一个都发不出去。
TURN_TIMEOUT_S = 2400.0

#: 设成 ``1`` 才给每个会话开「信任会话」（免逐次批准）。不设就是老实等人点批准
#: —— 没人点的话节点会一直停在「进行中」，直到上面那个超时。默认不开：自动写
#: 代码提交这件事本身已经够大，批准这一道留给操作员自己决定要不要撤。
TRUST_ENV = "AI_STUDIO_DEV_TRUST"

_NODE_STATES = ("queued", "running", "done", "failed")

#: ``planned`` 是「任务已拆好、Jira 子单已建、等人点〔开始开发〕」这一档 runState
#: （ACP-2085-S6 第 2 步）。节点状态不变（还是那四种），多的是**整轮**的一档。
#: 「planned 不是在跑」是这一档最要紧的语义：:meth:`DevRun.get` 的孤儿判断只针对
#: ``running``，一份计划停在 ``planned`` 几小时等人开工是正常用法，把它判成
#: 「网关重启，中断」会白毁一份计划和它底下已经建好的 Jira 子单。
RUN_PLANNED = "planned"


class DevDagError(Exception):
    """A refused dev run, with the HTTP status the route maps."""

    def __init__(self, message: str, code: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


# ── 落盘 ──────────────────────────────────────────────────────────────────


def _state_path(ws: Path) -> Path:
    return ws / ".ai-studio" / "dev-run.json"


def _log_path(ws: Path) -> Path:
    return ws / ".ai-studio" / "dev-run.log"


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def _write(path: Path, payload: dict[str, Any]) -> None:
    """tmp + replace：看板每 3 秒读一次这个文件，半个 json 就是一次白屏。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def _read(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # 读不动就当没有这一轮：看板退回空态，比拿半份状态猜一个 runState 诚实。
        logger.warning("ai-studio dev-run state unreadable at %s", path, exc_info=True)
        return None
    return raw if isinstance(raw, dict) else None


def git_head(ws: Path) -> str:
    """``git rev-parse HEAD``，没有提交/不是仓库时回空串。

    判一个任务有没有真交付只认这一条：助手自己说「完成」是它的一面之词，提交不
    会撒谎。空串在「前后都取不到 HEAD」时会算成「没变」，也就是失败 —— 宁严勿松。
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(ws), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


# ── 会话侧的三个动作（都可被测试替身换掉）────────────────────────────────


def open_slot(state: Any, slot_name: str, ws: Path, title: str) -> Any:
    """开（或复用）这一轮某任务的助手会话，并把它圈到工作区上。

    照 Spec Builder ``runtime._ensure_worker_slot`` 的做法：``get_or_create_slot``
    只在新建时打 ``app``，所以拿到 slot 后必须自己补 ``project``/``title``
    —— 会话进程的 cwd 就是 ``slot.project``（``chat_runner`` 拿它当 cwd），不设
    的话助手是在网关的工作目录里写代码，写到别人的仓里去。

    **有意不设 ``unattended``**：那一套是给无人值守的 app worker 用的，会把批准
    静默掉；这里的免批准只走「信任会话」那一条，且受 ``AI_STUDIO_DEV_TRUST`` 控制。
    """
    slot = state.get_or_create_slot(name=slot_name, app="ai-studio")
    slot.project = str(ws)
    slot.title = f"开发：{title}"
    return slot


def grant_trust(state: Any, slot: Any) -> None:
    """给这个会话开「信任会话」——和网页上那个〔信任会话〕按钮同一条路。

    按钮落在 ``dashboard.chat_handlers.api_chat_mode`` 的 ``mode == "trust"`` 分支
    （``chat_handlers.py:11769``），那个分支干的就是下面三件事，这里逐条照抄：

    1. 同一 session 的**每个** slot 都打 ``_trust``（批准策略按 session 存，而
       ``_trust`` 按 slot 存，只设一个会让两个共用 session 的 slot 各执一词）；
    2. ``sessions.set_approval_policy(key, "auto")`` —— 子代理读的是这一条，不是
       内存里那个集合；
    3. 写一条 SEL 审计（``operation="mode_change:trust"``），所以审计照常记。

    这里不做按钮的 Slack 频道那半（``_slack_channel``/``channel_manager``）：那些
    slot 不挂在任何 IM 频道上，搬过来只是把无关的状态搅进来。

    也**不走** ``messaging.session_trust.add_trusted_session`` —— 名字相近但不是同一条：
    它的 ``_trusted_sessions`` 映射只有 IM 通道（``slack/handler``、
    ``telegram/transport_dispatch``）和 ``dashboard/server`` 的频道批准在读，网页按钮和
    ``chat_runner._slot_is_trusted`` 都不查它，照它调等于没授权。
    """
    from kiro_crew.dashboard.chat_utils import effective_session_key
    from kiro_crew.sel import sel

    key = effective_session_key(slot)
    for sharing in getattr(state, "_slots", {}).values():
        try:
            if effective_session_key(sharing) == key:
                sharing._trust = True
        except Exception:  # noqa: BLE001: 一个算不出 key 的 slot 不该挡住授权
            logger.debug("ai-studio dev trust: session key failed for a slot", exc_info=True)
    slot._trust = True
    state.sessions.set_approval_policy(key, "auto")
    try:
        sel().log_api_access(
            caller="ai-studio:dev",
            operation="mode_change:trust",
            outcome="enabled",
            resources=str(getattr(slot, "key", key) or key),
        )
    except Exception:  # noqa: BLE001: 审计写不进不能挡住已经授出去的权（那更危险）
        logger.warning("ai-studio dev trust: SEL audit failed", exc_info=True)


async def dispatch_and_read(state: Any, slot: Any, prompt: str) -> str:
    """发一轮提示词，等这一轮结束，回助手最后说的话。

    ``spec_builder.runtime._dispatch_turn`` 起一个 ``asyncio.Task`` 跑 ``_run_chat``；
    它返回 ``None`` 意味着 slot 正忙、这句话被排进队列了 —— 那一轮不是我们起的，
    等不到它的结束，所以按失败如实报，绝不假装跑完（这些 slot 是本轮自己新建的，
    正常路径上不会忙）。

    超时用 ``wait_for``，会**取消**这一轮：节点判 failed 之后串行队列要继续往下走，
    留一个还在写代码的会话在跑，下一个任务就会和它抢同一个工作区。
    """
    from kiro_crew.apps.builtins.spec_builder.backend.runtime import _dispatch_turn

    before = len(getattr(slot, "messages", None) or [])
    task = _dispatch_turn(state, slot, prompt)
    if task is None:
        return "失败：会话正忙，这一轮没能发出去"
    try:
        await asyncio.wait_for(task, timeout=TURN_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise _TurnTimeout() from None
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001: 一轮跑崩了是这一节点的失败，不是全进程的事
        return f"失败：会话这一轮异常退出（{type(exc).__name__}: {exc}）"
    messages = getattr(slot, "messages", None) or []
    for msg in reversed(messages[max(0, before - 1) :] if before else messages):
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "assistant" and str(msg.get("content") or "").strip():
            return str(msg["content"])
    return "失败：这一轮没有回复"


class _TurnTimeout(Exception):
    """Internal: one turn exceeded :data:`TURN_TIMEOUT_S`."""


# ── 调度 ──────────────────────────────────────────────────────────────────


class DevRun:
    """一个项目的一轮开发：状态机 + 串行循环。

    三个外部世界都从构造参数注入（``dispatcher``/``git``/``clock``），单测因此
    不起会话、不跑 git、不等真时间；「信任会话」是模块级函数
    :func:`grant_trust`，测试直接 monkeypatch 它（构造签名是派工单定死的）。
    """

    def __init__(
        self,
        state: Any,
        project: dict[str, Any],
        ws: Path,
        *,
        dispatcher: Callable[[Any, Any, str], Awaitable[str]] | None = None,
        git: Callable[[], str] | None = None,
        clock: Callable[[], float] | None = None,
        fail_point: str = "",
    ) -> None:
        self.state = state
        self.project = project
        self.ws = Path(ws)
        self.fail_point = fail_point
        self._dispatch = dispatcher or dispatch_and_read
        self._git = git if git is not None else (lambda: git_head(self.ws))
        self._clock = clock if clock is not None else time.time
        self._loop_task: asyncio.Task[Any] | None = None

    # ── 状态读写 ──

    def get(self) -> dict[str, Any]:
        """本轮状态；没有状态文件就是 ``{"runState":"idle","nodes":[]}``。

        顺带收孤儿：状态文件写着 ``running``（整轮或某个节点）但**本进程没有正在
        跑的循环**，那它是网关重启前的遗物 —— 循环死在进程里，文件停在最后一次写入。
        它不会自己结束，看板会永远转圈，所以在读的时候如实判成失败并说明原因；
        判失败同时也是失败续跑那条路的入口（续跑只挑 queued，节点不先落成 failed
        就永远轮不到它重做）。

        ``planned`` 不在判断之列（ACP-2085-S6）：它是「拆好了等人开工」，一份计划
        停在这一档几小时是正常用法，判它「网关重启，中断」会白毁一份计划。
        """
        data = _read(_state_path(self.ws))
        if data is None:
            return {"runState": "idle", "nodes": []}
        if self._loop_alive():
            return self._with_parent_url(data)
        interrupted = False
        for node in data.get("nodes") or []:
            if isinstance(node, dict) and node.get("state") == "running":
                node["state"] = "failed"
                node["message"] = "网关重启，中断"
                interrupted = True
        if data.get("runState") == "running" or interrupted:
            data["runState"] = "failed"
            interrupted = True
        if interrupted:
            try:
                _write(_state_path(self.ws), data)
            except OSError:
                logger.warning("ai-studio dev-run orphan rewrite failed", exc_info=True)
            self._log("interrupted by gateway restart", "")
        # 没中断也要带上父单链接：派生字段只在读的时候算，理由见 _with_parent_url。
        return self._with_parent_url(data)

    def _with_parent_url(self, data: dict[str, Any]) -> dict[str, Any]:
        """给读出的一份状态补上父单链接（``jiraParentUrl``）。

        派生字段不写盘：链接模板是环境变量 ``AI_STUDIO_JIRA_BROWSE`` 决定的，落进
        状态文件就等于把一个部署侧的配置焊死在数据里 —— 换了 Jira 地址之后，旧文件
        里的旧链接会一直指着错的地方。
        """
        parent = str(data.get("jiraParent") or self.project.get("jiraParent") or "")
        if parent:
            data = {**data, "jiraParent": parent, "jiraParentUrl": jirasync.browse_url(parent)}
        return data

    def log_lines(self, lines: int) -> list[str]:
        path = _log_path(self.ws)
        if not path.is_file():
            return []
        try:
            rows = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        return rows[-lines:] if lines > 0 else rows

    # ── 起 ──

    def _jira_code(self) -> str:
        """Jira 标签和标题里带的工作区代号（没代号的普通项目退回 id，再退工作区名）。"""
        return str(self.project.get("code") or self.project.get("id") or self.ws.name)

    async def _jira(self, fn: str, *args: Any) -> Any:
        """线程池里调 :mod:`jirasync` 的一个函数。

        这一层的每个函数都是子进程（内网 Jira，秒级），在事件循环里直接调就是拿
        整个网关换一次建单。异常一律吃掉：Jira 是记账，记账坏了不许改开发的结论。
        """
        try:
            return await asyncio.to_thread(getattr(jirasync, fn), *args)
        except Exception as exc:  # noqa: BLE001: 见上
            logger.warning("ai-studio jira %s failed: %s", fn, exc)
            return (None, f"{type(exc).__name__}: {exc}") if fn.endswith("_checked") else None

    async def plan(self, pages: list[str]) -> dict[str, Any]:
        """先拆任务、后开发（ACP-2085-S6）：生成计划 + 每个任务建一个 Jira 子单。

        和 :meth:`start` 的分工就是这一步的全部意义：拆完的看板是一眼能数清的清单
        （``runState=planned``，一个节点都没跑）， Jira 里也已经挂上了子单，人能先
        在 Jira 上改标题、改优先级、删掉不该做的，再回来看板点〔开始开发〕。

        重复拆的规矩（派工单第 2 步）：

        * **页面集合没变**：原样保留已经拆好的那份，一个 Jira 单都不新建 —— 否则点
          两次〔拆分任务〕就会在项目下长出两套重复子单。
        * **页面集合变了**：按新页面重新生成，但**同一个任务 id 的号不重建**（老号
          跟着走），已 ``done`` 的节点连同提交号一起保留（不重跑已经交付的活）；
          被这次改动挤掉的、又没做完的老单，在 Jira 里评论「计划已重做，此单作废」
          并置完成 —— 留在待办里是让人去做一件已经不做了的事。

        ``running`` 时 409：正在跑的那一轮的节点就是它的进度，中途换计划会让循环
        手里的节点从盘上消失。
        """
        current = self.get()
        if current.get("runState") == "running":
            raise DevDagError("already running", "run_active", 409)

        prior = [n for n in (current.get("nodes") or []) if isinstance(n, dict)]
        by_key: dict[str, dict[str, Any]] = {str(n.get("jiraKey") or ""): n for n in prior}
        same_pages = bool(prior) and _pages_of(prior) == set(pages)
        if same_pages:
            # 已经拆好的一份计划（含它的 Jira 号）就是答案，重写一遍只会造重复单。
            data = dict(current)
            data.setdefault("runState", RUN_PLANNED)
            return data

        parent, parent_err = await self._jira("ensure_parent_checked", self.project)
        if parent_err:
            self._log(f"jira parent failed: {parent_err}", "")

        built = devplan.build_plan(self.ws, pages)
        nodes: list[dict[str, Any]] = []
        for task in built["tasks"]:
            key = str(task["id"])
            old = by_key.get(key)
            node: dict[str, Any] = {
                # ``jiraKey`` 是 07 §三 B1 定死的字段名（看板按它定位节点），里面装
                # 的是任务 id；真正的 Jira 号在 ``jira``（ACP-2085-S6 才有的那一位）。
                "jiraKey": key,
                "title": task["title"],
                "dependsOn": list(task["dependsOn"]),
                "state": "queued",
                "slotKey": "",
                "startCommit": "",
                "endCommit": "",
                "message": "",
            }
            if old is not None and old.get("state") == "done":
                # 交付过的活不重跑也不重开单：状态、提交号、号一起搬过来。
                node["state"] = "done"
                node["startCommit"] = str(old.get("startCommit") or "")
                node["endCommit"] = str(old.get("endCommit") or "")
                node["slotKey"] = str(old.get("slotKey") or "")
                node["message"] = str(old.get("message") or "")
            node["jira"] = str(old.get("jira") or "") if old else ""
            if not node["jira"] and parent:
                created, err = await self._jira(
                    "create_task_checked", str(parent), str(task["title"]), self._jira_code()
                )
                node["jira"] = str(created or "")
                node["jiraError"] = err
            elif not node["jira"] and parent_err:
                # 父单没建起来：原因记一条就够，不必每个节点去撞一次命令。
                node["jiraError"] = parent_err
            # 三种情况都不记 jiraError：没配 Jira（AI_STUDIO_JIRA_CMD 没设）时
            # parent 与 parent_err 都空，那不是故障，而是「这个部署不同步 Jira」。
            # 给每个节点挂一句「没有 Jira 父单」的灰字，等于把一项可选配置报成坏了。
            node["jiraUrl"] = jirasync.browse_url(node["jira"]) if node["jira"] else ""
            nodes.append(node)

        # 「done 的节点保留」：连页一起掉的也留着那一行 —— 代码已经提交在工作区里了，
        # 从看板上消失等于把交付过的事实抹掉，而 Jira 那张单还该是完成态。
        for key, old in by_key.items():
            if key not in {str(n["jiraKey"]) for n in nodes} and old.get("state") == "done":
                nodes.append(dict(old))

        kept = {str(n["jiraKey"]) for n in nodes}
        for key, old in by_key.items():
            # 只作废「这次不要了、而且没交付」的老单：留在 Jira 待办里是让人去做一件
            # 已经不做了的事；交付过的上面已经留下，不作废。
            if key not in kept:
                await self._void_old(old)

        data = {
            "runId": current.get("runId") or f"plan-{int(self._clock())}-{os.getpid()}",
            "phase": PHASE,
            "runState": RUN_PLANNED,
            "startedAt": current.get("startedAt") or _iso(self._clock()),
            "graphHashes": built["graphHashes"],
            "nodes": nodes,
        }
        if parent:
            data["jiraParent"] = str(parent)
        _write(_state_path(self.ws), data)
        self._log(f"planned nodes={len(nodes)} parent={parent or '-'}", "")
        # 和 GET dev/dag 同一个形状返回（父单链接是读时派生的），否则刚拆完那一次
        # 前端拿到的表头没有链接，要等下一次刷新才有。
        return self._with_parent_url(data)

    async def _void_old(self, node: dict[str, Any]) -> None:
        """把被新计划挤掉的、没做完的老单作废：评论一句 + 置完成。

        「置完成」而不是「删单」：Jira 里没有删（``jc`` 也没给），而留在待办的是一
        件没人会做的事。失败不抛，看板上那一行本来就已经不在列表里了。
        """
        key = str(node.get("jira") or "")
        if not key:
            return
        err = await self._jira("comment_checked", key, "计划已重做，此单作废")
        if err:
            self._log(f"jira void comment failed {key}: {err}", key)
        err = await self._jira("transition_checked", key, jirasync.done_state())
        if err:
            self._log(f"jira void transition failed {key}: {err}", key)

    async def start(self, pages: list[str]) -> dict[str, Any]:
        """起一轮（或从失败处续跑），立即返回 ``{"runId","phase"}``。

        循环在后台跑：一页前后端是几十分钟量级，没有任何 HTTP handler 可以等它。

        有 ``planned`` 计划就跑那份（**不重新拆**：任务已经建过 Jira 单，重拆等于
        把人工在 Jira 上改过的东西抹掉）；没有就先自动 ``plan`` 一次，所以老用法
        「点〔开始开发〕直接跑」的行为一个字没变，只是顺带也拆了单。

        ``done`` 之后再点是**新一轮**：节点全部改回 queued 重跑一遍（和这一单之前
        的行为一致 —— 交付过了也可以再来一轮），Jira 号沿用不重建：同一个任务第二
        次做完，是把原来那张单再流转一遍，而不是另开一张。
        """
        current = self.get()
        state_before = str(current.get("runState") or "")
        if state_before == "running":
            raise DevDagError("already running", "run_active", 409)

        resume_plan = state_before in (RUN_PLANNED, "failed") and bool(current.get("nodes"))
        if not resume_plan:
            # idle（没拆过）或上一轮已经 done：先拆一份（same-pages 时 plan 原样回
            # 已经拆好的那份，一个 Jira 单都不新建）。
            current = await self.plan(pages)
        # 续跑（planned / failed）：done 的节点原样不动，不重跑已经交付的活。
        # 新一轮（idle，或 done 之后再点一次）：整条清单重新派一遍。
        keep_done = resume_plan

        nodes = [dict(n) for n in (current.get("nodes") or []) if isinstance(n, dict)]
        for node in nodes:
            if node.get("state") == "done" and keep_done:
                continue
            node.update(
                {
                    "state": "queued",
                    "slotKey": "",
                    "startCommit": "",
                    "endCommit": "",
                    "message": "",
                }
            )
        hashes = current.get("graphHashes") if isinstance(current.get("graphHashes"), dict) else {}

        run_id = f"dev-{int(self._clock())}-{os.getpid()}"
        data = {
            "runId": run_id,
            "phase": PHASE,
            "runState": "running",
            "startedAt": _iso(self._clock()),
            "graphHashes": hashes,
            "nodes": nodes,
        }
        parent = str(current.get("jiraParent") or self.project.get("jiraParent") or "")
        if parent:
            data["jiraParent"] = parent
        _write(_state_path(self.ws), data)
        self._log(f"start phase={PHASE} resumed={resume_plan} nodes={len(nodes)}", "")
        self._loop_task = asyncio.create_task(self._run_safe())
        return {"runId": run_id, "phase": PHASE}

    # ── 循环 ──

    async def _run_safe(self) -> None:
        try:
            await self._loop()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001: 循环自己崩了必须落到状态里，否则看板永远转圈
            logger.exception("ai-studio dev loop crashed")
            self._finish_run("failed")
            self._log(f"loop crashed: {type(exc).__name__}: {exc}", "")

    def _data(self) -> dict[str, Any]:
        data = _read(_state_path(self.ws)) or {}
        if not isinstance(data.get("nodes"), list):
            data["nodes"] = []
        return data

    def _save(self, data: dict[str, Any]) -> None:
        _write(_state_path(self.ws), data)

    def _finish_run(self, run_state: str) -> None:
        data = self._data()
        data["runState"] = run_state
        self._save(data)

    def _loop_alive(self) -> bool:
        return self._loop_task is not None and not self._loop_task.done()

    def _crash(self, where: str) -> None:
        """测试注入点：在指定位置炸掉本轮，模拟「网关重启把循环带走」。

        没有别的办法造出那个现场 —— 验收要的中断恰好是「活已经干了、状态还没落盘」
        这一小段，只能在两处动作之间断掉。`fail_point` 只有测试会传：值是节点 key
        表示「这个节点开工前断」，``after-dispatch:<key>`` 表示「会话已经写完提交、
        状态文件里它还是 running 时断」。
        """
        raise DevDagError(f"injected crash at {where}", "dev_test_crash_point", 500)

    def _next_node(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """按顺序取第一个 queued 且依赖全 done 的节点。"""
        done = {n.get("jiraKey") for n in data["nodes"] if n.get("state") == "done"}
        for node in data["nodes"]:
            if node.get("state") != "queued":
                continue
            deps = node.get("dependsOn") or []
            if all(dep in done for dep in deps):
                return node
        return None

    async def _loop(self) -> None:
        project_id = str(self.project.get("id") or self.ws.name)
        while True:
            data = self._data()
            node = self._next_node(data)
            if node is None:
                states = {n.get("state") for n in data["nodes"]}
                if states <= {"done"}:
                    data["runState"] = "done"
                    self._save(data)
                    self._log("run done", "")
                elif "failed" in states:
                    # 上一轮判失败时已经收口过；走到这里说明没有可派的节点了。
                    data["runState"] = "failed"
                    self._save(data)
                else:
                    # 没有 failed 也没有可派的 queued：只剩 running 或依赖成环。
                    # 环在这一版不可能出现（每页只有 web→api 一条边），真到这里
                    # 就是状态文件被改坏了，如实标失败，不要转圈。
                    data["runState"] = "failed"
                    self._save(data)
                    self._log("no runnable node, stopping", "")
                return
            await self._run_node(data, node, project_id)
            if self._data().get("runState") == "failed":
                return

    async def _run_node(self, data: dict[str, Any], node: dict[str, Any], project_id: str) -> None:
        key = str(node.get("jiraKey") or "")
        index = next(
            (i for i, n in enumerate(data["nodes"]) if n.get("jiraKey") == key),
            len(data["nodes"]),
        )
        if self.fail_point == key:
            self._crash(key)
        node["state"] = "running"
        node["startCommit"] = self._git()
        node["message"] = ""
        self._save(data)
        self._log("node start", key)
        # 开工先把 Jira 子单推到「进行中」（名字可覆盖，见 jirasync.doing_state）。
        # 放在开会话之前：单子没流转到是记账的事，而会话开不开得出来是这条活干不
        # 干得了的事，两件事不要互相等。
        await self._jira_transition(node, jirasync.doing_state())
        self._save(data)

        slot_name = f"ai-studio-dev-{project_id}-{index + 1}"
        try:
            slot = open_slot(self.state, slot_name, self.ws, str(node.get("title") or key))
        except Exception as exc:  # noqa: BLE001: 会话开不出来就是这个节点的失败
            await self._set_failed(data, node, f"开会话失败：{type(exc).__name__}: {exc}")
            return
        node["slotKey"] = str(getattr(slot, "key", slot_name) or slot_name)
        self._save(data)
        self._log(f"slot={node['slotKey']}", key)

        if os.environ.get(TRUST_ENV, "").strip() == "1":
            try:
                # 模块级查找（不是 self 上缓存的引用）：测试靠 monkeypatch 它来数
                # 「每个 slot 调一次」。
                await asyncio.to_thread(grant_trust, self.state, slot)
                self._log("trust granted", key)
            except Exception as exc:  # noqa: BLE001: 授权失败就退回「等人点批准」，不要静默放行
                self._log(f"trust failed: {type(exc).__name__}: {exc}", key)

        prompt = self._prompt_for(node)
        try:
            reply = await self._dispatch(self.state, slot, prompt)
        except _TurnTimeout:
            await self._set_failed(data, node, "超时")
            return
        except Exception as exc:  # noqa: BLE001: 派发炸了同样是这一节点的失败
            await self._set_failed(data, node, f"派发失败：{type(exc).__name__}: {exc}")
            return

        # 会话已经写完并提交了，状态文件里这个节点还是 running —— 断在这里就是
        # 那道缺口：代码在盘上，看板不知道。
        if self.fail_point == f"after-dispatch:{key}":
            self._crash(self.fail_point)
        last_line = _last_line(reply)
        end_commit = self._git()
        node["endCommit"] = end_commit
        said_done = last_line.startswith("完成")
        committed = bool(end_commit) and end_commit != node.get("startCommit")
        if committed and said_done:
            node["state"] = "done"
            node["message"] = ""
            self._save(data)
            self._log(f"done commit={end_commit[:8]}", key)
            # 单子跟着落：先流转再评论，评论里带提交号 —— 在 Jira 里点开单子就能
            # 看到这一条是哪一次提交（看板只是它的投影）。两次调用都可能往节点上
            # 记 jiraError，所以完事再存一次盘。
            await self._jira_transition(node, jirasync.done_state())
            await self._jira_comment(node, f"完成，提交 {end_commit[:8]}")
            self._save(data)
            return
        # 两个条件不一致时，光回显助手那句话会把看板写成「失败 / 完成」——那种
        # 现场恰恰最需要说清是哪一半没成立。
        if said_done and not committed:
            node["message"] = "回复说完成了，但没有新提交"
        else:
            node["message"] = last_line
        await self._set_failed(data, node, None)

    async def _set_failed(
        self, data: dict[str, Any], node: dict[str, Any], message: str | None
    ) -> None:
        node["state"] = "failed"
        if message is not None:
            node["message"] = message
        # 本轮收口于失败：后面的节点保持 queued（07 场景 D2「不许假全绿」），恢复
        # 只有再 start 一条路。
        data["runState"] = "failed"
        self._save(data)
        self._log(f"failed: {node.get('message', '')}", str(node.get("jiraKey") or ""))
        # 失败的单子**不流转**（派工单第 2 步）：Jira 那边它还在「进行中」，因为这一
        # 条活确实没干完 —— 只有评论说清为什么。把失败流转成「完成」会让 Jira 的
        # 看板比这块板更假。
        await self._jira_comment(node, _failure_comment(node))
        self._save(data)

    async def _jira_transition(self, node: dict[str, Any], to: str) -> None:
        """流转这一节点的 Jira 子单，失败把原文记到 ``jiraError``（不抛）。

        没有号就一个子进程都不起（没配 Jira 的部署每轮会白跑十几次 ``jc``）。
        """
        key = str(node.get("jira") or "")
        if not key:
            return
        await self._jira_note(node, await self._jira("transition_checked", key, to))

    async def _jira_comment(self, node: dict[str, Any], text: str) -> None:
        """给这一节点的 Jira 子单追加一条评论，规则同上。"""
        key = str(node.get("jira") or "")
        if not key:
            return
        await self._jira_note(node, await self._jira("comment_checked", key, text))

    async def _jira_note(self, node: dict[str, Any], err: Any) -> None:
        """记一条 Jira 失败原文（调用方已经确认这一节点有号）。

        留**第一条**而不是最后一条：一个节点的建单／流转／评论是同一条链路上的三连
        调用，第一条坏了后面两条必然跟着坏，而看板上那行灰字要的是根因。
        """
        if not err:
            return
        if not str(node.get("jiraError") or ""):
            node["jiraError"] = str(err)
        self._log(f"jira call failed: {err}", str(node.get("jiraKey") or ""))

    def _prompt_for(self, node: dict[str, Any]) -> str:
        key = str(node.get("jiraKey") or "")
        page, _, kind = key.partition(":")
        if kind in devplan.KINDS:
            return devplan.task_prompt(page, kind)
        # 状态文件里的任务 id 被人改过：没有对应提示词就发一句最接近的话，至少
        # 会话里看得见要做什么，而不是发一个空串让助手自己猜。
        return f"你在这个工作区里完成「{node.get('title') or key}」。做完最后一句只回复：完成 或 失败：<原因>。"

    def _log(self, event: str, node_key: str) -> None:
        """一行一条追加：时间 + 事件 + 任务 id。"""
        try:
            path = _log_path(self.ws)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(f"{_iso(self._clock())} {event} {node_key}".rstrip() + "\n")
        except OSError:
            logger.warning("ai-studio dev-run log write failed", exc_info=True)


def _failure_comment(node: dict[str, Any]) -> str:
    """失败节点发到 Jira 的那句话。

    节点的 ``message`` 有两种来源：助手自己那一行的原文（「失败：单测没过」），或
    调度器的一句判定（「超时」「回复说完成了，但没有新提交」）。前者已经带了
    「失败：」，再拼一次就是「失败：失败：单测没过」—— 看板上那行是原文照抄的，
    Jira 里多出来的一层前缀会让它和看板对不上。
    """
    message = str(node.get("message") or "").strip() or "未知原因"
    return message if message.startswith("失败") else f"失败：{message}"


def _last_line(text: str) -> str:
    rows = [r.strip() for r in str(text or "").splitlines() if r.strip()]
    return rows[-1] if rows else ""


def node_jira_view(record: dict[str, Any]) -> dict[str, Any]:
    """一个项目记录对应的 Jira 父单视图 ``{jiraParent, jiraParentUrl}``。

    给路由用：一份 ``planned`` 计划可能还没有父单（没配 Jira、或建失败），这时
    表头那一行该显示项目记录里已经记着的号 —— ``project.json`` 的 ``jiraParent``
    是父单的唯一持久出处（``ensure_parent`` 建成就写回那里）。
    """
    parent = str(record.get("jiraParent") or "")
    if not parent:
        return {}
    return {"jiraParent": parent, "jiraParentUrl": jirasync.browse_url(parent)}


def _pages_of(nodes: list[dict[str, Any]]) -> set[str]:
    """一份节点列表覆盖的页名集合（任务 id 是 ``<page>:<kind>``）。

    ``plan`` 用它判「页面集合变没变」：没变就别重拆（会造重复 Jira 单），变了才
    重新生成。用集合而不是顺序：换页的顺序不改任务集合，也不该为此重开一批单。
    """
    pages: set[str] = set()
    for node in nodes:
        page = str(node.get("jiraKey") or "").partition(":")[0]
        if page:
            pages.add(page)
    return pages
