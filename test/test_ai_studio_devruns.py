"""Tests for the dev-run adapter: the four phases onto bgdd gate stages.

The gate subprocess is monkeypatched at ``devruns._run_gate`` — what these
tests pin is the ADAPTER's honesty: the phase→stage mapping and order, the
stop-at-first-FAIL (later phases are pending, never graded), the record's
shape (logs land, runnableVersion only after a fully green walk), and the
refusals (no wiring / missing gate entry are 503s, never simulated runs).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kiro_crew.apps.builtins.ai_studio.backend import devruns, projects


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KIROCREW_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture()
def project(home: Path) -> str:
    return projects.create_project("p", "d")["id"]


@pytest.fixture()
def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the wiring env at a fake bgdd checkout (tools/gate.ts present)."""
    repo = tmp_path / "bgdd"
    (repo / "tools").mkdir(parents=True)
    (repo / "tools" / "gate.ts").write_text("// fake entry\n", encoding="utf-8")
    monkeypatch.setenv("AI_STUDIO_BGDD_REPO", str(repo))
    monkeypatch.setenv("AI_STUDIO_BGDD_PROJECT", "examples/widget")
    return repo


class GateSpy:
    """Records every stage invoked; answers from a per-stage exit-code map."""

    def __init__(self, codes: dict[str, int]) -> None:
        self.codes = codes
        self.calls: list[str] = []

    def __call__(self, stage: str, repo: str, gate_project: str, timeout_s: int) -> tuple[int, str]:
        self.calls.append(stage)
        code = self.codes.get(stage, 0)
        return code, f"gate {stage} output\nexit={code}\n"


def test_phase_gate_mapping_and_order(
    project: str, wired: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = GateSpy({})
    monkeypatch.setattr(devruns, "_run_gate", spy)
    rec = devruns.run_dev(project, "v1")
    # the acceptance doc's four phases, in order, on the manifest-proven gates
    assert spy.calls == ["G2", "G3", "G7", "G4"]
    assert [p["name"] for p in rec["phases"]] == ["tasks", "implement", "test", "build"]
    assert all(p["status"] == "done" for p in rec["phases"])
    assert all("PASS" in p["summary"] for p in rec["phases"])
    # a fully green walk earns the runnable badge naming what was proven
    assert rec["runnableVersion"] == "v1"
    assert rec["designVersion"] == "v1 · gate:examples/widget"


def test_run_stops_at_the_first_failed_gate(
    project: str, wired: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = GateSpy({"G3": 1})
    monkeypatch.setattr(devruns, "_run_gate", spy)
    rec = devruns.run_dev(project, "v1")
    # G3 failed → G7/G4 never ran: they are pending, not graded, not faked
    assert spy.calls == ["G2", "G3"]
    st = [p["status"] for p in rec["phases"]]
    assert st == ["done", "failed", "pending", "pending"]
    assert "FAIL" in rec["phases"][1]["summary"]
    # no runnable badge on an unfinished walk
    assert "runnableVersion" not in rec


def test_gate_logs_are_the_artifacts(
    project: str, wired: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = GateSpy({"G7": 2})
    monkeypatch.setattr(devruns, "_run_gate", spy)
    rec = devruns.run_dev(project, "v1")
    kinds = [a["kind"] for a in rec["artifacts"]]
    # only the phases that RAN leave a log: the G7 failure stops the walk
    # before build, and a phase that never ran has nothing to point at
    assert kinds == ["runtime", "runtime", "test"]
    for a in rec["artifacts"]:
        p = Path(a["path"])
        assert p.exists(), a
        if p.name.startswith("test-"):
            assert "G7" in p.read_text(encoding="utf-8")
    # the phases after the stop have no artifact — nothing ran to log
    assert len(rec["artifacts"]) == 3


def test_record_persists_and_lists_newest_first(
    project: str, wired: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(devruns, "_run_gate", GateSpy({}))
    first = devruns.run_dev(project, "v1")
    second = devruns.run_dev(project, "v1", release_version="v2")
    listed = devruns.list_runs(project)
    assert [r["id"] for r in listed] == [second["id"], first["id"]]
    assert listed[0]["releaseVersion"] == "v2"
    assert listed[0]["runnableVersion"] == "v2"
    got = devruns.get_run(project, first["id"])
    assert got == first
    # the record file is readable json on disk
    path = projects.projects_root() / project / "devruns" / f"{first['id']}.json"
    assert json.loads(path.read_text(encoding="utf-8"))["id"] == first["id"]


def test_unwired_instance_refuses_rather_than_simulates(
    project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AI_STUDIO_BGDD_REPO", raising=False)
    monkeypatch.delenv("AI_STUDIO_BGDD_PROJECT", raising=False)
    with pytest.raises(devruns.DevRunError) as exc:
        devruns.run_dev(project, "v1")
    assert exc.value.status == 503
    assert exc.value.code == "dev_wiring_not_configured"


def test_missing_gate_entry_is_a_named_refusal(
    project: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_STUDIO_BGDD_REPO", str(tmp_path / "not-bgdd"))
    monkeypatch.setenv("AI_STUDIO_BGDD_PROJECT", "examples/widget")
    with pytest.raises(devruns.DevRunError) as exc:
        devruns.run_dev(project, "v1")
    assert exc.value.status == 503
    assert exc.value.code == "gate_entry_missing"


def test_unknown_project_and_run_are_404s(wired: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(devruns, "_run_gate", GateSpy({}))
    with pytest.raises(devruns.DevRunError) as exc:
        devruns.run_dev("nope", "v1")
    assert exc.value.status == 404
    with pytest.raises(devruns.DevRunError):
        devruns.get_run("nope", "dev-1")


def test_run_gate_transport_failure_is_a_fail_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a gate that cannot start (npx missing / not executable) must surface
    # as exit != 0 with an explanatory output, never as an exception out
    # of the adapter
    monkeypatch.setattr(devruns.subprocess, "run", _raise_oserror)
    code, out = devruns._run_gate("G2", str(tmp_path), "p", 5)
    assert code == -1
    assert "could not start" in out


def _raise_oserror(*args: Any, **kwargs: Any) -> Any:
    raise OSError("npx not found")


# --------------------------------------------------------------------------
# route surface: the three dev-run endpoints on the real app


def _make_app(monkeypatch, enabled=True):
    from aiohttp import web

    from kiro_crew.apps.builtins.ai_studio.backend import routes

    monkeypatch.setattr(routes, "is_app_enabled", lambda _name: enabled)
    app = web.Application()
    routes.register_routes(app)
    return app


@pytest.mark.asyncio
async def test_routes_devrun_round_trip(home, project, wired, monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(devruns, "_run_gate", GateSpy({}))
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        r = await client.post(
            f"/api/apps/ai-studio/projects/{project}/dev-runs",
            json={"designVersion": "v1", "releaseVersion": "v2"},
        )
        assert r.status == 201
        rec = (await r.json())["run"]
        assert rec["runnableVersion"] == "v2"
        assert [p["status"] for p in rec["phases"]] == ["done"] * 4

        r = await client.get(f"/api/apps/ai-studio/projects/{project}/dev-runs")
        assert r.status == 200
        assert [x["id"] for x in (await r.json())["runs"]] == [rec["id"]]

        r = await client.get(f"/api/apps/ai-studio/projects/{project}/dev-runs/{rec['id']}")
        assert r.status == 200
        r = await client.get(f"/api/apps/ai-studio/projects/{project}/dev-runs/dev-nope")
        assert r.status == 404


@pytest.mark.asyncio
async def test_routes_devrun_unwired_is_503(home, project, monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.delenv("AI_STUDIO_BGDD_REPO", raising=False)
    monkeypatch.delenv("AI_STUDIO_BGDD_PROJECT", raising=False)
    async with TestClient(TestServer(_make_app(monkeypatch))) as client:
        r = await client.post(
            f"/api/apps/ai-studio/projects/{project}/dev-runs", json={"designVersion": "v1"}
        )
        assert r.status == 503
        assert (await r.json())["code"] == "dev_wiring_not_configured"


@pytest.mark.asyncio
async def test_routes_devrun_disabled_app_403(home, wired, monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer

    monkeypatch.setattr(devruns, "_run_gate", GateSpy({}))
    pid = projects.create_project("p2", "d")["id"]
    async with TestClient(TestServer(_make_app(monkeypatch, enabled=False))) as client:
        r = await client.post(f"/api/apps/ai-studio/projects/{pid}/dev-runs", json={})
        assert r.status == 403
