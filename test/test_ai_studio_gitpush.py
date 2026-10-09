"""Tests for the branch-push step (ACP-2218).

Two kinds of case live here on purpose. The first drives
:func:`gitpush.push_branch` through its injected ``run`` seam: which branch it
picks, what it refuses to push, what the log line says. The second forks a
real git against a real bare remote in ``tmp_path``, because the bug this
module exists for is a fact about git's refspecs that no fake can reproduce —
``push origin v1`` uploads the tagged commit's objects yet creates no
``refs/heads/*``, so a workspace can be fully developed, deployed and tagged
while the personal repo's ``develop`` still sits at the template commit.

Both ``test_ai_studio_devdag.py`` (its scheduler-level pushes) and
``test_ai_studio_prodserver.py`` (which promises never to run git) keep their
own assertions about WHO pushes and WHEN; neither can be the place that proves
the command itself works.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from kiro_crew.apps.builtins.ai_studio.backend import gitpush


def _git(repo: Path, *args: str) -> str:
    """一条真 git（只在下面那两条真 git 的用例里用）。

    作者信息就地配死，不读部署机的 ``~/.gitconfig`` —— 否则换台机器（或 CI 容器里
    没有 ``user.email``）就报「请告诉我你是谁」。同 ``test_ai_studio_devdag.py`` 里
    那三条验 git 自己的用例。
    """
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, f"git {' '.join(args)}: {proc.stdout}{proc.stderr}"
    return ((proc.stdout or "") + (proc.stderr or "")).strip()


def _repo_with_a_commit(path: Path, branch: str = "develop") -> Path:
    """tmp 目录里一个能提交的最小仓库，有一个提交。"""
    path.mkdir()
    # `-b` 与分支名必须是两个参数：git 的短选项不吃 `=`，写成 `-b=develop` 它会
    # 老老实实在一个叫 `=develop` 的分支上开工（实测，报错全无，日志里看不出不对）
    _git(path, "init", "-q", "-b", branch)
    _git(path, "config", "user.email", "t@example.invalid")
    _git(path, "config", "user.name", "test")
    (path / "设备台账.txt").write_text("第一版\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "feat: 设备台账页")
    return path


# ── 真 git：远端到底长什么样 ────────────────────────────────────────────────


def test_a_pushed_branch_lands_on_the_remote(tmp_path: Path):
    """推成分支 ⇒ 远端有 ``refs/heads/develop`` 且指向那个提交。

    判据是**远端的引用**，不是命令的退出码 —— 这一单的全部教训就是「推成功了」和
    「别人看得见代码」不是一件事。替身 git 复现不了它（假 git 不知道 refspec 的语义，
    你说推什么它就记什么），所以这条 fork 真 git；远端用本地 bare 仓，不需要网络也
    不需要凭据。
    """
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "--initial-branch=develop", str(origin))
    repo = _repo_with_a_commit(tmp_path / "repo")
    _git(repo, "remote", "add", "origin", str(origin))
    sha = _git(repo, "rev-parse", "HEAD")

    lines: list[str] = []
    assert gitpush.push_branch(repo, lines.append) is True
    assert lines == ["推送 develop：成功"]
    assert _git(origin, "rev-parse", "refs/heads/develop") == sha


def test_pushing_only_a_tag_leaves_the_branch_unpublished(tmp_path: Path):
    """只推标签：对象过去了，分支引用一个都没有 —— 这一单的现象，当场造出来给测试看。

    这一条不测本模块，测的是 git 的规矩：`push origin v1` 只保证 ``refs/tags/v1``
    这一个引用，``refs/heads/develop`` 一动不动。写下来是因为**它是这一单的立项
    依据**，而它从任何一处运行输出里都看不出来（部署成功、推 tag 不报错、看板全绿）。
    下一个想「把 v<N> 推上去就交付完了」的人，这条会告诉他不够。
    """
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "--initial-branch=develop", str(origin))
    repo = _repo_with_a_commit(tmp_path / "repo")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "tag", "-a", "v1", "-m", "完整版通过验收")

    _git(repo, "push", "-q", "origin", "v1")
    refs = _git(origin, "for-each-ref", "--format=%(refname)").splitlines()
    assert [r for r in refs if r.startswith("refs/tags/")] == ["refs/tags/v1"]
    assert [r for r in refs if r.startswith("refs/heads/")] == []  # 零分支

    # clone 那个远端：一个文件都检不出来（`remote HEAD refers to nonexistent ref`）
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(origin), str(clone))
    assert _git(clone, "ls-files") == ""
    assert list(clone.iterdir()) == [clone / ".git"]  # 工作区里一个文件都没有


def test_a_detached_head_is_refused_never_pushed_as_a_branch_named_head(tmp_path: Path):
    """detached HEAD：``rev-parse --abbrev-ref HEAD`` 原样回 ``HEAD`` 且退出码 0。

    照字面拼 refspec 就是 ``push origin HEAD:HEAD`` —— 远端长出一个叫 ``HEAD`` 的
    分支，一次「成功」的推送写坏的是远端的引用命名空间，而日志上什么都看不出来。
    所以这里在**发 push 之前**就判掉，并断言那条命令一次都没发。
    """
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "--initial-branch=develop", str(origin))
    repo = _repo_with_a_commit(tmp_path / "repo")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "commit", "-q", "--allow-empty", "-m", "第二个提交")
    _git(repo, "checkout", "-q", "--detach")

    asked: list[list[str]] = []

    def spy(argv: list[str]) -> tuple[int, str]:
        asked.append(list(argv))
        return (0, "HEAD\n") if argv[0] == "rev-parse" else (0, "")

    lines: list[str] = []
    assert gitpush.push_branch(repo, lines.append, run=spy) is False
    assert "detached" in lines[-1]
    assert asked == [["rev-parse", "--abbrev-ref", "HEAD"]]  # 一条 push 都没发

    # 真 git 也走一遍：确认「detached」这个判断对的是 git 的真输出，不是替身的输出
    assert gitpush.push_branch(repo, lines.append) is False
    assert "detached" in lines[-1]
    assert _git(origin, "for-each-ref", "--format=%(refname)") == ""


# ── 判断与措辞（替身 git，不 fork 进程）────────────────────────────────────


def test_the_current_branch_is_read_and_pushed_as_a_refspec(tmp_path: Path):
    """两条命令、一个 refspec：``HEAD:<当前分支>``。

    写 ``HEAD:`` 而不是分支名，是让「推的就是当前检出的那个提交」由 git 自己保证。
    """
    asked: list[list[str]] = []
    lines: list[str] = []

    def fake_git(argv: list[str]) -> tuple[int, str]:
        asked.append(list(argv))
        return (0, "feat/device-manage\n") if argv[0] == "rev-parse" else (0, "")

    assert gitpush.push_branch(tmp_path, lines.append, run=fake_git) is True
    assert asked == [
        ["rev-parse", "--abbrev-ref", "HEAD"],
        ["push", "origin", "HEAD:feat/device-manage"],
    ]
    assert lines == ["推送 feat/device-manage：成功"]


def test_a_refused_push_writes_git_words_and_never_raises(tmp_path: Path):
    """认不出分支 / 推被拒：False + git 那句原文，一个异常都不冒。

    两个失败面都要走到，因为调用方两条都不许当成自己的失败 —— 前者（不是仓库）根本
    没法推，后者（远端拒绝）是远端的事，而代码都已经在盘上了。
    """
    lines: list[str] = []
    assert (
        gitpush.push_branch(tmp_path, lines.append, run=lambda a: (128, "fatal: 不是 git 仓库"))
        is False
    )
    assert "推送分支：失败" in lines[-1] and "不是 git 仓库" in lines[-1]

    def rejected(argv: list[str]) -> tuple[int, str]:
        return (
            (0, "develop\n") if argv[0] == "rev-parse" else (1, "error: failed to push some refs")
        )

    assert gitpush.push_branch(tmp_path, lines.append, run=rejected) is False
    assert "推送 develop：失败" in lines[-1] and "failed to push some refs" in lines[-1]


def test_the_child_env_drops_the_proxy_and_refuses_to_ask(tmp_path, monkeypatch):
    """推送环境：不挂代理，且 git 不许开 tty 问凭据。

    代理是这台机器的默认出口，个人仓在内网 —— 挂上反而不通（``child_env`` 的剥除
    清单里就有这一条）。``GIT_TERMINAL_PROMPT=0`` 更要紧：缺凭据时 git 默认开一个
    tty 问用户名，这里没人回答，只会把 120 秒等满，从外面看是「部署卡住了」。
    """
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7777")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7777")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "1")
    env = gitpush.child_env_without_prompt()
    assert "HTTP_PROXY" not in env and "HTTPS_PROXY" not in env
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    # 覆盖位是「加一条」而不是「换一份」：PATH 之类还得在，git 才起得来
    assert "PATH" in env
