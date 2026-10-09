"""开发运行的调度循环（ACP-2085-S4 第 2 步，ACP-2207 起可并行）。

一个 ``DevRun`` = 一个项目的一轮开发：把 ``devplan.build_plan`` 算出的任务跑完，
每个任务**开一个助手会话**发一轮，看板上就是这些节点的状态。

和 07 设计文档（``raw/ai-studio-acceptance/07-dev-dag-two-phase.md``）的差别是
本步有意为之的最小可用版，别照文档把它「补全」：

* 只有一个阶段 ``full``：不做演示版/完整版两阶段、不打 git tag、不做回退。节点上的
  ``jiraKey`` 起初只是任务 id 的字段名，ACP-2085-S6 之后才真的挂上 Jira 子单。
* **并行度受 ``AI_STUDIO_DEV_PARALLEL`` 管（默认 2，ACP-2207）**：一轮里同时最多
  跑这么多个「依赖全 done」的节点，每个并行节点一个 git worktree（见
  :func:`worktree_add`），跑完在**主目录** ``merge --no-ff``。设成 1 就是旧的串行，
  一个 worktree 都不建。
* **串行后继不复用前驱的 worktree**（ACP-2207 有意偏离 07 §四-2「串行复用」）：后继
  等前驱**合进主目录**之后，从合并后的主目录 HEAD 新开一个。复用同一棵目录树省不下
  什么（一次 ``worktree add`` 是秒级），代价却是两条说不清的语义：前驱的未提交改动
  会漏进后继的工作现场，而前驱失败留下的现场（「保留供人看」）会被后继踩掉。合并点
  才是这一单认的交接面 —— 看板上一个节点转「完成」的**那一刻**，它的代码已经在主
  目录的历史里，下一个节点从那儿起步，谁也不用猜对方留在目录里的是什么。
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
import re
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

#: 一轮里最多同时跑几个节点（ACP-2207）。默认 2，照 07 §四 的并行度峰值。
#: **设成 1 就是旧的串行**：一个 worktree 都不建，节点直接在工作区主目录里写，
#: 这一版的看板行为与并行改造之前逐字相同 —— 所以「退回串行」不是一条特判，
#: 而是「并行度 1 时永远只有一个节点在跑，也就没有同目录并写这回事」。
#: 上限 8 是护栏不是设计：会话数每加一个就多一个 ACP 子进程 + 一份 pnpm install，
#: 当晚实测几个会话同时跑就把机器压垮过（见 :mod:`devplan` 的「不跑测试」那条）。
PARALLEL_ENV = "AI_STUDIO_DEV_PARALLEL"
DEFAULT_PARALLEL = 2
MAX_PARALLEL = 8

#: 一个并行节点的 worktree 放在工作区的这个子目录下（``.ai-studio/wt/<序号>``）。
#: 跟着工作区走而不是放临时目录：节点失败留下现场时，人就在同一个工作区里找得到它。
WORKTREE_SUBDIR = ".ai-studio/wt"


def parallel_limit(raw: str | None = None) -> int:
    """本轮的并行度：``AI_STUDIO_DEV_PARALLEL``，读不出来就按 :data:`DEFAULT_PARALLEL`。

    0、负数、非数字统统退回默认，不退回 1：把它读成 1 等于「配置写错了 ⇒ 悄悄变
    串行」，那是把一个没人察觉的性能改动塞进一次拼写错误里；退回默认至少是这一版
    声明过的行为。
    """
    text = (os.environ.get(PARALLEL_ENV, "") if raw is None else raw).strip()
    if not text:
        return DEFAULT_PARALLEL
    try:
        n = int(text)
    except ValueError:
        return DEFAULT_PARALLEL
    if n < 1:
        return DEFAULT_PARALLEL
    return min(n, MAX_PARALLEL)


def branch_name(node_key: str) -> str:
    r"""一个节点的任务 id → 它的分支名 ``dev/<小写短横线>``。

    「小写短横线」只管有大小写可言的那一半：任务 id 的页名是中文，中文没有大小写，
    而把它一起换成短横线会让「设备点检记录:api」和「备件台账:api」塌成同一条分支
    —— 两个并行节点共用一条分支就是共用工作，正是这一单要消灭的事。所以：ASCII 转
    小写、下划线先换成短横线（它是 ``\w``，不先换就会被原样留下）、其余不是字母也
    不是数字的一律换成短横线（``:`` ``/`` 空格都是 git 不接受或难读的写法），中文
    原样保留（git 分支名允许 UTF-8，看板上一眼认得出是哪一页）。
    """
    cleaned = str(node_key).lower().replace("_", "-")
    slug = re.sub(r"[^\w-]+", "-", cleaned).strip("-")
    return f"dev/{slug or 'node'}"


def worktree_path(ws: Path, index: int) -> Path:
    """第 ``index``（0 起）个节点的 worktree 目录：``<工作区>/.ai-studio/wt/<序号>``。

    按**节点序号**而不是按任务 id 命名，和 slot 名同一条规则（``ai-studio-dev-<项目>-<序号>``）：
    看板上第几行、会话名、目录名是同一个序号，人排查时不用换算。
    """
    return Path(ws) / WORKTREE_SUBDIR / str(index + 1)


class GitOpError(Exception):
    """一条 git 命令没办成，带 git 自己那句话（原文，看板/日志照抄）。"""

    def __init__(self, message: str, conflict_files: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.conflict_files = conflict_files


def _git_run(repo: Path, args: list[str], timeout: int = 120) -> tuple[int, str]:
    """工作区里跑一条 git，回 ``(returncode, stdout+stderr 合并原文)``。

    合并两路：git 把进度和报错都往 stderr 写（``git worktree add`` 的
    ``Preparing worktree ...`` 就在 stderr），只看 stdout 会把「它说了什么」丢掉。

    **那句原文只能给人看，不能拿来做判断。** git 按 ``LC_MESSAGES`` 决定它说什么话：
    本机 ``LANG=zh_CN.utf8``，实测 ``git worktree add -b`` 撞见已有分支回的是
    ``fatal: 一个名为 'dev/x' 的分支已经存在``，``git status`` 还会把中文路径转成
    ``"\\350\\256\\276..."`` 那样的八进制。所以本模块判断一律只看退出码，要文件名单就
    用 ``diff --name-only --diff-filter=U``，一个英文子串都不匹配 —— 匹配英文子串的
    写法在英文机器上全绿、在中文部署机上静默失效，测试也照过。
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitOpError(f"git {' '.join(args)} 起不来：{type(exc).__name__}: {exc}") from exc
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


#: worktree 那一棵树对工作区自己是垃圾，但对 git 不是：模板的 ``.gitignore`` 里没有
#: ``.ai-studio/``，所以第二棵树建出来之后主目录的 ``git status`` 会多出整份代码的
#: 副本 —— 助手一句 ``git add -A`` 就能把另一个节点的现场当成自己的成果提交进去。
#: 写 ``.git/info/exclude`` 而不是 ``.gitignore``：前者是本地账本，不进版本库、不
#: 进发布包、也不改任何被跟踪的文件（改 ``.gitignore`` 本身就是把主目录改脏）。
#: 只 Ignore worktree 那一格，不 Ignore 整个 ``.ai-studio/``：同目录下还放着需求文档
#: （验收的事实源，要跟着代码一起进仓一起推），一把梭会把它们挡在提交之外。
_LOCAL_EXCLUDE_ENTRY = f"/{WORKTREE_SUBDIR}/"


def _git_dir(repo: Path) -> Path:
    """``<工作区>/.git``（普通克隆）。取不到就回工作区里那个 ``.git`` 的原样路径。"""
    rc, out = _git_run(repo, ["rev-parse", "--absolute-git-dir"], timeout=20)
    if rc != 0:
        return Path(repo) / ".git"
    row = out.strip().splitlines()
    return Path(row[-1]) if row else Path(repo) / ".git"


def ensure_local_exclude(repo: Path) -> None:
    """确保 ``.git/info/exclude`` 里 Ignore 得掉 ``.ai-studio/``（幂等，坏了自己咽）。

    只追加一行本地忽略，不做别的：它既不改被跟踪文件（改 ``.gitignore`` 会把主目录
    改脏，而每次合并前主目录都得是干净的），也不会被推到远端 —— 操作员的仓库里凭
    空多出一条我们发明的规则，那是我们的事不是他的。
    """
    try:
        git_dir = _git_dir(Path(repo))
        exclude = git_dir / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        existing = (
            exclude.read_text(encoding="utf-8", errors="replace") if exclude.is_file() else ""
        )
        have = any(line.strip() == _LOCAL_EXCLUDE_ENTRY for line in existing.splitlines())
        if have:
            return
        with exclude.open("a", encoding="utf-8") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            fh.write(_LOCAL_EXCLUDE_ENTRY + "\n")
    except OSError:
        # 忽略规则没写成，最坏是主目录脏一点；为此让一个任务开工就失败是本末倒置。
        logger.warning("ai-studio could not write .git/info/exclude", exc_info=True)


def worktree_add(repo: Path, path: Path, branch: str, base: str) -> None:
    """从 ``base``（主目录当前 HEAD）拉出 ``branch``，检出到 ``path``。

    先试带 ``-b`` 的那条，失败就退回「直接检出已有分支」那一条：续跑同一轮时分支
    已经在了，再 ``-b`` 只会回一句「分支已经存在」，于是同一个节点第二次永远开不出
    现场。

    **退回的判据是「第一条没成」，不是「git 那句话里有没有 already exists」。**
    曾经写的就是后者，本机 ``LANG=zh_CN.utf8`` 下实测永远不成立 —— git 回的是
    ``fatal: 一个名为 'dev/x' 的分支已经存在``，英文子串匹配不上，续跑在中文部署机上
    100% 报「建 worktree 失败」，而英文 CI 全绿。两条命令各管一种现场，第二条自己
    会决定成不成；真失败时把两条的原文一起带上，人能看到的是最后那次为什么没成。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    rc, out = _git_run(repo, ["worktree", "add", "-b", branch, str(path), base or "HEAD"])
    if rc == 0:
        return
    rc2, out2 = _git_run(repo, ["worktree", "add", str(path), branch])
    if rc2 == 0:
        return
    raise GitOpError(_git_failure("worktree add", f"{out}\n{out2}"))


def worktree_list(repo: Path) -> dict[str, str]:
    """已登记的 worktree：``{路径: 该目录当前分支}``（读不出来就是空表，不抛）。

    用 ``--porcelain`` 而不是 ``git worktree prune`` 那类副作用命令：这一版只想知道
    有什么，不改什么。
    """
    rc, out = _git_run(repo, ["worktree", "list", "--porcelain"], timeout=30)
    if rc != 0:
        return {}
    found: dict[str, str] = {}
    path = ""
    for row in out.splitlines():
        if row.startswith("worktree "):
            path = row[len("worktree ") :].strip()
        elif row.startswith("branch ") and path:
            found[path] = row[len("branch ") :].strip().removeprefix("refs/heads/")
            path = ""
    return found


def worktree_reusable(repo: Path, path: Path, branch: str) -> bool:
    """这个目录已经是检出 ``branch`` 的 worktree，可以直接续着用。

    为什么要有这一步：上一轮合并冲突的节点**留下了** worktree（「保留供人看」），
    续跑时同一个节点同一个序号同一个路径，``git worktree add`` 只会回一句
    ``fatal: '<路径>' 已经存在``（英文 locale 下是 ``already exists``）—— 于是「人把
    冲突解完了、点了重试」这一条最应该能走通的路被永久堵死。所以这里**问 git 有什么**
    （``worktree list --porcelain``）而不是**听 git 说什么**：前者是数据，后者换语言就变。
    分支对不上就不复用：宁可让它报建 worktree 失败，也不要在别人的分支上写这一条任务的代码。
    """
    return worktree_list(repo).get(str(path)) == branch


def worktree_abort(repo: Path) -> None:
    """把主目录退回合并之前的样子（``git merge --abort``，失败不抛）。"""
    try:
        _git_run(repo, ["merge", "--abort"], timeout=60)
    except GitOpError as exc:
        logger.warning("ai-studio merge abort failed: %s", exc)


def worktree_merge(repo: Path, branch: str, label: str) -> None:
    """在**主目录**里 ``merge --no-ff <branch>``。

    ``--no-ff`` 是这一单的形态而非形式：一个任务一个合并节点，看板上第 3 行对应
    git 图里第 3 个 merge，失败要回退也是回退那一个。快进合并会把两条线拧成一条
    直线，事后分不清哪个提交属于哪个任务。

    冲突 → :class:`GitOpError`，``conflict_files`` 是 git 报的那几个文件（取自
    ``git diff --name-only --diff-filter=U``，比从 merge 的 stdout 里猜稳 —— 后者
    按 locale 换语言）。这份名单要原样进看板那句「合并冲突：<文件>」，所以带
    ``-c core.quotePath=false``：模板的页名是中文，默认输出会把「设备台账.txt」变成
    ``"\\350\\256\\276\\345\\244\\207..."``，实测过 —— 人看到八进制就等于没看到文件名。

    冲突之后**把主目录 abort 回原样**，这是刻意反着「留在冲突态更直观」的直觉做的：
    主目录是这一轮唯一的公共目录，停在半合并状态时〔预览〕端看到的是两个任务混在
    一起的代码、下一个节点的 ``merge`` 会撞一句看不出所以然的「concluded your
    merge」、而〔开始开发〕之外没人能推进。现场不靠它保存 —— **分支和 worktree 都
    在原地**（``.ai-studio/wt/<序号>``），人 ``cd`` 进去 ``git log``/``git diff``
    看得完，而「保留 worktree 供人看」正是这一单写死的那句话。
    """
    rc, out = _git_run(repo, ["merge", "--no-ff", "-m", f"Merge {branch} ({label})", branch])
    if rc == 0:
        return
    _, listed = _git_run(
        repo,
        ["-c", "core.quotePath=false", "diff", "--name-only", "--diff-filter=U"],
        timeout=30,
    )
    conflict = tuple(f for f in listed.splitlines() if f.strip())
    worktree_abort(repo)
    raise GitOpError(_git_failure("merge", out), conflict)


def worktree_remove(repo: Path, path: Path) -> None:
    """收掉一个用顺了的 worktree（成功节点）。失败不抛：目录留在盘上是磁盘问题，
    不是这一轮开发的结论，喊出来只会把一个跑完的轮次报成坏的。"""
    try:
        _git_run(repo, ["worktree", "remove", "--force", str(path)], timeout=60)
    except GitOpError as exc:
        logger.warning("ai-studio worktree remove failed: %s", exc)


def _git_failure(what: str, out: str) -> str:
    """git 的原文，砍掉头尾空行，最多留最后 5 行。

    「失败」这一行要进看板，而看板上那一格是 ``whitespace-pre-wrap break-all``：
    一次 merge 的 stdout 可以有几十行（每个冲突文件一行 + 一堆 hint），全贴上就把
    整块板撑走了。最后几行才是 git 说「怎么解决」的那段。
    """
    rows = [r for r in (out or "").splitlines() if r.strip()]
    return "\n".join(rows[-5:]) if rows else f"git {what} 失败（无输出）"


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
        git_at: Callable[[Path], str] | None = None,
        clock: Callable[[], float] | None = None,
        fail_point: str = "",
    ) -> None:
        self.state = state
        self.project = project
        self.ws = Path(ws)
        self.fail_point = fail_point
        self._dispatch = dispatcher or dispatch_and_read
        self._git = git if git is not None else (lambda: git_head(self.ws))
        # 一个 worktree 的 HEAD：并行节点在**它自己的目录**里提交，主目录的 HEAD 在
        # 合并之前根本不动。所以判「这个节点有没有真交付」必须读它自己那一份，
        # 读主目录会把每个并行节点都判成「回复说完成了，但没有新提交」。
        # 没传 `git_at` 但传了 `git` 时**跟着 `git` 走**，不能默认成真的 ``git_head``：
        # 注入一个假 HEAD 却在判交付时偷偷去跑真 git，等于把一个测试的替身换成真环
        # 境 —— 单测的工作区是 tmp 目录、不是仓，真 git 永远回空串，于是一个好好的
        # 串行测试会莫名判成「回复说完成了，但没有新提交」。真按目录区分 HEAD 的
        # 用例（并行那几条）自己传 `git_at`，这也是「这条断言看得见目录」的证据。
        if git_at is not None:
            self._git_at: Callable[[Path], str] = git_at
        elif git is not None:
            self._git_at = lambda _path: self._git()
        else:
            self._git_at = git_head
        self._clock = clock if clock is not None else time.time
        self._loop_task: asyncio.Task[Any] | None = None
        # 合并串行化：两个并行节点同时成功时会在同一个 `.git` 上各合一次，而 git 的
        # index.lock 只容得下一个。谁先合无所谓，一起冲上去只会让第二个报错失败。
        self._merge_lock = asyncio.Lock()

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
                    # 上一轮的现场不能跟到这一轮来：冲突留下的 worktree 路径会一直挂
                    # 在这一行上，而这一轮它还没有目录。清掉之后「这一轮有没有目录」
                    # 就等于「worktree 这一格空不空」，看板和读文件的人是同一个判据。
                    "worktree": "",
                    "branch": "",
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
        """按顺序取第一个 queued 且依赖全 done 的节点（并行度 1 时的老写法）。"""
        runnable = self._runnable(data)
        return runnable[0] if runnable else None

    def _runnable(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """本轮现在就能派出去的节点（queued 且依赖全 done），保持计划顺序。

        依赖只看 ``done``：合并冲突的节点是 ``failed``，它的后继因此永远排不进
        来 —— 一个没合进去的后端接口，前端拿什么调。
        """
        done = {n.get("jiraKey") for n in data["nodes"] if n.get("state") == "done"}
        return [
            node
            for node in data["nodes"]
            if node.get("state") == "queued"
            and all(dep in done for dep in (node.get("dependsOn") or []))
        ]

    async def _loop(self) -> None:
        """并行调度（ACP-2207）：同时在跑的节点数不超过 ``AI_STUDIO_DEV_PARALLEL``。

        ``data`` 是**这一轮唯一的内存状态**，循环读它一次、每个节点改同一个对象、
        每次改动整体落盘。之前每轮从盘上重读，是因为串行循环是当时的唯一写者而它
        自己也在写；并行之后依然只有一个写者（这个循环），但「读-改-写」不再是原子的
        —— 两个节点各拿一份快照再各自落盘，后落的那一份会把先落的那个节点的状态
        抹掉（看板上一个已经「完成」的节点会退回「进行中」）。所以改成共享一份，
        而不是给落盘加合并逻辑：一个事实只有一个持有者。

        有节点失败时**不收正在跑的兄弟节点**：它们的会话正在自己的 worktree 里写
        代码，取消等于把已经写的丢掉、还把分支留在半提交状态。只是不再派新的，
        在跑的跑完各归各的状态，整轮仍以 ``failed`` 收口（07 场景 D2「不许假全绿」）。
        """
        project_id = str(self.project.get("id") or self.ws.name)
        limit = parallel_limit()
        data = self._data()
        running: set[asyncio.Task[Any]] = set()
        while True:
            # 有节点判失败就不再派新节点（07 D2「不许假全绿」），但**不取消**正在
            # 跑的兄弟：它们的会话正在自己的 worktree 里写代码，取消等于把已经写的
            # 丢掉、把分支留在半提交状态。让它们各归各的状态，整轮仍以 failed 收口。
            if data.get("runState") != "failed":
                for node in self._runnable(data):
                    if len(running) >= limit:
                        break
                    # 派出去就地置 running 并落盘。置位在循环这里而不是协程里，因为
                    # ``_runnable`` 只认 queued：协程要等事件循环调度才开跑，等它再置位
                    # 就等于「这一轮到底派了几个」取决于调度时机。落盘也是同一件事的
                    # 下半：从「决定派它」起，这个节点在这份文件里就是 running —— 包
                    # 括接下来建 worktree 的那几秒。断在那里的话，看板说它「中断」（会
                    # 重试它），而不是说它「从没开始过」（而盘上已经有一个目录和一条
                    # 分支了，那更糟）。
                    node["state"] = "running"
                    self._save(data)
                    running.add(
                        asyncio.ensure_future(
                            self._run_node(data, node, project_id, parallel=limit > 1)
                        )
                    )
            if not running:
                self._close_run(data)
                return
            finished, running = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            # 节点的**结局**（done/failed + 原因）由它自己落盘，循环不看它；能冒到
            # 这里的只有没被 :meth:`_run_node` 兜住的异常 —— 注入崩溃（``fail_point``
            # 模拟网关重启）和落盘失败这类。它们必须**终止整轮**，和改造前逐字相同：
            # 串行时异常直接从循环里冒出去，``_run_safe`` 把整轮判 failed。并行之后
            # 它躲在 task 里，不取出来的话 asyncio 只会析构时打一句「Task exception
            # was never retrieved」，而看板还在转圈 ——「进程没了」这个现场就这么被
            # 吞掉了，而它正是那套孤儿改判（:meth:`get`）唯一的入口。
            for task in finished:
                exc = task.exception()
                if exc is not None:
                    for other in running:
                        other.cancel()
                    if running:
                        await asyncio.wait(running)
                    raise exc

    def _close_run(self, data: dict[str, Any]) -> None:
        """没有可派的也没有在跑的了：按节点状态给整轮一个结论。

        三种结局和串行那一版逐字同义：全 done 才是 done；有 failed 就是 failed
        （**不许假全绿**，后继保持 queued）；既没有 failed 又派不出东西，是状态文件
        被改坏了或依赖成环，如实标 failed，不许转圈。
        """
        states = {n.get("state") for n in data["nodes"]}
        if states <= {"done"}:
            data["runState"] = "done"
            self._save(data)
            self._log("run done", "")
            return
        data["runState"] = "failed"
        self._save(data)
        if "failed" not in states:
            self._log("no runnable node, stopping", "")

    async def _run_node(
        self,
        data: dict[str, Any],
        node: dict[str, Any],
        project_id: str,
        *,
        parallel: bool = False,
    ) -> None:
        """跑一个任务节点，全程只改 ``node`` 这一份状态并落盘。

        ``parallel`` 是「本轮并行度 > 1」（由 :meth:`_loop` 传的）：为真时这个节点
        在**自己的 worktree** 里写代码，跑完在主目录合并；为假时和改造前逐字相同
        —— 会话的 cwd 就是工作区主目录，一个 worktree 都不建。「退回串行」因此
        不是一条特判分支，而是少做几件事。
        """
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
        # 会话的工作目录：并行时是它自己的 worktree，串行时就是主目录。开工之前先定
        # 下来，因为 ``startCommit`` 也要读**这个**目录的 HEAD（并行时那一个和主目录
        # 的是同一个提交，刚拉出来还没人动过）。
        cwd = self.ws
        node["worktree"] = ""
        if parallel:
            cwd = worktree_path(self.ws, index)
            branch = branch_name(key)
            # 三条 git 都是子进程：并行时事件循环上有另一个节点正在等它的会话，一秒
            # 都不能占（一次 worktree add 在真实工作区里是几秒）。
            await asyncio.to_thread(ensure_local_exclude, self.ws)
            reusable = await asyncio.to_thread(worktree_reusable, self.ws, cwd, branch)
            if not reusable:
                try:
                    await asyncio.to_thread(
                        worktree_add, self.ws, cwd, branch, str(node["startCommit"] or "")
                    )
                except GitOpError as exc:
                    await self._set_failed(data, node, f"建 worktree 失败：{exc}")
                    return
            node["worktree"] = str(cwd)
            node["branch"] = branch
        self._save(data)
        self._log("node start", key)
        if parallel:
            # 07 §三 B3 要日志里有「worktree 分配事件」，且要能和 §四 的实测路径互证
            self._log(f"worktree={cwd} branch={node['branch']}", key)
        # 开工先把 Jira 子单推到「进行中」（名字可覆盖，见 jirasync.doing_state）。
        # 放在开会话之前：单子没流转到是记账的事，而会话开不开得出来是这条活干不
        # 干得了的事，两件事不要互相等。
        await self._jira_transition(node, jirasync.doing_state())
        self._save(data)

        slot_name = f"ai-studio-dev-{project_id}-{index + 1}"
        try:
            slot = open_slot(self.state, slot_name, cwd, str(node.get("title") or key))
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
        # 交付判定看**会话写代码的那个目录**：并行时它是 worktree，主目录的 HEAD 在
        # 合并之前根本不动。拿主目录的 HEAD 判，每个并行节点都会被写成「回复说完成了，
        # 但没有新提交」。串行时 cwd 就是主目录，这一行和改造前取的是同一个 HEAD。
        end_commit = self._git_at(cwd)
        node["endCommit"] = end_commit
        said_done = last_line.startswith("完成")
        committed = bool(end_commit) and end_commit != node.get("startCommit")
        if committed and said_done:
            if parallel:
                # 活干完了，但还只在这个节点的分支上 —— 没合进主目录的代码对下一个
                # 任务、对〔预览〕、对发布都不存在。合并之后才配「完成」这两个字。
                merged = await self._merge_node(data, node, cwd)
                if not merged:
                    return
            else:
                node["state"] = "done"
                node["message"] = ""
                self._save(data)
                self._log(f"done commit={end_commit[:8]}", key)
        else:
            # 两个条件不一致时，光回显助手那句话会把看板写成「失败 / 完成」——那种
            # 现场恰恰最需要说清是哪一半没成立。
            if said_done and not committed:
                node["message"] = "回复说完成了，但没有新提交"
            else:
                node["message"] = last_line
            await self._set_failed(data, node, None)
            return
        # 单子跟着落：先流转再评论，评论里带提交号 —— 在 Jira 里点开单子就能
        # 看到这一条是哪一次提交（看板只是它的投影）。两次调用都可能往节点上
        # 记 jiraError，所以完事再存一次盘。
        await self._jira_transition(node, jirasync.done_state())
        await self._jira_comment(node, f"完成，提交 {end_commit[:8]}")
        self._save(data)

    async def _merge_node(self, data: dict[str, Any], node: dict[str, Any], cwd: Path) -> bool:
        """把这个节点的分支合回主目录，True = 节点已完成（False = 判失败）。

        冲突的写法照派工单：该节点 failed，message「合并冲突：<文件>」。**worktree
        留着**（只 ``merge --abort`` 回干净树）—— 现场就在 ``.ai-studio/wt/<序号>``，
        人 cd 进去就能看这一条到底改了些什么；自动收干净等于把现场抹了。
        """
        key = str(node.get("jiraKey") or "")
        async with self._merge_lock:
            try:
                await asyncio.to_thread(worktree_merge, self.ws, str(node.get("branch") or ""), key)
            except GitOpError as exc:
                files = "、".join(exc.conflict_files) or str(exc)
                self._log(f"merge conflict files={len(exc.conflict_files)}", key)
                await self._set_failed(data, node, f"合并冲突：{files}")
                return False
        # 合并提交是这一条任务真正的交付物（分支上的提交在主目录的历史里看不全），
        # 所以 ``endCommit`` 改成合并之后的 HEAD —— 看板上这一行显示的提交，就是
        # ``git log`` 里那个把这条任务带进主干的合并。
        node["endCommit"] = self._git()
        node["state"] = "done"
        node["message"] = ""
        # 只有合干净了才收得掉（--force 连未跟踪文件一起清）；失败的留下。放线程里
        # 跑：``git worktree remove`` 要删整棵树，几百上千个文件，占用事件循环会让
        # 另一个正在跑的节点连日志都写不出来。
        await asyncio.to_thread(worktree_remove, self.ws, cwd)
        node["worktree"] = ""
        self._save(data)
        self._log(f"merged {node.get('branch', '')}", key)
        return True

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
