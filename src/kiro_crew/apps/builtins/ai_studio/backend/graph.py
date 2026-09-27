"""The requirement graph read/freeze/regen layer (ACP-847 PoC).

Three endpoints' worth of logic, deliberately thin and deterministic:

* ``load_graph`` maps a ``kg-sem-poc/requirement-graph/v0`` JSON file into the
  wire shape the frontend's ``StudioGraph`` type (website/src/apps/ai-studio/
  studioApi.ts) declares: ``{nodes: [{id,label,kind,doc?}], edges:
  [{from,to,kind}]}``. The mapping is a lossy projection by design — the wire
  type predates the graph schema and carries no anchors/props — and the
  projection is exactly the "mapping layer" the PoC set out to measure.
* ``freeze`` appends an immutable record per version label under
  ``<project>/freezes/``; a second freeze of the same label raises
  ``FreezeError`` (409), the data-is-the-rule reading the StudioFreeze type
  already documents.
* ``regen`` renders an acceptance document (markdown) FROM the graph —
  the graph→doc direction of the BGDD loop — and writes it as a draft via
  the existing project store, so the editor's draft machinery (history,
  commit) applies unchanged.

Like ``projects.py`` this module is synchronous plain file I/O; routes call it
through ``asyncio.to_thread``. The demo graph file ships under this package so
the PoC runs against REAL graph data with zero external state.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from kiro_crew.apps.builtins.ai_studio.backend import projects


class GraphError(Exception):
    """A refused graph operation, with the HTTP status the route should map."""

    def __init__(self, message: str, code: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class FreezeError(GraphError):
    """Re-freezing an already-frozen version (the 409 case)."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message, code, 409)


def bundled_graph_path(name: str = "knowledge-doc-upload-v1") -> Path:
    """The PoC's real graph: the knowledge-doc-upload requirement graph
    (copied from the bgdd仓 requirements/knowledge-doc-upload/ — the same
    bytes, graphId inside is the identity)."""
    if "/" in name or "\\" in name or name in (".", "..") or not name:
        raise GraphError("graph name must be a bare identifier", "invalid_graph_name", 400)
    path = Path(__file__).parent / "graphs" / f"{name}.json"
    if not path.is_file():
        raise GraphError(f"graph {name} not found", "graph_not_found", 404)
    return path


def load_graph(name: str = "knowledge-doc-upload-v1") -> dict[str, Any]:
    """Read the raw graph JSON (the full kg-sem-poc/v0 document)."""
    try:
        doc = json.loads(bundled_graph_path(name).read_text(encoding="utf-8"))
    except ValueError as exc:
        raise GraphError(f"graph json unreadable: {exc}", "graph_unreadable", 500) from exc
    if not isinstance(doc, dict) or "G_structure" not in doc:
        raise GraphError("not a kg-sem-poc requirement graph", "graph_schema_mismatch", 500)
    return doc


# ---------------------------------------------------------------------------
# mapping layer: kg-sem-poc/requirement-graph/v0  →  StudioGraph wire shape
# ---------------------------------------------------------------------------
# The whole mapping is this one table plus edge selection. Node `kind` on the
# wire only speaks requirement | doc | module; the graph speaks
# ComponentView / DomContract|SaveContract|… / semanticRequirements /
# acceptanceScenarios. The PoC's chosen projection (measured and reported in
# ACP-847's conclusion):
#   acceptanceScenarios  → requirement   (what the graph promises, testable)
#   G_structure nodes    → doc           (the design surface the promises land on)
#   G_contract nodes     → module        (the behavioural units between them)
# Edges: a contract's acceptanceScenarioIds becomes a trace edge
# contract→scenario (the wire's trace), and RENDERS (page→component) becomes
# 'depends'. semanticRequirements are NOT emitted as nodes — the wire has no
# kind for them — and with them every CONTRACT_REALIZES and realizes edge
# lands on a dropped endpoint; that whole SR layer is the measured loss of
# the projection, reported in the differential, not hidden.
def to_studio_graph(doc: dict[str, Any]) -> dict[str, Any]:
    """Project a requirement-graph document onto the StudioGraph wire shape.

    Deterministic (declaration order preserved), total (never invents ids),
    and lossy only where the wire type has no slot — each loss is a bullet in
    the ACP-847 differential, not a silent default.
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    for sc in doc.get("acceptanceScenarios", []):
        nodes.append({"id": sc["id"], "label": sc.get("title", sc["id"]), "kind": "requirement"})
    for n in doc.get("G_structure", {}).get("nodes", []):
        label = n.get("props", {}).get("role") or n["id"].split(":", 1)[-1]
        nodes.append({"id": n["id"], "label": label, "kind": "doc"})
    for n in doc.get("G_contract", {}).get("nodes", []):
        nodes.append({"id": n["id"], "label": n["id"].split(":", 1)[-1], "kind": "module"})

    id_set = {n["id"] for n in nodes}
    for e in doc.get("G_structure", {}).get("edges", []):
        if e.get("type") == "RENDERS" and e.get("from") in id_set and e.get("to") in id_set:
            edges.append({"from": e["from"], "to": e["to"], "kind": "depends"})
    for n in doc.get("G_contract", {}).get("nodes", []):
        for sid in n.get("props", {}).get("acceptanceScenarioIds", []):
            if sid in id_set:
                edges.append({"from": n["id"], "to": sid, "kind": "trace"})
    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# freeze: one immutable record per version label, 409 on a duplicate
# ---------------------------------------------------------------------------

def _freezes_dir(project_id: str) -> Path:
    return projects.projects_root() / project_id / "freezes"


def list_freezes(project_id: str) -> list[dict[str, Any]]:
    """Frozen baselines of a project, newest first (StudioFreeze records)."""
    if projects.get_project(project_id) is None:
        return []
    out: list[dict[str, Any]] = []
    d = _freezes_dir(project_id)
    if not d.is_dir():
        return []
    for path in sorted(d.iterdir()):
        if not path.is_file() or path.suffix != ".json":
            continue
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict):
            out.append(rec)
    out.sort(key=lambda r: r.get("time") or 0, reverse=True)
    return out


def freeze(
    project_id: str,
    version: str,
    doc_name: str,
    notes: str = "",
    generated_from: str = "knowledge-doc-upload-v1",
) -> dict[str, Any]:
    """Freeze one graph version as the round's sole basis (StudioFreeze).

    The record IS the rule: one file per version label, created with O_EXCL,
    so a duplicate freeze loses the race to a 409 no matter how many tabs
    click at once. The frozen content itself is NOT copied — the graph is the
    truth and it does not move; the record pins WHICH graph generation it
    pins (``generatedFrom``).
    """
    if projects.get_project(project_id) is None:
        raise GraphError("project not found", "project_not_found", 404)
    if not version or "/" in version or version in (".", ".."):
        raise GraphError("version label required", "invalid_version", 400)
    rec = {
        "version": version,
        "docName": doc_name,
        # StudioFreeze.generatedFrom pins WHICH graph generation this baseline
        # is the basis of — resolve it through the real graph, never guess.
        "generatedFrom": load_graph(generated_from).get("graphId", generated_from),
        "time": time.time(),
        "notes": notes,
    }
    d = _freezes_dir(project_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{version}.json"
    try:
        with path.open("x", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    except FileExistsError:
        raise FreezeError(f"version {version} is already frozen", "already_frozen") from None
    return rec


# ---------------------------------------------------------------------------
# regen: graph → acceptance document draft (the graph→doc direction)
# ---------------------------------------------------------------------------

def render_acceptance_doc(doc: dict[str, Any]) -> str:
    """Mechanically render an acceptance document from the graph.

    Same discipline as bgdd's acceptance-doc-template: one line per graph
    node, every sentence derived from node fields, no prose the graph does
    not hold. Sections follow the template's fixed order: structure,
    contract, scenarios. (The full-template byte parity with the bgdd v2 doc
    is ACP-849's job; this PoC renders the honest mechanical subset.)
    """
    lines: list[str] = []
    lines.append(f"# 验收文档（由图谱 {doc.get('graphId', '?')} 反向生成）")
    lines.append("")
    lines.append("## 1. 结构节点")
    lines.append("")
    for n in doc.get("G_structure", {}).get("nodes", []):
        p = n.get("props", {})
        lines.append(f"- id={n['id']}（{p.get('role', '')}）")
    lines.append("")
    lines.append("## 2. 契约清单")
    lines.append("")
    for n in doc.get("G_contract", {}).get("nodes", []):
        p = n.get("props", {})
        arrow = (
            f"{p['trigger']} → {p['effect']}"
            if p.get("trigger") and p.get("effect")
            else ""
        )
        parts = [p.get("assertion") or arrow]
        if p.get("message"):
            parts.append(f"文案逐字等于「{p['message']}」")
        scen = "、".join(p.get("acceptanceScenarioIds", []))
        suffix = f"（由 {scen} 判定）" if scen else ""
        lines.append(f"- id={n['id']}：{'；'.join(x for x in parts if x)}{suffix}")
    lines.append("")
    lines.append("## 3. 验收场景")
    lines.append("")
    for sc in doc.get("acceptanceScenarios", []):
        lines.append(f"### id={sc['id']} {sc.get('title', '')}")
        lines.append("")
        for i, anchor in enumerate(sc.get("anchors", []), start=1):
            lines.append(f"{i}. {anchor.get('quote', '')}")
        lines.append("")
    return "\n".join(lines) + "\n"


def regen(project_id: str, graph_name: str = "knowledge-doc-upload-v1", doc_name: str = "requirements.md") -> dict[str, Any]:
    """Regenerate the acceptance doc from the graph into the project's draft.

    Writes through ``projects.save_draft`` so the draft history/commit flow is
    the existing one — regen is a producer, not a parallel store.
    """
    graph = load_graph(graph_name)
    content = render_acceptance_doc(graph)
    try:
        saved = projects.save_draft(project_id, doc_name, content)
    except projects.ProjectError as exc:
        raise GraphError(str(exc), exc.code, exc.status) from exc
    return {"doc": saved["name"], "content": content, "generatedFrom": graph.get("graphId", graph_name)}
