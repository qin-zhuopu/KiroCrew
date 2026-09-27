"""The requirement graph read/freeze/regen/distill layer (ACP-847 PoC, T7).

Four endpoints' worth of logic, deliberately thin and deterministic:

* ``distill`` compares a committed doc against the graph's rendered promise
  and writes one ``StudioDistillation`` PROPOSAL record per run — the
  doc→graph direction, the mechanical half (absorbing candidates into the
  graph is the LLM step and is not this endpoint's).

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

import difflib
import json
import re
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
# 'depends'. T7 (ACP-851) closed the measured loss: the semanticRequirements
# layer rides the wire as ``StudioGraph.srs`` — its own array, not a faked
# fourth node kind (the canvas consumers — GraphView's layout table, the demo
# frames — stay byte-identical) — carrying every SR's text/anchor/openRef/
# adopted verbatim plus the canvas-node ids the source edges realise it (the
# CONTRACT_REALIZES targets re-homed onto the SR record), so all 20 SRs and
# every edge that pointed at one survive the projection.
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

    graph: dict[str, Any] = {"nodes": nodes, "edges": edges}
    # The SR layer (T7). Every source SR becomes one wire record — none is
    # dropped — and the edges that pointed AT it (CONTRACT_REALIZES, whose
    # ``from`` is a module the wire kept) are re-homed onto it as ``realizes``
    # ids, so the contract→SR realisation the PoC lost is now carried without
    # inventing a canvas node. Declaration order is preserved.
    src_srs = doc.get("semanticRequirements", [])
    if src_srs:
        sr_ids = {s["id"] for s in src_srs}
        realizers: dict[str, list[str]] = {}
        for grp in ("G_structure", "G_contract"):
            for e in doc.get(grp, {}).get("edges", []):
                to = e.get("to")
                frm = e.get("from")
                if to in sr_ids and frm in id_set:
                    realizers.setdefault(to, []).append(frm)
        srs: list[dict[str, Any]] = []
        for sr in src_srs:
            rec: dict[str, Any] = {
                "id": sr["id"],
                "text": sr.get("text", ""),
                "realizes": realizers.get(sr["id"], []),
            }
            anchor = sr.get("anchor")
            if isinstance(anchor, dict):
                rec["anchor"] = {"ref": anchor.get("ref", ""), "quote": anchor.get("quote", "")}
            if "openRef" in sr:
                rec["openRef"] = sr["openRef"]
            if "adopted" in sr:
                rec["adopted"] = bool(sr["adopted"])
            srs.append(rec)
        graph["srs"] = srs
    return graph


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
        arrow = f"{p['trigger']} → {p['effect']}" if p.get("trigger") and p.get("effect") else ""
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


def distill(
    project_id: str,
    graph_name: str = "knowledge-doc-upload-v1",
    doc_name: str = "requirements.md",
    release_version: str = "",
) -> dict[str, Any]:
    """Distil the project's committed doc against what the graph promises.

    The doc→graph direction of the BGDD loop (T7, ACP-851). Honest mechanical
    subset, the mirror of ``render_acceptance_doc``'s discipline: the graph's
    own rendered promise is diffed against the committed doc, and every
    difference becomes one ``StudioDistillCandidate`` proposal — a heading the
    doc added/removed names its scenario id as the target, anything else is a
    ``modify`` on the doc itself. The record is a PROPOSAL, never an applied
    change: the bundled graph is read truth and absorbing candidates (the LLM
    half of distillation) is out of this endpoint's scope — ``appliedAt``
    stays absent and says so.

    Evidence: each candidate carries ``doc.md § section`` — the nearest
    heading above its diff hunk — so every proposal points at the paragraph
    it was distilled from (the acceptance doc's traceability requirement).
    """
    if projects.get_project(project_id) is None:
        raise GraphError("project not found", "project_not_found", 404)
    docs = {d["name"]: d["content"] for d in projects.list_docs(project_id)}
    if doc_name not in docs:
        raise GraphError(f"doc {doc_name} has no committed version", "doc_not_found", 404)
    graph = load_graph(graph_name)
    baseline = render_acceptance_doc(graph).splitlines()
    current = docs[doc_name].splitlines()

    def section_of(lines: list[str], idx: int) -> str:
        for i in range(min(idx, len(lines) - 1), -1, -1):
            if lines[i].startswith("#"):
                return lines[i].lstrip("#").strip() or "(top)"
        return "(top)"

    def named_id(text: str) -> str | None:
        """the node id a line names (regen writes `### id=KDU-AC-01 …`);
        that id is the graph node this change is ABOUT."""
        m = re.search(r"(?<![A-Za-z0-9])id=([A-Za-z0-9:.:-]+)", text)
        return m.group(1) if m else None

    candidates: list[dict[str, Any]] = []
    seq = 0
    sm = difflib.SequenceMatcher(a=baseline, b=current, autojunk=False)
    for tag, a1, a2, b1, b2 in sm.get_opcodes():
        if tag == "equal":
            continue
        seq += 1
        old = [ln for ln in baseline[a1:a2] if ln.strip()]
        new = [ln for ln in current[b1:b2] if ln.strip()]
        # kind: gone from the doc → a graph promise the doc no longer makes
        # (remove); only in the doc → a promise the graph has yet to earn
        # (add); both sides → modify. target: the id the changed text names.
        if tag == "delete":
            kind, shown, where = "remove", old, ("baseline", a1)
        elif tag == "insert":
            kind, shown, where = "add", new, ("current", b1)
        else:
            kind, shown, where = "modify", new or old, ("current", b1)
        target = next((t for t in (named_id(ln) for ln in shown) if t), doc_name)
        lines_ctx, idx = (baseline, a1) if where[0] == "baseline" else (current, b1)
        candidates.append(
            {
                "id": f"{doc_name[:-3]}-{seq:03d}",
                "kind": kind,
                "target": target,
                "summary": (new[0] if new else old[0] if old else "(blank change)")[:120],
                "evidenceDoc": f"{doc_name} § {section_of(lines_ctx, idx)}",
            }
        )
    rec: dict[str, Any] = {
        "id": f"distill-{int(time.time() * 1000)}",
        "releaseVersion": release_version,
        "status": "done",
        "candidates": candidates,
        # appliedAt deliberately absent: proposals only, the graph has not
        # absorbed anything (see docstring).
        "distilledFromDoc": doc_name,
        "graphId": graph.get("graphId", graph_name),
    }
    d = projects.projects_root() / project_id / "distills"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{rec['id']}.json"
    with path.open("x", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return rec


def list_distills(project_id: str) -> list[dict[str, Any]]:
    """Distillation records of a project, newest first."""
    if projects.get_project(project_id) is None:
        return []
    out: list[dict[str, Any]] = []
    d = projects.projects_root() / project_id / "distills"
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
    out.sort(key=lambda r: r.get("id") or "", reverse=True)
    return out


def regen(
    project_id: str, graph_name: str = "knowledge-doc-upload-v1", doc_name: str = "requirements.md"
) -> dict[str, Any]:
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
    return {
        "doc": saved["name"],
        "content": content,
        "generatedFrom": graph.get("graphId", graph_name),
    }
