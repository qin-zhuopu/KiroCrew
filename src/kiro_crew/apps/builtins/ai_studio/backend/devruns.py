"""Dev runs: the four development phases driven by the BGDD gate (T7, ACP-851).

The workbench's 开发 tab used to be a snapshot-only fixture; the absorption
doc's step 4 (docs/kirocrew-ai-studio-absorption.md § 四) says the four
phases must run the BGDD gate scripts instead of inventing progress. Since
T4 the bgdd repo ships ONE entry — ``tools/gate.ts <stage> --project <dir>``
— which runs a project's declared commands and decides PASS only by exit
code. This module is the adapter: it maps the acceptance doc's four phases
onto gate stages, invokes the gate as a subprocess, and records EVERY phase
outcome — including a refusal to run — as a ``StudioDevRun`` the shipped
DevRunPanel renders unchanged.

The honest-run rules this file lives by:

* a phase PASSES only when its gate's exit code is 0 — nothing here reads
  the gate's prose to grade the work (gate.ts's own discipline, inherited);
* gates run IN ORDER and the run STOPS at the first FAIL — the later phases
  then say ``pending``, because they were never run, which the panel shows
  rather than a fake all-red or a silent all-green;
* the run is recorded whether it passes or fails: the failing gate's log
  path and evidence tail are the artifacts;
* wiring is opt-in environment: ``AI_STUDIO_BGDD_REPO`` (the bgdd checkout
  holding tools/gate.ts) and ``AI_STUDIO_BGDD_PROJECT`` (the gate-project
  directory with its bgdd/gate.json). Unset is a refusal (503), never a
  simulated green run.

Phase → gate mapping (absorption doc § 一: 四阶段「对应 BGDD G1~G7 的展示层
拆分」; the same split the purchase-order/widget manifests use — G1/G5/G6
are graph-side doors the doc-editing loop already closed, G8/G-FE are
skipped by those manifests):

* tasks     → G2 (the design compiles as a graph — the task's input is sound)
* implement → G3 (typecheck + build)
* test      → G7 (generated acceptance tests + e2e)
* build     → G4 (migration + runnable service — the build that can run)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from . import projects

logger = logging.getLogger(__name__)

# the acceptance doc's four phases, in order, each onto its gate stage
PHASE_GATES: list[tuple[str, str]] = [
    ("tasks", "G2"),
    ("implement", "G3"),
    ("test", "G7"),
    ("build", "G4"),
]

# which shipped StudioDevArtifact kind carries each phase's gate log
_PHASE_ARTIFACT = {"tasks": "runtime", "implement": "runtime", "test": "test", "build": "build"}


class DevRunError(Exception):
    """A refusal to start or read a dev run, carried to a stable HTTP code."""

    def __init__(self, message: str, code: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def wiring() -> tuple[str, str] | None:
    """(bgdd_repo, gate_project) from the environment, or None when the
    operator has not pointed the workbench at a gate yet."""
    repo = os.environ.get("AI_STUDIO_BGDD_REPO", "").strip()
    project = os.environ.get("AI_STUDIO_BGDD_PROJECT", "").strip()
    if not repo or not project:
        return None
    return repo, project


def _runs_dir(project_id: str) -> Path:
    d = projects.projects_root() / project_id / "devruns"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _record_path(project_id: str, run_id: str) -> Path:
    return _runs_dir(project_id) / f"{run_id}.json"


def list_runs(project_id: str) -> list[dict[str, Any]]:
    if projects.get_project(project_id) is None:
        raise DevRunError("project not found", "project_not_found", 404)
    out: list[dict[str, Any]] = []
    for p in sorted(_runs_dir(project_id).glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            logger.warning("devruns: unreadable run record %s", p)
    out.sort(key=lambda r: _sort_key(str(r.get("id", ""))), reverse=True)
    return out


def _sort_key(run_id: str) -> tuple[int, int]:
    """dev-<ms> and dev-<ms>-<n> → (ms, n); an unknown id sorts oldest."""
    parts = run_id.removeprefix("dev-").split("-")
    try:
        ms = int(parts[0])
    except (IndexError, ValueError):
        return (0, 0)
    try:
        return (ms, int(parts[1]))
    except (IndexError, ValueError):
        return (ms, 0)


def get_run(project_id: str, run_id: str) -> dict[str, Any]:
    path = _record_path(project_id, run_id)
    if not path.exists():
        raise DevRunError("dev run not found", "run_not_found", 404)
    return json.loads(path.read_text(encoding="utf-8"))


def _run_gate(stage: str, repo: str, gate_project: str, timeout_s: int) -> tuple[int, str]:
    """One gate stage as a subprocess; (exit code, whole output). A gate
    that cannot start or hangs is a FAIL with an explanatory output — the
    run never dies at the transport layer, it lands in the record."""
    try:
        proc = subprocess.run(
            ["npx", "tsx", "tools/gate.ts", stage.lower(), "--project", gate_project],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        raw = exc.stdout or b""
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        return -1, f"gate {stage} timed out after {timeout_s}s\n{text}"
    except OSError as exc:
        return -1, f"gate {stage} could not start: {exc}\n"


def run_dev(
    project_id: str,
    design_version: str,
    release_version: str = "",
    timeout_s: int = 900,
) -> dict[str, Any]:
    """Run the four phases as bgdd gate stages and record the result.

    Blocking by design: the caller offloads it (routes use to_thread), and
    the record is complete the moment the response is — a half-written
    'running' record that nobody owns is how a workbench grows a stuck
    spinner.
    """
    if projects.get_project(project_id) is None:
        raise DevRunError("project not found", "project_not_found", 404)
    wired = wiring()
    if wired is None:
        raise DevRunError(
            "dev runs are not wired on this instance: set AI_STUDIO_BGDD_REPO "
            "and AI_STUDIO_BGDD_PROJECT to the bgdd checkout and gate project",
            "dev_wiring_not_configured",
            503,
        )
    repo, gate_project = wired
    if not (Path(repo) / "tools" / "gate.ts").exists():
        raise DevRunError(
            f"gate entry not found: {repo}/tools/gate.ts (AI_STUDIO_BGDD_REPO "
            "must point at a bgdd checkout containing tools/gate.ts)",
            "gate_entry_missing",
            503,
        )

    # millisecond ids collide when two runs land in the same millisecond
    # (instant in tests, reachable in reality on a fast gate); walk a suffix
    # so every run gets its own record and log directory
    runs = _runs_dir(project_id)
    base = int(time.time() * 1000)
    suffix = 0
    run_dir = runs / f"dev-{base}"
    while run_dir.exists():
        suffix += 1
        run_dir = runs / f"dev-{base}-{suffix}"
    run_id = run_dir.name
    run_dir.mkdir(parents=True)

    phases: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    failed = False
    for phase, stage in PHASE_GATES:
        if failed:
            # never ran — say so, rather than grade a gate that did not run
            phases.append({"name": phase, "status": "pending", "summary": ""})
            continue
        exit_code, out = _run_gate(stage, repo, gate_project, timeout_s)
        log_path = run_dir / f"{phase}-{stage}.log"
        log_path.write_text(out, encoding="utf-8")
        if exit_code == 0:
            phases.append({"name": phase, "status": "done", "summary": f"{stage} PASS"})
        else:
            failed = True
            phases.append(
                {"name": phase, "status": "failed", "summary": f"{stage} FAIL (exit {exit_code})"}
            )
        artifacts.append({"kind": _PHASE_ARTIFACT[phase], "path": str(log_path)})

    rec: dict[str, Any] = {
        "id": run_id,
        # the traceability anchor the panel shows: WHICH design this built,
        # proven by WHICH gate project (gate.ts's own path, not a copy)
        "designVersion": f"{design_version} · gate:{gate_project}",
        "phases": phases,
        "artifacts": artifacts,
    }
    if release_version:
        rec["releaseVersion"] = release_version
    if not failed:
        # the runnable badge rides the same proof as the build phase — G4
        # says a service exists; the version names what was proven, never
        # a promise beyond the gates that ran
        rec["runnableVersion"] = release_version or design_version
    path = _record_path(project_id, run_id)
    with path.open("x", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return rec
