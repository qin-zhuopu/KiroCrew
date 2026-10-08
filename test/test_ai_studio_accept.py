"""Tests for the AI Studio acceptance runner (ACP-2085-S4 step 3).

The commands run through the injected ``runner`` seam — nothing here may spawn
``pnpm`` (nor resolve it on PATH), because an acceptance suite is exactly the
kind of long-running child a unit test must never own (testing-conventions).
The two accept routes are covered here too, since what they own is this
module's two error shapes and the record envelope.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from kiro_crew.apps.builtins.ai_studio.backend import accept, devdag, projects, routes

DONE_RUN: dict[str, Any] = {
    "runId": "dev-1",
    "phase": "full",
    "runState": "done",
    "graphHashes": {"备件台账": "b2", "设备点检记录": "a1"},
}


def make_runner(codes: dict[str, int], outputs: dict[str, str] | None = None):
    """A stand-in for the subprocess seam: ``{argv[1]: exit code}``."""
    seen: list[tuple[list[str], str]] = []
    texts = outputs or {}

    def runner(cmd: list[str], ws: Path) -> tuple[int, str]:
        seen.append((list(cmd), str(ws)))
        code = codes.get(" ".join(cmd), 0)
        return code, texts.get(" ".join(cmd), f"line for {' '.join(cmd)}")

    return runner, seen


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root


def test_two_passing_cmds_are_a_pass(ws: Path):
    runner, seen = make_runner({})
    record = accept.run_accept(ws, DONE_RUN, runner=runner)
    assert record["result"] == "passed"
    assert [r["id"] for r in record["results"]] == ["pnpm typecheck", "pnpm test:unit"]
    assert all(r["ok"] for r in record["results"])
    # cwd is the workspace, not the gateway's directory
    assert {cwd for _cmd, cwd in seen} == {str(ws)}
    assert record["phase"] == "full"
    assert record["voided"] is False
    assert (accept.accept_dir(ws) / f"{record['id']}.json").is_file()


def test_one_failing_cmd_is_a_failure_with_output_in_the_tail(ws: Path):
    runner, _seen = make_runner(
        {"pnpm test:unit": 1}, {"pnpm test:unit": "a\nb\nFAIL tests/x.spec.ts\ntype: Error"}
    )
    record = accept.run_accept(ws, DONE_RUN, runner=runner)
    assert record["result"] == "failed"
    bad = record["results"][1]
    assert bad["ok"] is False
    assert "FAIL tests/x.spec.ts" in bad["tail"]
    assert record["results"][0]["ok"] is True


def test_the_tail_keeps_only_the_last_forty_lines(ws: Path):
    spam = "\n".join(f"noise {i}" for i in range(500))
    runner, _seen = make_runner({"pnpm typecheck": 2}, {"pnpm typecheck": spam})
    record = accept.run_accept(ws, DONE_RUN, runner=runner)
    rows = record["results"][0]["tail"].splitlines()
    assert len(rows) == 40
    assert rows[0] == "noise 460"
    assert rows[-1] == "noise 499"


@pytest.mark.parametrize("state", ["running", "failed", "idle"])
def test_a_run_that_is_not_done_is_refused_with_409(ws: Path, state: str):
    runner, seen = make_runner({})
    with pytest.raises(accept.AcceptError) as exc:
        accept.run_accept(ws, {"runState": state}, runner=runner)
    assert (exc.value.code, exc.value.status) == ("dev_not_done", 409)
    assert seen == []  # refused before running anything
    assert not accept.accept_dir(ws).exists()


def test_voided_is_written_even_though_nothing_sets_it(ws: Path):
    """07 §三 B4: the field must exist at write time, never lean on a default."""
    runner, _seen = make_runner({})
    record = accept.run_accept(ws, DONE_RUN, runner=runner)
    on_disk = json.loads((accept.accept_dir(ws) / f"{record['id']}.json").read_text())
    assert "voided" in on_disk
    assert on_disk["voided"] is False


def test_record_carries_the_plan_hashes_and_head(ws: Path, monkeypatch):
    runner, _seen = make_runner({})
    monkeypatch.setattr(accept, "_git_head", lambda _ws: "deadbeef")
    record = accept.run_accept(ws, DONE_RUN, runner=runner)
    # sorted by page so two runs over the same graphs produce the same string
    assert record["requirementVersion"] == "备件台账:b2+设备点检记录:a1"
    assert record["commitHash"] == "deadbeef"
    assert record["at"].endswith("Z")


def test_accept_cmds_defaults(ws: Path):
    assert accept.accept_cmds(ws) == [["pnpm", "typecheck"], ["pnpm", "test:unit"]]


def test_accept_cmds_reads_workspace_json(ws: Path):
    cfg = ws / ".ai-studio" / "workspace.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        json.dumps({"acceptCmds": ["pnpm -w check", "bash -c 'pnpm test -- --run'"]}),
        encoding="utf-8",
    )
    assert accept.accept_cmds(ws) == [["pnpm", "-w", "check"], ["bash", "-c", "pnpm test -- --run"]]


@pytest.mark.parametrize(
    "payload",
    [
        {"acceptCmds": "pnpm typecheck"},  # not a list
        {"acceptCmds": []},  # empty
        {"acceptCmds": ["pnpm ok", 7]},  # a non-string row
        {"acceptCmds": ["   "]},  # whitespace-only -> shlex yields nothing
        "not an object",
    ],
)
def test_a_malformed_acceptcmds_falls_back_whole(ws: Path, payload: Any):
    """Half a command list running is worse than an obviously wrong one."""
    cfg = ws / ".ai-studio" / "workspace.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps(payload), encoding="utf-8")
    assert accept.accept_cmds(ws) == [["pnpm", "typecheck"], ["pnpm", "test:unit"]]


def test_child_env_drops_secrets_and_proxy(monkeypatch):
    for key in (
        "ANTHROPIC_API_KEY",
        "KIROCREW_HOME",
        "CLAUDE_CODE_SOMETHING",
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
    ):
        monkeypatch.setenv(key, "secret")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("CI", "1")
    env = accept.child_env()
    assert not [k for k in env if k.startswith(("ANTHROPIC_", "KIROCREW_", "CLAUDE_"))]
    assert "HTTPS_PROXY" not in env and "https_proxy" not in env and "ALL_PROXY" not in env
    assert env["PATH"] == "/usr/bin"
    assert env["CI"] == "1"


def test_list_records_is_newest_first(ws: Path):
    runner, _seen = make_runner({})
    first = accept.run_accept(ws, DONE_RUN, runner=runner)
    second = accept.run_accept(ws, DONE_RUN, runner=runner)
    # force the order the clock cannot guarantee inside one tick
    for record, stamp in ((first, "2026-01-01T00:00:00Z"), (second, "2026-02-01T00:00:00Z")):
        path = accept.accept_dir(ws) / f"{record['id']}.json"
        record["at"] = stamp
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    (accept.accept_dir(ws) / "broken.json").write_text("{not json", encoding="utf-8")

    records = accept.list_records(ws)
    # the unreadable file is skipped, not a crash
    assert [r["id"] for r in records] == [second["id"], first["id"]]


def test_list_records_without_a_directory_is_empty(ws: Path):
    assert accept.list_records(ws) == []


def test_default_cmds_match_the_ticket():
    assert accept.DEFAULT_CMDS == [["pnpm", "typecheck"], ["pnpm", "test:unit"]]
    assert accept._CMD_TIMEOUT_S == 900
    assert devdag.PHASE == "full"


# ---------------------------------------------------------------------------
# the two accept routes (ACP-2085-S4 §4)


class FakeRun:
    """The scheduler as the routes see it: one dict in, one dict out."""

    def __init__(self, state: dict[str, Any]) -> None:
        self._state = state

    def get(self) -> dict[str, Any]:
        return self._state

    async def start(self, pages: list[str]) -> dict[str, Any]:
        return {"runId": "dev-1", "phase": "full"}

    def log_lines(self, lines: int) -> list[str]:
        return []


class FakeAccept:
    """Stands in for the two entry points the accept routes call.

    Patched onto the module as *functions*, not by replacing ``routes.accept``:
    the handler names ``accept.AcceptError`` in its ``except``, so swapping the
    module object for a fake makes exception handling itself raise — the test
    would report a 500 that the route cannot produce.
    """

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.seen: list[tuple[Path, dict[str, Any]]] = []

    def run_accept(self, ws: Path, state: dict[str, Any], **_kw: Any) -> dict[str, Any]:
        self.seen.append((ws, state))
        if self.error is not None:
            raise self.error
        return {"id": "acc-1", "result": "passed", "voided": False}

    def list_records(self, ws: Path) -> list[dict[str, Any]]:
        return [{"id": "acc-1", "result": "passed"}]


@pytest.fixture()
def fake_accept(monkeypatch):
    def _install(error: Exception | None = None) -> FakeAccept:
        fake = FakeAccept(error)
        monkeypatch.setattr(accept, "run_accept", fake.run_accept)
        monkeypatch.setattr(accept, "list_records", fake.list_records)
        return fake

    return _install


@pytest.fixture()
def route_env(tmp_path, monkeypatch):
    home = tmp_path / "crew"
    home.mkdir()
    monkeypatch.setenv("KIROCREW_HOME", str(home))
    monkeypatch.setattr(routes, "_DEV_RUNS", {})
    ws = tmp_path / "ws"
    ws.mkdir()
    record = projects.create_project("设备管理", "")
    path = projects.projects_root() / record["id"] / "project.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["workspaceDir"] = str(ws)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    app = web.Application()
    app["state"] = object()  # the dev routes need a chat state, any state
    monkeypatch.setattr(routes, "is_app_enabled", lambda _name: True)
    routes.register_routes(app)
    return record["id"], ws, app


@pytest.mark.asyncio
async def test_accept_route_refuses_until_the_run_reports_done(route_env, monkeypatch):
    # the REAL accept module here: 「dev not done」 is decided from the state file,
    # so faking it would test the fake. No command can run — which is the point.
    pid, _ws, app = route_env
    monkeypatch.setattr(routes, "_dev_run_for", lambda *a, **k: FakeRun({"runState": "running"}))
    async with TestClient(TestServer(app)) as client:
        r = await client.post(f"/api/apps/ai-studio/projects/{pid}/accept/run")
        assert r.status == 409
        assert (await r.json())["code"] == "dev_not_done"


@pytest.mark.asyncio
async def test_accept_routes_pass_the_workspace_and_the_run_state_through(
    route_env, monkeypatch, fake_accept
):
    pid, ws, app = route_env
    monkeypatch.setattr(routes, "_dev_run_for", lambda *a, **k: FakeRun(dict(DONE_RUN)))
    fake = fake_accept()
    async with TestClient(TestServer(app)) as client:
        r = await client.post(f"/api/apps/ai-studio/projects/{pid}/accept/run")
        assert r.status == 201
        record = (await r.json())["record"]
        # the envelope the board renders the result out of, verbatim
        assert record["id"] == "acc-1" and record["voided"] is False

        r = await client.get(f"/api/apps/ai-studio/projects/{pid}/accept/records")
        assert r.status == 200
        assert [x["id"] for x in (await r.json())["records"]] == ["acc-1"]

        r = await client.get("/api/apps/ai-studio/projects/p-nope/accept/records")
        assert r.status == 404
        assert (await r.json())["code"] == "project_not_found"
    # the checks are about THIS workspace and THIS run: the requirement version and
    # the 「dev not done」 refusal both come from that pair, not from the request body
    assert fake.seen == [(ws, DONE_RUN)]


@pytest.mark.asyncio
async def test_accept_run_store_failure_is_503(route_env, monkeypatch, fake_accept):
    pid, _ws, app = route_env
    monkeypatch.setattr(routes, "_dev_run_for", lambda *a, **k: FakeRun(dict(DONE_RUN)))
    fake_accept(OSError("read-only file system"))
    async with TestClient(TestServer(app)) as client:
        r = await client.post(f"/api/apps/ai-studio/projects/{pid}/accept/run")
        # a failed record write is retryable and says so, instead of a 500 with no body
        assert r.status == 503
        assert (await r.json())["code"] == "store_write_failed"
