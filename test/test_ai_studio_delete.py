"""Tests for deleting an AI Studio workspace (ACP-2206).

Four facts this file exists to hold, in the order the ticket states them:

* the delete MOVES — the workspace lands in ``<AI_STUDIO_WORKSPACES_ROOT>/.trash/
  <代号>-<时间戳>/`` and the record in ``<projects_root>/.trash/``, so a wrong
  click is a wrong click and not a lost project;
* the servers are stopped FIRST;
* a development run in flight refuses the delete at all (409 ``dev_running``)
  rather than leaving a live session writing into a directory already moved;
* the remote personal repo survives — nothing here talks to git or the network,
  and the workspace's ``.git`` (remote url and all) is still in the trash.

Everything external is a stand-in: the servers are injected as ``stop_servers``,
so no test here can kill a process or touch a gateway conf (the route's real
stop helper is tested against its own ``not_running`` rule below).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from kiro_crew.apps.builtins.ai_studio.backend import (
    devserver,
    prodserver,
    projects,
    routes,
)


@pytest.fixture()
def home(tmp_path, monkeypatch):
    h = tmp_path / "crew"
    h.mkdir()
    monkeypatch.setenv("KIROCREW_HOME", str(h))
    monkeypatch.setenv("KIROCREW_STAFF_ID", "14409")
    monkeypatch.setenv("AI_STUDIO_WORKSPACES_ROOT", str(tmp_path / "workspaces"))
    # both server caches are process globals: a test that fills one must not
    # hand a stale object (with a stale workspace path) to the next one
    monkeypatch.setattr(devserver, "_SERVERS", {})
    monkeypatch.setattr(prodserver, "_SERVERS", {})
    return h


class StopSpy:
    """The injected ``stop_servers``: records what it was handed and what it saw."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool]] = []

    def __call__(self, record: dict[str, Any], ws: Path) -> None:
        # ``ws_exists`` is the ordering proof: the stop must run while the
        # workspace is still where it was, or the processes being killed were
        # started from a path we had already moved away.
        self.calls.append((str(record.get("id")), str(ws), ws.is_dir()))


def _make_record(tmp_path: Path, code: str = "sbgl") -> tuple[dict[str, Any], Path]:
    """A derived workspace: the record the job leaves behind (id == 代号, status
    ready, ``workspaceDir`` pointing at a real cloned repo directory)."""
    ws = tmp_path / "workspaces" / code
    (ws / ".git").mkdir(parents=True)
    (ws / ".git" / "config").write_text(
        f'[remote "origin"]\n\turl = https://bitbucket.jereh.cn/scm/~14409/{code}.git\n',
        encoding="utf-8",
    )
    (ws / "apps" / "web").mkdir(parents=True)
    (ws / "package.json").write_text('{"name": "sbgl"}', encoding="utf-8")
    projects.create_project("设备管理", "设备点检", code)
    return projects.update_project(code, status="ready", workspaceDir=str(ws)), ws


def _set_dev_state(ws: Path, run_state: str) -> None:
    (ws / ".ai-studio").mkdir(parents=True, exist_ok=True)
    (ws / ".ai-studio" / "dev-run.json").write_text(
        json.dumps({"runId": "dev-1", "runState": run_state, "nodes": []}), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# 1. the move into the trash
# ---------------------------------------------------------------------------


def test_delete_moves_workspace_and_record_into_the_trash(home, tmp_path):
    record, ws = _make_record(tmp_path)

    result = projects.delete_project(record["id"], stop_servers=StopSpy())

    assert result["deleted"] is True
    trash_ws = Path(result["trash"])
    assert trash_ws.parent == tmp_path / "workspaces" / ".trash"
    assert trash_ws.name.startswith("sbgl-")
    # 内容跟着走，不是新建的空目录
    assert (trash_ws / "package.json").read_text(encoding="utf-8") == '{"name": "sbgl"}'
    assert (trash_ws / "apps" / "web").is_dir()
    # 记录目录同样进回收站，project.json 还读得动
    record_trash = Path(result["recordTrash"])
    assert record_trash.parent == projects.projects_root() / ".trash"
    assert json.loads((record_trash / "project.json").read_text(encoding="utf-8"))["id"] == "sbgl"
    # 原处都不在了，列表里也没有了
    assert not ws.exists()
    assert not (projects.projects_root() / "sbgl").exists()
    assert projects.list_projects() == []
    assert projects.get_project("sbgl") is None


def test_delete_loses_no_files(home, tmp_path):
    # 「移到回收站」的全部意义：一个文件都不少。按相对名比，位置换了名字不变。
    record, ws = _make_record(tmp_path)
    before = sorted(str(p.relative_to(ws)) for p in ws.rglob("*"))

    result = projects.delete_project(record["id"], stop_servers=StopSpy())

    after = sorted(
        str(p.relative_to(Path(result["trash"]))) for p in Path(result["trash"]).rglob("*")
    )
    assert before == after


def test_delete_a_plain_project_moves_its_record_dir_only(home, tmp_path):
    # 没代号的项目 ``workspace_dir`` 就是记录目录本身，移一次就是全部。移第二次会
    # 因为源目录已经搬走而抛 FileNotFoundError —— 列表页每张卡片都有删除按钮，
    # 老项目就成了 503。
    record = projects.create_project("老项目", "")

    result = projects.delete_project(record["id"], stop_servers=StopSpy())

    assert result["deleted"] is True
    assert Path(result["trash"]).parent == projects.projects_root() / ".trash"
    assert "recordTrash" not in result
    assert not (projects.projects_root() / record["id"]).exists()
    assert projects.list_projects() == []


def test_same_code_deleted_twice_keeps_both_copies(home, tmp_path):
    # 删完重建同代号再删（或同一秒点两次）：第二份绝不覆盖第一份，覆盖了就没有
    # 「可找回」了。时间戳显式给同一个，免得靠时钟配合才测到这一条。
    first_record, _ws = _make_record(tmp_path)
    first = projects.delete_project(first_record["id"], now=1700000000.0, stop_servers=StopSpy())
    assert projects.list_projects() == []

    second_record, _second_ws = _make_record(tmp_path)
    second = projects.delete_project(second_record["id"], now=1700000000.0, stop_servers=StopSpy())

    assert first["trash"] != second["trash"]
    for path in (first["trash"], first["recordTrash"], second["trash"], second["recordTrash"]):
        assert Path(path).is_dir(), path


# ---------------------------------------------------------------------------
# 2. the servers are stopped first
# ---------------------------------------------------------------------------


def test_delete_stops_the_servers_before_it_moves(home, tmp_path):
    record, ws = _make_record(tmp_path)
    spy = StopSpy()

    projects.delete_project(record["id"], stop_servers=spy)

    assert len(spy.calls) == 1
    called_id, called_ws, existed_at_call = spy.calls[0]
    assert called_id == "sbgl"
    assert called_ws == str(ws)
    # 停的那一刻工作区还在原位：进程、端口和 conf 都是按那台目录记着的
    assert existed_at_call is True


def test_delete_without_the_injection_still_moves(home, tmp_path):
    # 不注入就等于不停（本模块不 import 那两个服务器类，否则就成循环导入）：
    # 删除本身照做，路由层负责传真版进来。
    record = projects.create_project("老项目", "")
    assert projects.delete_project(record["id"])["deleted"] is True


def test_route_stop_helper_tolerates_not_running_only(home, monkeypatch):
    # 「没在运行」是删除一个从没起过服务器的工作区的常态，吞掉；其余 code 上抛，
    # 因为「停了但没停干净」不该被一个删除按钮抹平。
    class DevStub:
        def __init__(self, code: str) -> None:
            self.code = code
            self.stopped = 0

        def stop(self) -> dict:
            self.stopped += 1
            raise devserver.DevServerError("开发服务器没在运行", self.code, 409)

    class ProdStub(DevStub):
        def stop(self) -> dict:
            self.stopped += 1
            raise prodserver.ProdServerError("正式服务器没在运行", self.code, 409)

    dev_stub, prod_stub = DevStub("not_running"), ProdStub("not_running")
    monkeypatch.setattr(devserver, "dev_server_for", lambda _p, _ws: dev_stub)
    monkeypatch.setattr(prodserver, "prod_server_for", lambda _p, _ws: prod_stub)

    routes._stop_both_servers({"id": "sbgl"}, Path("/workspaces/sbgl"))
    assert (dev_stub.stopped, prod_stub.stopped) == (1, 1)

    dev_stub.code = "already_running"
    with pytest.raises(devserver.DevServerError):
        routes._stop_both_servers({"id": "sbgl"}, Path("/workspaces/sbgl"))


# ---------------------------------------------------------------------------
# 3. a run in flight refuses the delete
# ---------------------------------------------------------------------------


def test_delete_refuses_while_development_is_running(home, tmp_path):
    record, ws = _make_record(tmp_path)
    _set_dev_state(ws, "running")
    spy = StopSpy()

    with pytest.raises(projects.ProjectError) as exc:
        projects.delete_project(record["id"], stop_servers=spy)

    assert (exc.value.code, exc.value.status) == ("dev_running", 409)
    assert str(exc.value) == "开发进行中，先等它结束"
    # 什么都没动：这一条拒绝是完全的
    assert ws.is_dir()
    assert (projects.projects_root() / "sbgl").is_dir()
    assert [p["id"] for p in projects.list_projects()] == ["sbgl"]
    # 服务器已经被停是既成事实（顺序如此）：项目还在，再点一次接着来
    assert len(spy.calls) == 1


@pytest.mark.parametrize("run_state", ["done", "failed", "planned", "idle", "aborted"])
def test_every_other_run_state_allows_the_delete(home, tmp_path, run_state):
    record, ws = _make_record(tmp_path)
    _set_dev_state(ws, run_state)
    assert projects.delete_project(record["id"], stop_servers=StopSpy())["deleted"] is True


def test_missing_or_corrupt_dev_run_state_is_not_running(home, tmp_path):
    # 一个读不动的状态文件不能变成「不许删」，否则看板坏了就再也删不掉工作区
    record, ws = _make_record(tmp_path)
    (ws / ".ai-studio").mkdir(parents=True)
    (ws / ".ai-studio" / "dev-run.json").write_text("{not json", encoding="utf-8")
    assert projects.delete_project(record["id"], stop_servers=StopSpy())["deleted"] is True


def test_running_state_never_rewrites_the_dev_run_file(home, tmp_path):
    # 拒绝用的那份状态必须原样留着：删除一条路径顺手把 running 改成 failed，
    # 看板上的中断判定就不是它自己判的了
    record, ws = _make_record(tmp_path)
    _set_dev_state(ws, "running")
    state_file = ws / ".ai-studio" / "dev-run.json"
    before = state_file.read_text(encoding="utf-8")

    with pytest.raises(projects.ProjectError):
        projects.delete_project(record["id"], stop_servers=StopSpy())

    assert state_file.read_text(encoding="utf-8") == before


# ---------------------------------------------------------------------------
# 4. the remote is never touched
# ---------------------------------------------------------------------------


def test_the_store_talks_to_no_git_at_all(home, tmp_path):
    # 「远端仓不删」在这一层是无结构的：``projects`` 没有 import subprocess、没有
    # git 客户端，所以没有任何一条 git 调用可漏。断言只能是模块级的 —— 哪天有人
    # 给删除加了 ``git push --delete``，这一条先红。
    source = Path(projects.__file__).read_text(encoding="utf-8")
    assert "import subprocess" not in source
    assert "bitbucket" not in source

    record, ws = _make_record(tmp_path)
    remote = (ws / ".git" / "config").read_text(encoding="utf-8")
    result = projects.delete_project(record["id"], stop_servers=StopSpy())

    # 远端地址原样躺在回收站那一份 .git/config 上
    assert (Path(result["trash"]) / ".git" / "config").read_text(encoding="utf-8") == remote


def test_workspace_already_gone_still_removes_the_record(home, tmp_path):
    # 派生失败的工作区可能半个都不存在，而那张卡片照样有删除按钮
    projects.create_project("设备管理", "", "sbgl")
    projects.update_project("sbgl", status="failed", workspaceDir=str(tmp_path / "gone"))

    result = projects.delete_project("sbgl", stop_servers=StopSpy())

    assert result["deleted"] is True
    assert "recordTrash" not in result
    assert Path(result["trash"]).parent == projects.projects_root() / ".trash"
    assert projects.list_projects() == []


# ---------------------------------------------------------------------------
# 5. the route
# ---------------------------------------------------------------------------


def _make_app(monkeypatch, enabled: bool = True) -> web.Application:
    monkeypatch.setattr(routes, "is_app_enabled", lambda _name: enabled)
    app = web.Application()
    routes.register_routes(app)
    return app


@pytest.mark.asyncio
async def test_route_delete_200_then_the_project_is_gone(home, tmp_path, monkeypatch):
    record, ws = _make_record(tmp_path)
    seen: list[str] = []
    monkeypatch.setattr(
        routes, "_stop_both_servers", lambda r, w: seen.append(f"{r['id']}:{w.is_dir()}")
    )
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.delete(f"/api/apps/ai-studio/projects/{record['id']}")
        assert resp.status == 200
        body = await resp.json()
        assert body["deleted"] is True
        assert Path(body["trash"]).is_dir()
        assert seen == ["sbgl:True"]

        resp = await client.get("/api/apps/ai-studio/projects")
        assert (await resp.json())["projects"] == []

        resp = await client.delete("/api/apps/ai-studio/projects/sbgl")
        assert resp.status == 404
        assert (await resp.json())["code"] == "project_not_found"


@pytest.mark.asyncio
async def test_route_delete_409_while_development_runs(home, tmp_path, monkeypatch):
    record, ws = _make_record(tmp_path)
    _set_dev_state(ws, "running")
    monkeypatch.setattr(routes, "_stop_both_servers", lambda _r, _w: None)
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.delete(f"/api/apps/ai-studio/projects/{record['id']}")
        assert resp.status == 409
        body = await resp.json()
        # 前端按 code 分流，error 原文照抄给人看
        assert body["code"] == "dev_running"
        assert body["error"] == "开发进行中，先等它结束"
    assert ws.is_dir()


@pytest.mark.asyncio
async def test_route_delete_403_when_the_app_is_disabled(home, monkeypatch):
    async with TestClient(TestServer(_make_app(monkeypatch, enabled=False))) as client:
        resp = await client.delete("/api/apps/ai-studio/projects/whatever")
        assert resp.status == 403
        assert (await resp.json())["code"] == "app_disabled"


@pytest.mark.asyncio
async def test_route_delete_reports_a_failed_move_as_503(home, tmp_path, monkeypatch):
    def refuse(self: Path, _target: Path) -> None:
        # 跨设备 rename 是 EXDEV：宁可 503 也不要静默复制一半（那才是真丢数据）
        raise OSError(18, "Invalid cross-device link")

    record, _ws = _make_record(tmp_path)
    monkeypatch.setattr(routes, "_stop_both_servers", lambda _r, _w: None)
    monkeypatch.setattr(Path, "rename", refuse)
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        resp = await client.delete(f"/api/apps/ai-studio/projects/{record['id']}")
        assert resp.status == 503
        assert (await resp.json())["code"] == "store_write_failed"
    # 记录还在，删除可以重来 —— 半删状态不能把一个项目变成没人认领的孤儿
    assert projects.get_project("sbgl") is not None
