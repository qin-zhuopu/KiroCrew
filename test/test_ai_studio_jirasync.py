"""Tests for the Jira sync layer (ACP-2085-S6 第 1 步).

这一层的全部对外依赖是一条外部命令，所以测试的全部手段也是它：替身命令写进
tmp_path，``AI_STUDIO_JIRA_CMD`` 指向它（照 test_ai_studio_requirements.py 对
``jc fe reqdoc`` 的做法）。替身把每次收到的 argv 逐行记进一个文件，回一个和真
CLI 同形状的 JSON 信封 ``{"success":true,"data":{"key":…}}``，并且能按环境变量
切成「退出 1」「回一坨非 JSON」「回 success=false」三种坏形状。

不 monkeypatch ``subprocess.run``：这一层的存在意义就是「子进程怎么调、坏了怎么
不炸」，把子进程本身换掉，等于把要验的那件事换掉了。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from kiro_crew.apps.builtins.ai_studio.backend import jirasync, projects

#: 替身命令的行为开关，测试用 monkeypatch 设它
_MODE_ENV = "FAKE_JIRA_MODE"
_CALLS_ENV = "FAKE_JIRA_CALLS"
_KEY_ENV = "FAKE_JIRA_KEY"

_FAKE_JIRA = """
import json, os, sys

calls = os.environ["FAKE_JIRA_CALLS"]
with open(calls, "a", encoding="utf-8") as fh:
    for a in sys.argv[1:]:
        fh.write(a + "\\n")
    fh.write("\\x00\\n")

mode = os.environ.get("FAKE_JIRA_MODE", "ok")
if mode == "exit1":
    print(json.dumps({"success": False, "message": "无可用流转 \\"进行中\\""}))
    raise SystemExit(1)
if mode == "garbage":
    print("not json at all")
    raise SystemExit(0)
if mode == "boom":
    print("Traceback (most recent call last)")
    raise SystemExit(3)
if mode == "false":
    print(json.dumps({"success": False, "message": "项目不存在"}))
    raise SystemExit(20)
if mode == "nokey":
    print(json.dumps({"success": True, "data": {}}))
    raise SystemExit(0)
print(json.dumps({"success": True, "data": {"key": os.environ.get("FAKE_JIRA_KEY", "ACP-9001")}}))
"""


@pytest.fixture()
def fake(tmp_path, monkeypatch):
    """把替身命令接到 ``AI_STUDIO_JIRA_CMD`` 上，并管好其余那几个环境变量。

    ``AI_STUDIO_JIRA_*`` 五个都得显式设/删：本模块读的都是环境变量，上一个测试
    留下的值会让下一个测试读到别人的配置（尤其 CI 上真部署里就设着这几个）。
    """
    script = tmp_path / "fake_jira.py"
    script.write_text(_FAKE_JIRA, encoding="utf-8")
    calls = tmp_path / "calls.txt"
    monkeypatch.setenv("AI_STUDIO_JIRA_CMD", f"{sys.executable} {script}")
    monkeypatch.setenv(_CALLS_ENV, str(calls))
    monkeypatch.delenv(_MODE_ENV, raising=False)
    monkeypatch.setenv(_KEY_ENV, "ACP-9001")
    monkeypatch.delenv("AI_STUDIO_JIRA_PROJECT", raising=False)
    monkeypatch.delenv("AI_STUDIO_JIRA_BROWSE", raising=False)
    monkeypatch.delenv("AI_STUDIO_JIRA_DOING", raising=False)
    monkeypatch.delenv("AI_STUDIO_JIRA_DONE", raising=False)
    return calls


def calls_of(path: Path) -> list[list[str]]:
    """替身记下的每次调用（用 NUL 行分隔）。"""
    if not path.is_file():
        return []
    chunks = path.read_text(encoding="utf-8").split("\x00\n")
    return [c.splitlines() for c in chunks if c.strip()]


# ── 1. 没设命令 = 不同步 Jira ──────────────────────────────────────────────


def test_unset_cmd_disables_everything_and_spawns_nothing(tmp_path, monkeypatch, fake):
    """没设 ``AI_STUDIO_JIRA_CMD``：每个函数直接回 ``None``／空错误，一条命令都不起。

    「不起子进程」是本单能不能在没配 Jira 的部署上跑起来的关键，所以断言的是替身
    一个字节都没写，而不是返回值恰好对。
    """
    monkeypatch.delenv("AI_STUDIO_JIRA_CMD")
    project = {"id": "eqp", "code": "eqp", "name": "设备管理"}

    assert jirasync.jira_cmd() is None
    assert jirasync.ensure_parent(project) is None
    assert jirasync.ensure_parent_checked(project) == (None, "")
    assert jirasync.create_task("ACP-1", "标题", "eqp") is None
    assert jirasync.create_task_checked("ACP-1", "标题", "eqp") == (None, "")
    # transition/comment 返回的是错误原文，空串就是「没做也没错」
    assert jirasync.transition("ACP-1", "开始进行") is None
    assert jirasync.transition_checked("ACP-1", "开始进行") == ""
    assert jirasync.comment("ACP-1", "完成") is None
    assert jirasync.comment_checked("ACP-1", "完成") == ""
    assert calls_of(fake) == []
    # 没建单也不许往项目记录里写东西
    assert "jiraParent" not in project


def test_blank_cmd_is_unset_too(monkeypatch, fake):
    """设成空串／一串空白也是「没设」：不能让 ``shlex.split`` 的空 argv 漏到子进程。"""
    monkeypatch.setenv("AI_STUDIO_JIRA_CMD", "   ")
    assert jirasync.jira_cmd() is None
    assert jirasync.ensure_parent({"id": "e", "name": "n"}) is None
    assert calls_of(fake) == []


# ── 命令拼装 ───────────────────────────────────────────────────────────────


def test_cmd_project_and_browse_come_from_env(monkeypatch):
    monkeypatch.setenv("AI_STUDIO_JIRA_CMD", "jc jira")
    assert jirasync.jira_cmd() == ["jc", "jira"]
    # 默认值照派工单
    assert jirasync.jira_project() == "ACP"
    assert jirasync.browse_url("ACP-9") == "https://jira.jereh.cn/browse/ACP-9"
    assert jirasync.doing_state() == "进行中"
    assert jirasync.done_state() == "完成"

    monkeypatch.setenv("AI_STUDIO_JIRA_PROJECT", "MYAPP")
    monkeypatch.setenv("AI_STUDIO_JIRA_BROWSE", "https://j.example/x/{key}")
    monkeypatch.setenv("AI_STUDIO_JIRA_DOING", "开始进行")
    monkeypatch.setenv("AI_STUDIO_JIRA_DONE", "关闭")
    assert jirasync.jira_project() == "MYAPP"
    assert jirasync.browse_url("ACP-9") == "https://j.example/x/ACP-9"
    assert jirasync.doing_state() == "开始进行"
    assert jirasync.done_state() == "关闭"


def test_browse_url_tolerates_a_broken_template(monkeypatch):
    """模板是运维写的：里面有单独的 ``{`` 也不许抛（一个链接不该有本事崩掉开发）。"""
    monkeypatch.setenv("AI_STUDIO_JIRA_BROWSE", "https://j.example/issues/{key}#{{x}")
    assert jirasync.browse_url("ACP-9") == "https://j.example/issues/ACP-9#{{x}"


def test_parent_create_arguments(fake):
    """父单：``--project``／``--summary``／``--labels ai-studio,<代号>``。"""
    key = jirasync.ensure_parent({"id": "eqp", "code": "eqp", "name": "设备管理"})
    assert key == "ACP-9001"
    argv = calls_of(fake)[0]
    assert argv[:2] == ["issue", "create"]
    assert argv[argv.index("--project") + 1] == "ACP"
    assert argv[argv.index("--summary") + 1] == "[AI Studio] 设备管理（eqp）开发"
    assert argv[argv.index("--labels") + 1] == "ai-studio,eqp"
    assert "--parent" not in argv


def test_parent_summary_falls_back_to_id_when_no_code(fake):
    """没代号的普通项目（``create_project`` 不带 code）：标题用 id，标签只有 app。"""
    jirasync.ensure_parent({"id": "p0101", "name": "设备管理"})
    argv = calls_of(fake)[0]
    assert argv[argv.index("--summary") + 1] == "[AI Studio] 设备管理（p0101）开发"
    assert argv[argv.index("--labels") + 1] == "ai-studio,p0101"


def test_task_create_arguments(fake):
    """3：子单带 ``--parent`` 与 ``--labels ai-studio,eqp``。"""
    key = jirasync.create_task("ACP-7000", "设备清单：后端接口", "eqp")
    assert key == "ACP-9001"
    argv = calls_of(fake)[0]
    assert argv[:2] == ["issue", "create"]
    assert argv[argv.index("--parent") + 1] == "ACP-7000"
    assert argv[argv.index("--summary") + 1] == "设备清单：后端接口"
    assert argv[argv.index("--labels") + 1] == "ai-studio,eqp"


def test_transition_and_comment_arguments(fake):
    jirasync.transition("ACP-9001", "开始进行")
    jirasync.comment("ACP-9001", "完成，提交 abc12345")
    rows = calls_of(fake)
    assert rows[0] == ["issue", "transition", "ACP-9001", "--to", "开始进行"]
    assert rows[1] == ["issue", "comment", "ACP-9001", "--body", "完成，提交 abc12345"]


def test_state_names_env_reaches_the_command(fake, monkeypatch):
    """状态名可覆盖，且真的进到了命令行里（这一条是「部署侧能改」的唯一证据）。"""
    monkeypatch.setenv("AI_STUDIO_JIRA_DOING", "开始进行")
    jirasync.transition("ACP-9001", jirasync.doing_state())
    assert calls_of(fake)[0] == ["issue", "transition", "ACP-9001", "--to", "开始进行"]


def test_no_key_no_transition_no_comment(fake):
    """没有单号就别调命令：一个空 key 打到 CLI 上是一条看不懂的报错。"""
    jirasync.transition("", "开始进行")
    jirasync.comment("", "x")
    jirasync.transition("ACP-1", "")
    assert calls_of(fake) == []


# ── 2. 父单只建一次 ────────────────────────────────────────────────────────


def test_ensure_parent_creates_once_then_reuses(home, monkeypatch, fake):
    """第一次建 + 写回项目记录，第二次直接读记录，一条命令都不再发。

    「一个工作区一个父单」是本单的地基：重做计划、重启网关都只该往同一个父单下挂
    子单。写回真走 ``projects.update_project``（真记录，不是替身 dict），所以下一个
    进程、下一次请求读到的也是同一个号。
    """
    record = projects.create_project("设备管理", "", code="eqp")
    project_id = record["id"]

    key = jirasync.ensure_parent(record)
    assert key == "ACP-9001"
    assert len(calls_of(fake)) == 1
    on_disk = json.loads(
        (projects.projects_root() / project_id / "project.json").read_text(encoding="utf-8")
    )
    assert on_disk["jiraParent"] == "ACP-9001"
    # 传进来的那份也更新了，调用方不用重读记录
    assert record["jiraParent"] == "ACP-9001"

    monkeypatch.setenv(_KEY_ENV, "ACP-9002")
    again = jirasync.ensure_parent(projects.get_project(project_id) or {})
    assert again == "ACP-9001"
    assert len(calls_of(fake)) == 1, "已有 jiraParent 还建单 = 一个工作区两个父单"


def test_parent_remember_failure_does_not_lose_the_key(monkeypatch, fake):
    """写回记录失败也不丢已经建好的单：号照样回，错误不外抛。"""
    from kiro_crew.apps.builtins.ai_studio.backend import projects as projects_module

    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(projects_module, "update_project", boom)
    assert jirasync.ensure_parent({"id": "eqp", "code": "eqp", "name": "设备管理"}) == "ACP-9001"


def test_parent_without_id_still_returns_the_key(monkeypatch, fake):
    """构造出来的记录没有 id（单测里常见）：不写回、不抛，号照回。"""
    assert jirasync.ensure_parent({"name": "设备管理"}) == "ACP-9001"


# ── 4. 坏命令 ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("mode", ["exit1", "garbage", "boom", "false", "nokey"])
def test_a_broken_command_returns_none_and_never_raises(monkeypatch, fake, mode):
    """退出 1／非 JSON／success=false／没单号：一律 ``None``（或空错误），不抛。

    这一层抛出去，开发轮次就会停在第一个节点上，而 Jira 只是记账。错误原文要能
    带出来（``*_checked``），因为看板上那行灰字要显示它。
    """
    monkeypatch.setenv(_MODE_ENV, mode)
    project = {"id": "eqp", "code": "eqp", "name": "n"}
    parent, parent_err = jirasync.ensure_parent_checked(project)
    task, task_err = jirasync.create_task_checked("ACP-1", "t", "eqp")
    trans = jirasync.transition_checked("ACP-1", "开始进行")
    com = jirasync.comment_checked("ACP-1", "x")

    assert (parent, task) == (None, None)
    # 建不成就不许往记录里写 jiraParent：半个号比没有更糟（下次 plan 会重试）
    assert "jiraParent" not in project
    if mode == "nokey":
        # 信封是 success:true 但 data 里没有单号：建单算失败（节点不许拿空链接），
        # 而流转/评论不读 data，命令说成就是成 —— 两种判法各自照命令的回话。
        assert "单号" in parent_err and "单号" in task_err
        assert (trans, com) == ("", "")
    else:
        for err in (parent_err, task_err, trans, com):
            assert err, "失败必须带回原文，否则看板上只有一句「失败」"


def test_cli_error_message_is_what_the_board_shows(monkeypatch, fake):
    """``jc`` 报错是「退出码非 0 + 信封里带 message」：message 优先于退出码。

    实测的 ``transition --to 进行中`` 就是这个形状，看板上要看到的是「无可用流转
    "进行中"」这一句，不是 ``exit 1``。
    """
    monkeypatch.setenv(_MODE_ENV, "exit1")
    err = jirasync.transition_checked("ACP-1", "进行中")
    assert "无可用流转" in err
    assert "exit 1" not in err


def test_exit_only_failure_falls_back_to_stderr(monkeypatch, fake):
    """没有信封的非零退出：用退出码 + stderr 兜底，别回一个空串。"""
    monkeypatch.setenv(_MODE_ENV, "boom")
    err = jirasync.transition_checked("ACP-1", "开始进行")
    assert "exit 3" in err


def test_missing_command_is_reported_not_raised(monkeypatch, fake):
    """命令根本不存在（``jc`` 没装）：回原文，不抛 ``FileNotFoundError``。"""
    monkeypatch.setenv("AI_STUDIO_JIRA_CMD", "/nonexistent/jc jira")
    assert jirasync.jira_cmd() == ["/nonexistent/jc", "jira"]
    key, err = jirasync.create_task_checked("ACP-1", "t", "eqp")
    assert key is None and "命令不存在" in err
    assert calls_of(fake) == []


def test_timeout_returns_an_error_not_a_hang(tmp_path, monkeypatch, fake):
    """挂住的命令：到点回错误。

    超时值临时调小，否则这条测试要真等 60 秒 —— 上限本身是模块常量，测的是「到点
    会回」，不是「恰好 60 秒」。
    """
    sleeper = tmp_path / "sleep.py"
    sleeper.write_text("import time; time.sleep(30)", encoding="utf-8")
    monkeypatch.setenv("AI_STUDIO_JIRA_CMD", f"{sys.executable} {sleeper}")
    monkeypatch.setattr(jirasync, "CMD_TIMEOUT_S", 1)
    key, err = jirasync.create_task_checked("ACP-1", "t", "eqp")
    assert key is None
    assert "超时" in err


# ── 环境隔离 ───────────────────────────────────────────────────────────────


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "crew"
    h.mkdir()
    monkeypatch.setenv("KIROCREW_HOME", str(h))
    return h


def test_module_reads_env_per_call(monkeypatch, fake):
    """没有模块级缓存：改环境变量下一次调用就生效。

    ``requirements.py`` 同理（``config_dir()`` 的 memo 按 ``KIROCREW_HOME`` 键），
    这里钉住它：网关不重启也想换项目 key 是运维会干的事，而 import 期定死的值在
    测试里更是会让相邻两个测试互相串味。
    """
    monkeypatch.setenv("AI_STUDIO_JIRA_PROJECT", "A")
    assert jirasync.jira_project() == "A"
    monkeypatch.setenv("AI_STUDIO_JIRA_PROJECT", "B")
    assert jirasync.jira_project() == "B"
