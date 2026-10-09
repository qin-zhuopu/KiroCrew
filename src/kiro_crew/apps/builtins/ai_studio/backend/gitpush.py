"""把当前分支推到远端（ACP-2218）。

现象是记账缺口而不是 git 故障：开发轮次把代码提交在工作区本地，部署也打了 ``v<N>``
标签并把标签推了上去，**分支本身一次都没推** —— 别人 clone 个人仓只看到模板那一版，
``develop`` 停在起点。打标签那条路推的是 ``origin <tag>``，它只搬那一个提交对象，
不会搬分支引用，所以「推过东西」和「推过代码」是两件事。

单独成模块而不是塞进 ``devdag``：调用点跨两个模块（``devdag`` 的开发轮次收尾、
``prodserver`` 的部署成功路径），而这两处谁也不该为了推一次代码去 import 对方的
git 函数 —— ``devdag`` 的那一组（``worktree_*``、``_git_run``）语义是 worktree
调度，把「推分支」放进去等于让 ``prodserver`` 依赖调度器。

推的是**当前分支**（``rev-parse --abbrev-ref HEAD`` + ``push origin HEAD:<分支>``）
而不是写死 ``develop``：工作区在哪个分支上就推哪个，个人仓的默认分支叫 ``main``
的部署、以及并行节点合完仍然停在 ``dev/*`` 的现场，都不需要这里再猜一次。
``HEAD:`` 而不是分支名，是为了让「推的就是当前检出的那个提交」这句话由 git 自己
保证，中间没有人有机会把名字和提交搞拧。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from kiro_crew.apps.builtins.ai_studio.backend import devserver

#: 一次推送的天花板。一次分支推送在个人仓上是秒级，真跑满 120 秒更像是网络在
#: 握手阶段挂住（凭据提示、远端不可达），而那正是下面 ``GIT_TERMINAL_PROMPT`` 要
#: 断掉的那一类等待 —— 没有它，git 会开一个 tty 问用户名，父进程这边只能干等。
PUSH_TIMEOUT_S = 120

#: 问一次「当前在哪个分支」的天花板：本地读，秒级；等满就是仓库被别的进程锁住。
_BRANCH_TIMEOUT_S = 20


def child_env_without_prompt() -> dict[str, str]:
    """子进程环境：**不挂代理**，且禁止 git 找人要凭据。

    代理是刻意剥掉的（沿用 :func:`devserver.child_env`，它的剥除清单里有
    ``HTTP(S)_PROXY``）：个人仓多半在内网或需要直连，挂了本机那条 SOCKS 反而不通。
    ``GIT_TERMINAL_PROMPT=0`` 是让 git 在缺凭据时**直接报错**而不是开一个 tty
    问用户名 —— 后者在这里没人回答，只会把 120 秒等满。
    """
    return devserver.child_env({"GIT_TERMINAL_PROMPT": "0"})


def _run(ws: Path, args: list[str], timeout: int) -> tuple[int, str]:
    """``git -C <ws> …``，回 ``(退出码, stdout+stderr 合并原文)``。

    两路合并：git 把进度写在 stdout、报错写在 stderr，只看一路会把「它说了什么」
    丢掉（``push`` 的 ``Everything up-to-date`` 在前者，被拒的原因在后者）。
    与 :func:`devdag._git_run` 同一条纪律：**那句原文只给人看，不参与判断** ——
    本机 ``LANG=zh_CN.utf8`` 下 git 说中文，任何英文子串匹配在部署机上都会静默失效。
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(ws), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=child_env_without_prompt(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, f"git {' '.join(args)} 起不来：{type(exc).__name__}: {exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def push_branch(
    ws: Path,
    log: Callable[[str], None],
    run: Callable[[list[str]], tuple[int, str]] | None = None,
) -> bool:
    """把工作区当前分支推到 ``origin``，回是否推成。

    ``run`` 是跑 git 的那一条（``argv -> (退出码, 合并原文)``）：默认走本模块的真
    子进程，``prodserver`` 传的是它自己那条可注入的 :meth:`ProdServer._run_git` ——
    共用的是**判断与措辞**（哪个分支、detached 怎么办、日志长什么样），不是子进程。
    没有这一位，``prodserver`` 的单测就得靠真 git 才能验「先推分支再推标签」的顺序。

    **永不抛异常**：调用它的是「开发跑完」「部署跑通」之后的收尾，代码已经在盘上、
    服务已经在跑，一个推不出去的分支（远端没配凭据是常态）不该把整轮开发判失败、
    更不该把一套起来的正式服务器报成部署失败。失败只写日志。

    ``log`` 是调用方的写日志入口（``devdag`` 给的是往 ``dev-run.log`` 追加的那条，
    ``prodserver`` 给的是往 ``prod-server.log`` 追加的那条）。日志里带 git 原文，
    人排查时看到的是最后那句「为什么没推上去」，不是「失败了」。
    """

    def real(timeout: int) -> Callable[[list[str]], tuple[int, str]]:
        return lambda args: _run(ws, args, timeout)

    runner = run if run is not None else real(_BRANCH_TIMEOUT_S)
    code, out = runner(["rev-parse", "--abbrev-ref", "HEAD"])
    if code != 0:
        log(f"推送分支：失败：{_tail(out) or '拿不到当前分支'}")
        return False
    branch = out.strip().splitlines()[0].strip() if out.strip() else ""
    if not branch or branch == "HEAD":
        # detached HEAD：没有分支可推。写清是这一条，而不是让 git 报一句
        # 「src refspec HEAD does not match」让人去查一个不存在的分支名。
        log("推送分支：失败：当前不在任何分支上（detached HEAD），不推")
        return False
    runner = run if run is not None else real(PUSH_TIMEOUT_S)
    code, out = runner(["push", "origin", f"HEAD:{branch}"])
    if code != 0:
        log(f"推送 {branch}：失败：{_tail(out) or f'git push 退出码 {code}'}")
        return False
    log(f"推送 {branch}：成功")
    return True


def _tail(text: str, limit: int = 600) -> str:
    """git 原文的尾巴，砍掉空行。

    一次被拒的 push 可以有几十字节的进度条 + 一段 hint，全贴进日志会把有用的一句
    冲走；最后那几行才是 git 说「为什么」的那段（同 :func:`devdag._git_failure`
    的取舍，但这里不需要文件名名单，所以不做 ``--name-only`` 那套）。
    """
    rows = [r for r in (text or "").splitlines() if r.strip()]
    joined = "\n".join(rows[-5:]) if rows else ""
    return joined[-limit:]
