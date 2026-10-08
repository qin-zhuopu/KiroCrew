"""新建工作区 = 复制模板（RFC rfc-ai-studio-req-flow §9.1）。

一个工作区是一份从模板仓克隆出来的真实 Git 仓，外加一个个人远端。派生动作本身
不归本平台实现：它是一条可配置命令（默认 ``jc webapp init``，环境变量
``AI_STUDIO_WORKSPACE_CMD`` 可换），本平台负责的是**把一条长命令变成用户看得懂的
四步进度**，以及失败后能重试而不必从头再来。

状态写在项目记录里（``projects.py`` 的 ``project.json``），不另开状态文件：前端
每 2 秒轮询的就是 ``GET /projects/{id}``，多一个文件就多一个会和记录说不一致的
东西。四步名（:data:`STEPS`）是界面要显示的中英之外唯一的步骤标识，``failedStep``
用的就是这些原文。

外部世界全在可注入的替身后面（``runner`` / ``devserver_factory``），理由和
:mod:`devserver` 一样：单测绝不起真进程、绝不联网（testing-conventions）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

from kiro_crew.apps.builtins.ai_studio.backend import devserver, projects

logger = logging.getLogger(__name__)

#: 代号：进仓名、进个人仓路径、进开发服务器域名，所以字符集必须同时满足三处。
#: 3~24 位、小写字母开头、结尾不许是短横线（DNS 标签也不许）。
CODE_RE = re.compile(r"^[a-z][a-z0-9-]{1,22}[a-z0-9]$")

#: 四步的原文名字，界面照抄、``failedStep`` 照抄。前三步由一条派生命令做完，
#: 第四步复用 devserver 那套（起服务 + 挂网址 + 健康检查都在它里面）。
STEPS = ("克隆模板", "建个人仓", "推送", "启动开发服务器")

#: 前三步：一条 ``jc webapp init`` 全做完，失败时只能靠信封 message 里的词猜是哪步。
DERIVE_STEPS = STEPS[:3]

DEFAULT_TEMPLATE_URL = "https://bitbucket.jereh.cn/scm/~14409/webapp-template.git"

#: 默认派生命令的参数（``jc webapp init <模板> --name <代号> --uid <工号> --base
#: <根> --no-init-sessions``）。``--no-init-sessions`` 是不想要但已经踩过的：模板
#: 初始化时顺手建会话，会把一个空工作区塞进会话列表。
DEFAULT_CMD_HEAD = ["jc", "webapp", "init"]

#: 派生命令的天花板。克隆一个 monorepo + 建远端 + 推 develop 分支，冷启动是分钟
#: 级；这个只挡死住的孩子，不是给用户看的等待时间。
_DERIVE_TIMEOUT_S = 900

#: 重试补推送的天花板：一次 push 不该超过五分钟，超了就是网络或远端有问题。
_PUSH_TIMEOUT_S = 300

#: 派生日志名，落在项目记录目录下（不是工作区里 —— 克隆失败时工作区可能半个都不
#: 存在，而「查看日志」按钮在那一刻最需要能用）。
LOG_FILE = "workspace.log"

#: 派生命令的 JSON 信封里，判断「哪一步失败」用的关键词（按顺序命中先来的）。
_STEP_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("克隆模板", ("clone",)),
    ("建个人仓", ("create-repo", "repo")),
)

#: 项目状态。creating 是建完记录到后台跑完之间的唯一状态，界面据此显示「创建中」。
#: 已知残留，和 devserver 那句「状态文件孤零零写着 starting 是上次启动跟着网关一起没
#: 了」是同一种谎：网关在派生跑到一半时重启，这条记录就永远停在 creating —— 界面一直
#: 转圈，retry 回 409（不是 failed），重新建又回 409（代号已被占用），今天只能手工去
#: 数据目录里改。修法已经备好：:func:`job_running` 就是 devserver ``_launching`` 的
#: 对应物，按它把 creating 重算即可；本期没做，是因为改判据要同时改 retry 的 409 语义
#: （本单第 3 步把「非 failed 一律 409」定死为对外契约），不该由实现顺手放宽。
STATUS_CREATING = "creating"
STATUS_READY = "ready"
STATUS_FAILED = "failed"

#: 每一步的状态。名字对外（界面的图标按它选），值是 project.json 里写的原文。
STEP_PENDING = "pending"
STEP_RUNNING = "running"
STEP_DONE = "done"
STEP_FAILED = "failed"

#: 环境里必须剥掉的键前缀：派生命令会去起 ACP 会话（jc 侧的活儿），绝不能拿到
#: 网关自己的模型与密钥。同 devserver._ENV_DROP_PREFIXES。
_ENV_DROP_PREFIXES = ("ANTHROPIC_", "KIROCREW_", "CLAUDE_")


class WorkspaceError(Exception):
    """一次被拒的工作区操作，带 HTTP 层要用的 code 与 status（同 devserver）。"""

    def __init__(self, message: str, code: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


#: 「失败状态已经写好了」的异常：抛出它们的那一处负责落盘，run/retry 只负责把它们
#: 原样交给调用方（线程版会记一条 traceback）。分开列是因为 DevServerError 是别的模块
#: 的类型 —— 漏了它，一次被拒的启动会被当成「没预料到的坏」再兜一次，把已经写对的
#: failedStep 覆盖成猜的。
_HANDLED = (WorkspaceError, devserver.DevServerError)


def workspaces_root() -> Path:
    """工作区的家：环境变量 ``AI_STUDIO_WORKSPACES_ROOT``，默认 ``/workspaces``。

    每次调用现读，不在 import 期定死：测试用 monkeypatch 改环境变量，模块级常量
    会把它锁在导入那一刻的值上。这里**不**用 ``config_dir()``——工作区是要进 Git、
    要给人 ``cd`` 进去干活的真仓，把它埋进数据目录（``~/.kiro/crew`` 下）等于把它
    藏进一个带沙箱围栏的地方。
    """
    raw = os.environ.get("AI_STUDIO_WORKSPACES_ROOT", "").strip()
    return Path(raw) if raw else Path("/workspaces")


def check_code(code: str) -> str:
    """验代号并原样返回（不转小写：大写在界面就该被看见，``sbgl`` 才是 ``SBGL``）。

    消息带原值 —— 「代号不合规：设备管理」比「格式不对」更省一轮来回。

    正则 ``^[a-z][a-z0-9-]{1,22}[a-z0-9]$`` 要求**至少三位**（首、中 1~22、尾），
    所以 ``a1`` 这种两位的是不合的 —— 短横线在尾巴上也不合（DNS 标签两端都不许）。
    """
    value = code if isinstance(code, str) else ""
    if not CODE_RE.match(value):
        raise WorkspaceError(f"代号不合规：{value}", "bad_code", 400)
    return value


def template_url() -> str:
    """模板仓地址：``AI_STUDIO_WORKSPACE_TEMPLATE``，默认 :data:`DEFAULT_TEMPLATE_URL`。"""
    raw = os.environ.get("AI_STUDIO_WORKSPACE_TEMPLATE", "").strip()
    return raw or DEFAULT_TEMPLATE_URL


def derive_cmd(template_url: str, code: str, staff_id: str, root: Path) -> list[str]:
    """派生命令本体。

    ``AI_STUDIO_WORKSPACE_CMD``（shlex 拆）设了就用它，并把 ``{template}``
    ``{code}`` ``{uid}`` ``{base}`` 四个占位换掉 —— 换的是**每个参数**，不是整条
    命令字符串，所以 ``--base={base}`` 这种粘连写法也换得动。没设用默认那条
    ``jc webapp init``。

    占位用 ``.replace`` 而不是 ``.format``：模板地址里可能带花括号吗？不会，但
    ``shlex.split`` 出来的用户参数里带一个孤立的 ``{`` 是完全可能的（``awk '{print}'``），
    ``format`` 会当场炸。
    """
    raw = os.environ.get("AI_STUDIO_WORKSPACE_CMD", "").strip()
    parts = shlex.split(raw) if raw else []
    if not parts:
        return [
            *DEFAULT_CMD_HEAD,
            template_url,
            "--name",
            code,
            "--uid",
            staff_id,
            "--base",
            str(root),
            "--no-init-sessions",
        ]
    subs = {
        "{template}": template_url,
        "{code}": code,
        "{uid}": staff_id,
        "{base}": str(root),
    }
    return [_sub_one(part, subs) for part in parts]


def _sub_one(part: str, subs: dict[str, str]) -> str:
    for key, value in subs.items():
        part = part.replace(key, value)
    return part


def child_env(extra: dict | None = None) -> dict:
    """派生命令的环境：网关环境剥掉模型/密钥类。

    和 :func:`devserver.child_env` 是同一件事，但**故意不剥代理变量**：派生命令要
    走内网 Bitbucket，代理变量在不在是本机网络的事，这里没资格替它决定。
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith(_ENV_DROP_PREFIXES)}
    env.update({str(k): str(v) for k, v in (extra or {}).items()})
    return env


def run_derive(cmd: list[str], log_path: Path, timeout: int = _DERIVE_TIMEOUT_S) -> dict:
    """跑派生命令，stdout+stderr 追加进 ``log_path``，返回信封里的 ``data``。

    命令的输出是要给用户看的（「查看日志」），所以日志先写、判定后做：命令哪怕
    一个字节都没出，日志文件也已经在了。信封只认 stdout 的**最后一个** JSON ——
    命令在正式结果前会打进度行，那是给人看日志用的，不是给机器读的第二个信封。
    """
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=child_env(),
        )
    except FileNotFoundError as exc:
        _append_log(log_path, f"命令不存在：{cmd[0]}")
        raise WorkspaceError(f"派生命令不存在：{cmd[0]}", "workspace_cmd_unavailable", 503) from exc
    except subprocess.TimeoutExpired as exc:
        _append_log(log_path, f"派生命令超时（{timeout}s）")
        raise WorkspaceError(f"派生命令超时（{timeout}s）", "derive_timeout", 504) from exc
    except OSError as exc:
        _append_log(log_path, f"命令跑不起来：{exc}")
        raise WorkspaceError(f"派生命令跑不起来：{exc}", "workspace_cmd_unavailable", 503) from exc

    _append_log(log_path, "\n".join(p for p in (proc.stdout, proc.stderr) if p))
    envelope = _last_envelope(proc.stdout or "")
    if envelope is None:
        raise WorkspaceError("派生命令没有返回 JSON 信封", "derive_failed", 502)
    if envelope.get("success") is not True:
        message = str(envelope.get("message") or "派生命令失败")
        raise WorkspaceError(message, "derive_failed", 502)
    data = envelope.get("data")
    return data if isinstance(data, dict) else {}


def _last_envelope(stdout: str) -> dict[str, Any] | None:
    """stdout 里最后一个能 parse 成对象的 JSON。倒着按行找，第一个成的就是它。"""
    for line in reversed((stdout or "").splitlines()):
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            parsed = json.loads(stripped)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _append_log(log_path: Path, text: str) -> None:
    if not text:
        return
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(text if text.endswith("\n") else text + "\n")
    except OSError:
        # 日志写不坏主流程：派生本身的成功与否不由日志决定。
        logger.warning("ai-studio workspace log write failed: %s", log_path, exc_info=True)


def log_path_for(project_id: str) -> Path:
    """派生日志路径：项目记录目录下的 ``workspace.log``。"""
    return projects.projects_root() / project_id / LOG_FILE


def log_tail(project_id: str, lines: int = 80) -> list[str]:
    """日志尾巴。没有日志文件是空列表（工作区还没开始建，本来就没有）。"""
    count = lines if isinstance(lines, int) and 0 < lines <= 500 else 80
    try:
        text = log_path_for(project_id).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()[-count:]


def _new_steps() -> list[dict[str, Any]]:
    return [{"name": name, "state": STEP_PENDING, "message": None} for name in STEPS]


def _fail_step_index(message: str, code: str = "derive_failed") -> int:
    """猜前三步里哪一步失败。

    ``code`` 先说话：``derive_failed`` 之外的码（命令不存在、超时）意味着**命令一行
    都没跑成**，那种情况下在 "派生命令不存在：jc" 里搜 ``clone``/``repo`` 是搜个笑话
    —— 一律算第一步，那是唯一真的没发生的动作。

    只有拿到信封里的错误原文时才按词猜。顺序是 :data:`_STEP_MARKERS` 定的：先认
    ``clone``，再认 ``create-repo``/``repo``，都不认就算推送 —— 猜错的最坏结果是「推送」
    这行标红了而其实没推，用户看着错误原文自己知道，重试仍是同一条命令，不会因为标错
    步而做错事。
    """
    if code != "derive_failed":
        return 0
    lowered = (message or "").lower()
    for name, markers in _STEP_MARKERS:
        if any(m in lowered for m in markers):
            return STEPS.index(name)
    return STEPS.index("推送")


def _is_git_repo(path: Path) -> bool:
    """是不是一个 Git 仓（``.git`` 在就行，目录或文件都算 —— worktree 的是文件）。"""
    try:
        return (path / ".git").exists()
    except OSError:
        return False


def _recorded_workspace(project: dict[str, Any]) -> Path | None:
    """记录里那个 workspaceDir 的原样解读（不判存在）。"""
    raw = project.get("workspaceDir")
    if not (isinstance(raw, str) and raw.strip()):
        return None
    return Path(raw.strip())


def _cloned_workspace(project: dict[str, Any]) -> Path | None:
    """记录里的工作区目录，且它是个 Git 仓（重试时判「还需不需要克隆」）。"""
    path = _recorded_workspace(project)
    return path if path is not None and _is_git_repo(path) else None


class WorkspaceJob:
    """一个工作区的派生任务。

    ``runner`` 替 :func:`run_derive`（``(cmd, log_path) -> data``），
    ``devserver_factory`` 替 :func:`devserver.dev_server_for`。两个都能注入是硬性
    要求：真跑要联网、要建远端仓、要起 pnpm，单测一样都不许碰。
    """

    def __init__(
        self,
        project_id: str,
        *,
        runner: Callable[[list[str], Path], dict[str, Any]] | None = None,
        pusher: Callable[[list[str], Path], bool] | None = None,
        devserver_factory: Callable[[dict, Path], Any] | None = None,
    ) -> None:
        self.project_id = project_id
        self._runner = runner if runner is not None else run_derive
        self._pusher = pusher if pusher is not None else run_push
        self._devserver_factory = (
            devserver_factory if devserver_factory is not None else devserver.dev_server_for
        )

    # -- 读写项目记录 ----------------------------------------------------

    def _project(self) -> dict[str, Any]:
        record = projects.get_project(self.project_id)
        if record is None:
            raise WorkspaceError("project not found", "project_not_found", 404)
        return record

    def _set_steps(self, steps: list[dict[str, Any]], **fields: Any) -> None:
        projects.update_project(self.project_id, steps=steps, **fields)

    # -- 跑 --------------------------------------------------------------

    def run(self) -> None:
        """同步跑完四步。路由层用线程跑它，所以这里的每次写盘都是前端会看到的。"""
        project = self._project()
        steps = _read_steps(project)
        try:
            self._derive(project, steps)
            # 派生成功后 workspaceDir/repoUrl 才写进记录，第四步要读**重读**的记录：
            # 拿旧字典过去就是「工作区目录还不存在」，一个假失败。
            self._start_dev_server(self._project(), steps)
        except _HANDLED:
            # 失败状态已经由抛出的那一处写好了，这里只负责让它别再往上冒到线程里。
            raise
        except Exception as exc:  # 没预料到的坏：不能让任务静默停在 creating
            self._crash(steps, exc)
            raise
        self._set_steps(steps, status=STATUS_READY, failedStep=None, message=None)

    def retry(self) -> None:
        """只重试失败的那一步。不是 failed 就拒（409）—— 「全好了你再点重试」是
        界面上的 bug，不该由后端假装成功来配合它。"""
        project = self._project()
        if project.get("status") != STATUS_FAILED:
            raise WorkspaceError("当前不是失败状态", "not_failed", 409)
        steps = _read_steps(project)
        index = _first_failed(steps)
        if index is None:
            # status 说 failed 但没有一步是 failed（记录被手改过）：整条重跑，别猜。
            steps = _new_steps()
            index = 0
        # 失败步之后的步一律回到 pending：它们当时是被这一步连累的，不是自己坏了
        for i in range(index, len(steps)):
            _mark(steps, i, STEP_PENDING, None)
        self._set_steps(steps, status=STATUS_CREATING, failedStep=None, message=None)
        try:
            if index < len(DERIVE_STEPS):
                self._derive(self._project(), steps, resume=True)
            self._start_dev_server(self._project(), steps)
        except _HANDLED:
            raise
        except Exception as exc:
            self._crash(steps, exc)
            raise
        self._set_steps(steps, status=STATUS_READY, failedStep=None, message=None)

    # -- 三步合一：派生命令 ----------------------------------------------

    def _derive(
        self, project: dict[str, Any], steps: list[dict[str, Any]], resume: bool = False
    ) -> None:
        """跑派生命令，或（``resume`` 且工作区已是 Git 仓）只补推一次。

        前三步置 running 是在**跑之前**：一条命令跑一分多钟，期间前端每 2 秒刷一
        次，那三行必须已经是转圈的样子，不然用户看到的是一动不动的 ⏳，以为没在动。
        """
        code = check_code(str(project.get("code") or ""))
        root = workspaces_root()
        log = log_path_for(self.project_id)
        existing = _cloned_workspace(project) if resume else None
        if existing is not None:
            # 目录已在且是 Git 仓：重跑整条命令会撞一个已存在的非空目录（git clone
            # 对这种是 fatal），所以只把缺的推送补上。
            self._resume_push(existing, steps, log)
            return
            # 目录已存在且是 Git 仓：整条命令重跑会撞一个已存在的目录（jc 那边是
            # 报错还是覆盖，取决于它的版本，我们不该赌），只把推送这一步补上。
            self._resume_push(existing, steps, log)
            return

        for i in range(len(DERIVE_STEPS)):
            _mark(steps, i, STEP_RUNNING, None)
        self._set_steps(steps, status=STATUS_CREATING, failedStep=None, message=None)

        cmd = derive_cmd(template_url(), code, devserver.staff_id(), root)
        try:
            data = self._runner(cmd, log)
        except WorkspaceError as exc:
            # 猜是哪一步（只在这三步里猜），错误原文进那一步的 message
            self._fail(steps, _fail_step_index(str(exc), exc.code), str(exc))
            raise
        for i in range(len(DERIVE_STEPS)):
            _mark(steps, i, STEP_DONE, None)
        fields: dict[str, Any] = {}
        target = data.get("target")
        if isinstance(target, str) and target:
            fields["workspaceDir"] = target
        repo = data.get("personalRepo")
        if isinstance(repo, str) and repo:
            fields["repoUrl"] = repo
        self._set_steps(steps, **fields)

    def _resume_push(self, ws: Path, steps: list[dict[str, Any]], log: Path) -> None:
        """重试路径：克隆已在，只补一次推送。

        「建个人仓」在这条路上无从重新判定 —— 能推上去就说明仓在。所以推送成功 =
        前三步全 done，失败 = 「推送」这一步红，错误原文写进它的 message。
        """
        _mark(steps, 0, STEP_DONE, None)
        _mark(steps, 1, STEP_DONE, None)
        index = STEPS.index("推送")
        _mark(steps, index, STEP_RUNNING, None)
        self._set_steps(steps)
        if not self._pusher(push_cmd(ws), log):
            detail = "git push 失败，见工作区日志"
            self._fail(steps, index, detail)
            raise WorkspaceError(detail, "derive_failed", 502)
        _mark(steps, index, STEP_DONE, None)

    def _fail(self, steps: list[dict[str, Any]], index: int, detail: str) -> None:
        """一步失败：该步带上错误原文，之前的步算过，之后的步回 pending。

        「之前的步算过」不是乐观 —— 派生命令是顺序做完前三步的，它能报出建仓失败
        就等于克隆已经成功了；把克隆留在 running 会让界面上永远有两个转圈。
        """
        message = _fail_message(steps[index]["name"], detail)
        for i in range(index):
            if steps[i]["state"] != STEP_DONE:
                _mark(steps, i, STEP_DONE, None)
        _mark(steps, index, STEP_FAILED, message)
        for i in range(index + 1, len(steps)):
            _mark(steps, i, STEP_PENDING, None)
        self._set_steps(
            steps, status=STATUS_FAILED, failedStep=steps[index]["name"], message=message
        )

    def _crash(self, steps: list[dict[str, Any]], exc: Exception) -> None:
        """没被归到某一步的坏（写记录失败、工厂自己炸了）。

        兜底只为一件事：**不许让一个已经没有线程的任务停在 creating** —— 那在界面
        上是一个永远转圈、又点不动重试的死项目。
        """
        logger.exception("ai-studio workspace job crashed: %s", self.project_id)
        index = _first_unfinished(steps)
        if index is None:
            index = len(steps) - 1
        try:
            self._fail(steps, index, str(exc) or exc.__class__.__name__)
        except Exception:
            logger.exception("ai-studio workspace failure could not be recorded")

    # -- 第四步：起开发服务器 --------------------------------------------

    def _start_dev_server(self, project: dict[str, Any], steps: list[dict[str, Any]]) -> None:
        """起开发服务器这一步。

        :meth:`devserver.DevServer.start` 只是落一条 starting 就返回（真起进程在
        它自己的后台线程里），所以这一步**当场就算 done** —— 它后面成不成由
        dev-server 自己的状态说话（顶栏那个按钮看的就是它），这一步不替它负责。
        """
        index = STEPS.index("启动开发服务器")
        _mark(steps, index, STEP_RUNNING, None)
        self._set_steps(steps)
        ws = _recorded_workspace(project)
        if ws is None:
            detail = "工作区目录还不存在，先重试前三步"
            self._fail(steps, index, detail)
            raise WorkspaceError(detail, "workspace_missing", 502)
        try:
            server = self._devserver_factory(project, ws)
            server.start()
        except devserver.DevServerError as exc:
            self._fail(steps, index, str(exc))
            raise
        _mark(steps, index, STEP_DONE, None)


def push_cmd(ws: Path) -> list[str]:
    """补推送的命令。重试时用它，而不是重跑整条派生命令。"""
    return ["git", "-C", str(ws), "push", "-u", "origin", "develop"]


def run_push(cmd: list[str], log_path: Path) -> bool:
    """跑一条 git 推送，输出追加进日志，返回是否成功（退出码 0）。"""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_PUSH_TIMEOUT_S,
            check=False,
            env=child_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _append_log(log_path, f"git push 跑不起来：{exc}")
        return False
    _append_log(log_path, "\n".join(p for p in (proc.stdout, proc.stderr) if p))
    return proc.returncode == 0


def _read_steps(project: dict[str, Any]) -> list[dict[str, Any]]:
    """记录里的 steps，形状不对就当没有（重建四步全 pending）。"""
    raw = project.get("steps")
    if not isinstance(raw, list):
        return _new_steps()
    out: list[dict[str, Any]] = []
    for one in raw:
        if not isinstance(one, dict) or one.get("name") not in STEPS:
            return _new_steps()
        state = (
            one.get("state")
            if one.get("state")
            in (
                STEP_PENDING,
                STEP_RUNNING,
                STEP_DONE,
                STEP_FAILED,
            )
            else STEP_PENDING
        )
        message = one.get("message")
        out.append(
            {
                "name": str(one["name"]),
                "state": state,
                "message": message if isinstance(message, str) else None,
            }
        )
    return out or _new_steps()


def _mark(steps: list[dict[str, Any]], index: int | None, state: str, message: str | None) -> None:
    if index is None or not (0 <= index < len(steps)):
        return
    steps[index] = {"name": steps[index]["name"], "state": state, "message": message}


def _first_failed(steps: list[dict[str, Any]]) -> int | None:
    for i, one in enumerate(steps):
        if one["state"] == STEP_FAILED:
            return i
    return None


def _first_unfinished(steps: list[dict[str, Any]]) -> int | None:
    for i, one in enumerate(steps):
        if one["state"] != STEP_DONE:
            return i
    return None


def _fail_message(step: str, detail: str) -> str:
    """RFC §8 的原文格式：「<步骤名>失败：<错误原文>」。"""
    return f"{step}失败：{detail}"


# 路由层用同一个 job 管理器起线程：同一项目同时只允许一个派生线程在跑，
# 否则前端连点两次创建就会有两个线程抢同一份 project.json。
_JOBS: set[str] = set()
_JOBS_LOCK = threading.Lock()


def start_job(project_id: str, *, job: WorkspaceJob | None = None, retry: bool = False) -> None:
    """后台起一个派生线程。已经在跑的同一个项目不再起第二个（幂等）。"""
    with _JOBS_LOCK:
        if project_id in _JOBS:
            return
        _JOBS.add(project_id)

    def _target() -> None:
        try:
            work = job if job is not None else WorkspaceJob(project_id)
            if retry:
                work.retry()
            else:
                work.run()
        except Exception:
            # 状态已经由 job 自己写成 failed 了；这里只是别把 traceback 咽了。
            logger.exception("ai-studio workspace job failed: %s", project_id)
        finally:
            with _JOBS_LOCK:
                _JOBS.discard(project_id)

    threading.Thread(target=_target, daemon=True, name=f"ai-studio-ws-{project_id}").start()


def job_running(project_id: str) -> bool:
    with _JOBS_LOCK:
        return project_id in _JOBS
