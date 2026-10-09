"""Tests for the AI Studio dev-plan builder (ACP-2085-S4 step 1).

``devplan`` is a pure function of (workspace, page names), so the only fixture
it needs is the graph files whose hash it reads. Nothing here may call the
reqdoc subprocess or a session — hashing is a sha256 over the file bytes, which
is why the module touches no IO beyond that read (testing-conventions).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kiro_crew.apps.builtins.ai_studio.backend import devplan, requirements


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    """A workspace holding two requirement graphs (contents irrelevant: only
    the bytes go into the hash)."""
    req = tmp_path / requirements.REQ_DIR
    req.mkdir(parents=True)
    for page in ("设备点检记录", "备件台账"):
        (req / f"{page}.json").write_text(
            json.dumps({"page": page}, ensure_ascii=False), encoding="utf-8"
        )
    return tmp_path


def test_two_pages_make_four_tasks_in_page_order(ws: Path):
    plan = devplan.build_plan(ws, ["设备点检记录", "备件台账"])
    tasks: list[dict[str, Any]] = plan["tasks"]
    assert len(tasks) == 4
    assert [t["id"] for t in tasks] == [
        "设备点检记录:api",
        "设备点检记录:web",
        "备件台账:api",
        "备件台账:web",
    ]
    assert [t["kind"] for t in tasks] == ["api", "web", "api", "web"]
    assert [t["title"] for t in tasks] == [
        "设备点检记录：后端接口",
        "设备点检记录：前端页面",
        "备件台账：后端接口",
        "备件台账：前端页面",
    ]


def test_only_the_in_page_edge_exists(ws: Path):
    plan = devplan.build_plan(ws, ["设备点检记录", "备件台账"])
    by_id = {t["id"]: t for t in plan["tasks"]}
    assert by_id["设备点检记录:api"]["dependsOn"] == []
    assert by_id["设备点检记录:web"]["dependsOn"] == ["设备点检记录:api"]
    # cross-page order comes from the serial loop, not from a fake dependency
    assert by_id["备件台账:api"]["dependsOn"] == []
    assert by_id["备件台账:web"]["dependsOn"] == ["备件台账:api"]


def test_prompt_carries_the_page_and_never_points_at_a_legacy_page(ws: Path):
    prompt = devplan.task_prompt("设备点检记录", "api")
    assert "「设备点检记录」页面的后端接口" in prompt
    assert "docs/需求图谱/设备点检记录.md" in prompt
    assert "docs/需求图谱/设备点检记录.json" in prompt
    # the de-Amazoned rule (RFC §10 acceptance 14) applies to the prompt too:
    # naming a legacy page is what sends the agent off to copy the old system
    for banned in ("原页面", "旧页面", ".vue", "原接口"):
        assert banned not in prompt


def test_api_and_web_prompts_differ_only_in_the_requirement_line():
    api = devplan.task_prompt("p", "api").splitlines()
    web = devplan.task_prompt("p", "web").splitlines()
    assert len(api) == len(web) == 6
    diff = [i for i, (a, b) in enumerate(zip(api, web)) if a != b]
    # exactly the three lines the kind is allowed to move: the 后端接口/前端页面
    # label, the per-kind requirement, and the commit message that names the label
    assert diff == [0, 3, 4]
    assert api[3].startswith("api：")
    assert web[3].startswith("web：")
    for prompt in (api, web):
        assert prompt[-1] == "最后一句只回复：完成 或 失败：<原因>。"


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        devplan.task_prompt("p", "db")


def test_graph_hashes_are_one_key_per_page(ws: Path):
    plan = devplan.build_plan(ws, ["设备点检记录", "备件台账"])
    hashes = plan["graphHashes"]
    assert set(hashes) == {"设备点检记录", "备件台账"}
    assert hashes["设备点检记录"] == requirements.graph_hash(
        ws / requirements.REQ_DIR / "设备点检记录.json"
    )
    # two different files must not collide into one hash
    assert hashes["设备点检记录"] != hashes["备件台账"]


def test_empty_pages_make_an_empty_plan(ws: Path):
    assert devplan.build_plan(ws, []) == {"tasks": [], "graphHashes": {}}


def test_prompt_defers_to_the_page_developer_agent_when_the_workspace_has_it(tmp_path):
    # ACP-2211：工作区带 .claude/agents/page-developer.md → 只说「先读它」+ 这次的活
    old = devplan.task_prompt("设备清单", "api", tmp_path)
    assert "不要运行任何测试" in old  # 没有 agent 文件：老的长提示照旧
    (tmp_path / ".claude" / "agents").mkdir(parents=True)
    (tmp_path / ".claude" / "agents" / "page-developer.md").write_text("x")
    new = devplan.task_prompt("设备清单", "api", tmp_path)
    assert new.startswith("先完整读 .claude/agents/page-developer.md")
    assert "「设备清单」" in new and new.rstrip().endswith("完成 或 失败：<原因>。")
