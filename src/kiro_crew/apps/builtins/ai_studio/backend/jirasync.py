"""开发任务往 Jira 拆一份（ACP-2085-S6）。

看板上的每个开发任务在 Jira 里有对应的单：一个工作区一个**父单**，每个开发任务
一个**子单**。这一层只干一件事 —— 把「调外部 jira 命令」这件事收在一个文件里，
让 ``devdag`` 只管节点状态该流转成什么，不管命令行怎么拼、凭据在哪、返回长什么样。

**命令可配，不把 jereh 专有的逻辑写死**：调什么命令、哪个项目、单子链接怎么拼、
两种状态叫什么名字，全部来自环境变量（见下）。没设 ``AI_STUDIO_JIRA_CMD`` 就是
「这个部署不同步 Jira」：所有函数直接返回 ``None``，一个子进程都不起，也不报错
—— Jira 是可选项，缺它不等于开发跑不了（``devdag`` 那边照样把整轮跑完）。

失败一律不抛。一次建单失败最多让看板上多一行灰字（节点的 ``jiraError``），而抛
出去会让整个开发轮次停在第一个节点上：为了记账把活停掉，是本末倒置。``*_checked``
那几个变体把错误原文一起回出来，就是给 ``devdag`` 记 ``jiraError`` 用的。

子进程一律 ``subprocess.run``（同步）+ 60 秒上限，调用方在
``asyncio.to_thread`` 里调它（``routes`` 与 ``devdag`` 都这么做）：Jira 在内网，
一次建单是秒级，但网关的事件循环还要服务别的会话。
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

#: 项目与子任务都打这两个标签之一：``ai-studio`` 标明是这套流程建的，另一个是
#: 工作区代号，便于在 Jira 里按代号搜回一整个工作区的单。
LABEL_APP = "ai-studio"

#: 一次 Jira 调用的上限。``jc`` 是个 node CLI，冷启动加一次内网往返是秒级；这个
#: 数只为挡住「命令挂住占着一个网关线程」，不是给正常路径设的预算。
CMD_TIMEOUT_S = 60

_DEFAULT_PROJECT = "ACP"
_DEFAULT_BROWSE = "https://jira.jereh.cn/browse/{key}"
#: 两个默认状态名。实测（2026-10-09，ACP-2153）jira.jereh.cn 的 ACP 项目里子任务
#: 的可用流转是「开始进行 / 停止进行 / 完成」，**没有**叫「进行中」的流转 ——
#: 「开始进行」这条流转把状态推到「测试中」。所以部署时要把
#: ``AI_STUDIO_JIRA_DOING`` 设成「开始进行」，默认值只是照派工单写的样子留着。
_DEFAULT_DOING = "进行中"
_DEFAULT_DONE = "完成"


def _env(name: str, default: str) -> str:
    """读环境变量，空串（含只有空白）按没设处理。"""
    raw = os.environ.get(name, "")
    return raw.strip() or default


def jira_cmd() -> list[str] | None:
    """环境变量 ``AI_STUDIO_JIRA_CMD``（shlex 拆，如 ``"jc jira"``）。

    没设返回 ``None`` = 不同步 Jira：本模块每个函数在第一步就回 ``None``，不起
    子进程、不报错。拆完是空的（设成了一个引号）也算没设，否则会拿空 argv 去
    ``subprocess.run`` 撞一个 ``IndexError``。
    """
    raw = os.environ.get("AI_STUDIO_JIRA_CMD", "").strip()
    if not raw:
        return None
    return shlex.split(raw) or None


def jira_project() -> str:
    """项目 key，``AI_STUDIO_JIRA_PROJECT``，默认 ``ACP``。"""
    return _env("AI_STUDIO_JIRA_PROJECT", _DEFAULT_PROJECT)


def browse_url(key: str) -> str:
    """一个单子的网页地址，``AI_STUDIO_JIRA_BROWSE``，默认官方 browse 链接。

    用 ``str.replace`` 而不是 ``format``：模板是运维写的，里面出现一个单独的
    ``{``（或者写了 ``%s`` 之类的别的形状）时 ``format`` 会抛，一个链接模板不该
    有本事让开发轮次报错。找不到 ``{key}`` 就照原样回 —— 给一个指不到单子的地址，
    也比抛出去强。
    """
    return _env("AI_STUDIO_JIRA_BROWSE", _DEFAULT_BROWSE).replace("{key}", key)


def doing_state() -> str:
    """节点开工时把 Jira 单流转成什么，``AI_STUDIO_JIRA_DOING``。"""
    return _env("AI_STUDIO_JIRA_DOING", _DEFAULT_DOING)


def done_state() -> str:
    """节点做完时把 Jira 单流转成什么，``AI_STUDIO_JIRA_DONE``。"""
    return _env("AI_STUDIO_JIRA_DONE", _DEFAULT_DONE)


def _failure(proc: subprocess.CompletedProcess[str]) -> str:
    """一次非零退出的错误原文：退出码 + stderr（没有就 stdout）的尾段。

    这段文字会原样出现在看板节点的 ``jiraError`` 上，所以要能一眼看出是哪坏了；
    命令自己打的 usage 之类长篇用尾 400 字截住。
    """
    detail = (proc.stderr or proc.stdout or "").strip()
    if len(detail) > 400:
        detail = detail[-400:]
    return f"exit {proc.returncode}: {detail or '命令没有输出'}"


def _run(argv: list[str]) -> tuple[Any, str]:
    """跑一条命令，回 ``(data 或 None, 错误原文)``；除 ``None`` 外不抛。

    ``data`` 是 JSON 信封里的 ``data``（建单类命令要看它），非建单类命令不看它、
    只要退出 0 且 ``success`` 为真就算成。

    先解析信封再决定成败：``jc`` 这类 CLI 报错走的是「退出码非 0 + 信封里带
    ``message``」（实测 ``transition --to 进行中`` 就是这么回的），那条 message 才
    是看板上该显示的话（「无可用流转 …」），退出码和 stderr 只是它的兜底。
    """
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CMD_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError:
        return None, f"命令不存在：{argv[0]}"
    except subprocess.TimeoutExpired:
        return None, f"命令超时（{CMD_TIMEOUT_S}s）：{' '.join(argv[:3])}"
    except OSError as exc:
        return None, f"命令跑不起来：{type(exc).__name__}: {exc}"
    try:
        envelope = json.loads(proc.stdout)
    except ValueError:
        envelope = None
    if isinstance(envelope, dict):
        if envelope.get("success"):
            return envelope.get("data"), ""
        return None, str(envelope.get("message") or "") or _failure(proc)
    if proc.returncode != 0:
        return None, _failure(proc)
    return None, f"命令没有回 JSON 信封：{(proc.stdout or '').strip()[:200]}"


def _created_key(data: Any) -> tuple[str | None, str]:
    """从建单命令的 ``data`` 里取单号（``key``，兼容 ``issueKey``）。

    取不到号一律按失败算并带原文：``jc`` 在 ``create`` 之后回的就是这两个名字，
    一个没有单号的 ``success`` 信封要么是命令改了形状要么是建了个别的单，两种都
    不该让节点拿一个空链接去显示。
    """
    if not isinstance(data, dict):
        return None, "建单命令回的 data 不是对象"
    key = str(data.get("key") or data.get("issueKey") or "").strip()
    return (key, "") if key else (None, "建单命令没有回单号")


def _title_for(project: dict[str, Any]) -> str:
    name = str(project.get("name") or "").strip() or str(project.get("id") or "")
    return f"[AI Studio] {name}（{_code_for(project)}）开发"


def _code_for(project: dict[str, Any]) -> str:
    """工作区代号。``code`` 是 RFC §9.1 的工作区代号，没代号的普通项目退回 id
    （``create_project`` 里没代号时 id 与代号同源，标签照样唯一）。"""
    return str(project.get("code") or project.get("id") or "")


def _labels(code: str) -> str:
    return f"{LABEL_APP},{code}" if code else LABEL_APP


def ensure_parent_checked(project: dict[str, Any]) -> tuple[str | None, str]:
    """:func:`ensure_parent`，附带错误原文。

    项目记录里已经有 ``jiraParent`` 就直接用它（**一个工作区只有一个父单**，重启
    网关、重做计划都不另建）；否则建一个并把单号写回项目记录。
    """
    argv = jira_cmd()
    if argv is None:
        return None, ""
    existing = str(project.get("jiraParent") or "").strip()
    if existing:
        return existing, ""
    code = _code_for(project)
    argv = [
        *argv,
        "issue",
        "create",
        "--project",
        jira_project(),
        "--summary",
        _title_for(project),
        "--labels",
        _labels(code),
    ]
    data, err = _run(argv)
    if err:
        return None, err
    key, err = _created_key(data)
    if key is None:
        return None, err or "建单命令没有回单号"
    _remember_parent(project, key)
    return key, ""


def ensure_parent(project: dict[str, Any]) -> str | None:
    """本项目开发父单的 Jira 号，没有 Jira 或建失败时 ``None``（不抛）。"""
    key, err = ensure_parent_checked(project)
    if err:
        logger.warning("ai-studio jira parent failed: %s", err)
    return key


def _remember_parent(project: dict[str, Any], key: str) -> None:
    """把父单号写回项目记录，并就地更新传进来的那份 dict。

    写回失败只记日志：单子已经建出来了，Jira 里看得见，看板上这一轮也拿到了号。
    为一个记账字段把开发停掉不值，但下一次 ``plan`` 会再建一个父单，所以这条日志
    是要人看的。
    """
    project["jiraParent"] = key
    project_id = str(project.get("id") or "")
    if not project_id:
        logger.warning("ai-studio jira parent %s not recorded: project record has no id", key)
        return
    from kiro_crew.apps.builtins.ai_studio.backend import projects

    try:
        projects.update_project(project_id, jiraParent=key)
    except Exception as exc:  # noqa: BLE001: 记不上账不该挡住已经建好的单
        logger.warning("ai-studio jira parent %s not recorded: %s", key, exc)


def create_task_checked(parent: str, title: str, code: str) -> tuple[str | None, str]:
    """:func:`create_task`，附带错误原文。"""
    argv = jira_cmd()
    if argv is None:
        return None, ""
    argv = [
        *argv,
        "issue",
        "create",
        "--project",
        jira_project(),
        "--parent",
        parent,
        "--summary",
        title,
        "--labels",
        _labels(code),
    ]
    data, err = _run(argv)
    if err:
        return None, err
    return _created_key(data)


def create_task(parent: str, title: str, code: str) -> str | None:
    """一个开发任务的 Jira 子单号；没有 Jira、或建不成时 ``None``（不抛）。"""
    key, err = create_task_checked(parent, title, code)
    if err:
        logger.warning("ai-studio jira task failed (%s): %s", title, err)
    return key


def transition_checked(key: str, to: str) -> str:
    """:func:`transition`，只回错误原文（空串 = 成）。"""
    argv = jira_cmd()
    if argv is None:
        return ""
    if not key or not to:
        return ""
    _data, err = _run([*argv, "issue", "transition", key, "--to", to])
    return err


def transition(key: str, to: str) -> None:
    """把单子流转成某个状态（``AI_STUDIO_JIRA_DOING`` / ``_DONE`` 那两个名字）。

    失败不抛：看板上节点的 Jira 号还在，状态没跟上，人工流转一下就行。
    """
    err = transition_checked(key, to)
    if err:
        logger.warning("ai-studio jira transition %s -> %s failed: %s", key, to, err)


def comment_checked(key: str, text: str) -> str:
    """:func:`comment`，只回错误原文（空串 = 成）。"""
    argv = jira_cmd()
    if argv is None:
        return ""
    if not key:
        return ""
    _data, err = _run([*argv, "issue", "comment", key, "--body", text])
    return err


def comment(key: str, text: str) -> None:
    """给单子追加一条评论（完工带提交号，失败带原因）。

    命令不支持 ``--body`` 的话就是「跳过并写日志」：评论是最轻的一笔，Jira 那边
    没有这条命令，开发这边不该有任何变化。
    """
    err = comment_checked(key, text)
    if err:
        logger.warning("ai-studio jira comment %s failed: %s", key, err)
