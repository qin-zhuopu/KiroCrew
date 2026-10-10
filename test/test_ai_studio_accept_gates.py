"""The ACP-2226 quality gates: the platform bottom line, AC coverage, weakened
tests, lint, and schema-vs-requirements.

Two disciplines the file must keep. Nothing here may resolve ``pnpm`` — every
command goes through the injected ``runner`` seam, exactly as in
``test_ai_studio_accept.py`` (testing-conventions: a unit test never owns a
long-running child). The one place real ``git`` is forked is
``weakened_tests``, which IS a git reader; those cases build a throwaway repo
under ``tmp_path`` and pass no network remote.

The advisory half of the contract is what most of these cases pin: a gate that
reports must not intercept, and a gate that intercepts must be the one the
operator opted into. Those two sentences are the whole reason the feature can
ship without breaking the deploy gate.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from kiro_crew.apps.builtins.ai_studio.backend import accept

DONE_RUN: dict[str, Any] = {
    "runId": "dev-1",
    "phase": "full",
    "runState": "done",
    "graphHashes": {"备件台账": "b2"},
    "nodes": [{"jiraKey": "备件台账:list", "startCommit": "abc123"}],
}


def make_runner(codes: dict[str, int] | None = None, outputs: dict[str, str] | None = None):
    """``{cmd: exit code}``，默认全 0。记录了跑过哪些命令，好判「没跑」。"""
    seen: list[list[str]] = []
    want = codes or {}
    texts = outputs or {}

    def runner(cmd: list[str], _ws: Path) -> tuple[int, str]:
        key = " ".join(cmd)
        seen.append(list(cmd))
        return want.get(key, 0), texts.get(key, f"output for {key}")

    return runner, seen


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root


def write_workspace_json(ws: Path, payload: Any) -> None:
    cfg = ws / ".ai-studio" / "workspace.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_graph(ws: Path, page: str, payload: Any) -> None:
    path = ws / "docs" / "需求图谱" / f"{page}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_file(ws: Path, rel: str, text: str) -> Path:
    path = ws / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 第 1 条：平台底线不可减（唯一一条改了现有行为的）


def test_workspace_cmds_are_appended_after_the_bottom_line(ws: Path):
    # THE behaviour change of this ticket: acceptCmds used to REPLACE the two
    # platform commands, so a workspace could swap acceptance for `echo ok`.
    # It may only ADD now — the order is stated because the board shows it.
    write_workspace_json(ws, {"acceptCmds": ["pnpm -w check"]})
    assert accept.accept_cmds(ws) == [
        ["pnpm", "typecheck"],
        ["pnpm", "test:unit"],
        ["pnpm", "-w", "check"],
    ]


def test_a_workspace_cannot_drop_one_of_the_two_bottom_line_cmds(ws: Path):
    # The whole point is that a workspace cannot SUBTRACT. Naming the bottom
    # line plus one extra must not read as a redeclaration of the set.
    write_workspace_json(ws, {"acceptCmds": ["pnpm test:unit", "pnpm e2e-smoke"]})
    assert accept.accept_cmds(ws) == [
        ["pnpm", "typecheck"],
        ["pnpm", "test:unit"],
        ["pnpm", "e2e-smoke"],
    ]


def test_replace_semantics_survive_only_behind_an_explicit_flag(ws: Path):
    # The escape hatch the ticket allows: replace is still reachable, but only
    # by a word the workspace wrote on purpose, not by the shape of a list.
    write_workspace_json(ws, {"acceptCmds": ["pnpm -w check"], "acceptCmdsReplace": True})
    assert accept.accept_cmds(ws) == [["pnpm", "-w", "check"]]


def test_replace_flag_with_unusable_cmds_still_runs_the_bottom_line(ws: Path):
    # Opting out and then writing the list wrong must not produce a run of
    # NOTHING: zero commands reported as acceptance is the worst record shape.
    write_workspace_json(ws, {"acceptCmds": ["pnpm ok", 7], "acceptCmdsReplace": True})
    assert accept.accept_cmds(ws) == [["pnpm", "typecheck"], ["pnpm", "test:unit"]]


@pytest.mark.parametrize(
    "payload",
    [
        {"acceptCmds": "pnpm typecheck"},
        {"acceptCmds": ["pnpm ok", 7]},
        {"acceptCmds": ["   "]},
        "not an object",
    ],
)
def test_a_malformed_extra_list_loses_the_extras_never_the_bottom_line(ws: Path, payload: Any):
    # Before this ticket a bad shape fell back to the defaults (the defaults
    # WERE everything). Now falling back would claim the workspace's own checks
    # ran, so the extras are dropped and stated, and the bottom line stays.
    write_workspace_json(ws, payload)
    assert accept.accept_cmds(ws) == [["pnpm", "typecheck"], ["pnpm", "test:unit"]]


def test_no_workspace_json_is_just_the_bottom_line(ws: Path):
    assert accept.accept_cmds(ws) == [["pnpm", "typecheck"], ["pnpm", "test:unit"]]


# ---------------------------------------------------------------------------
# 第 6 条：kind=e2e 默认不跑（本文件不起服务、不开浏览器，只验开关）


def test_an_e2e_cmd_is_skipped_by_default_and_says_so(ws: Path, monkeypatch):
    monkeypatch.delenv(accept.E2E_ENV, raising=False)
    write_workspace_json(ws, {"acceptCmds": [{"cmd": "pnpm test:e2e", "kind": "e2e"}]})
    runner, seen = make_runner()
    record = accept.run_accept(ws, DONE_RUN, runner=runner)
    assert [c[1] for c in seen] == ["typecheck", "test:unit"]
    assert record["skippedCmds"] == ["pnpm test:e2e"]
    # skipped is NOT a green row: an e2e that never ran must not appear as a
    # passing check, or 「验收全绿」 silently includes a test nobody ran.
    assert [r["id"] for r in record["results"]] == ["pnpm typecheck", "pnpm test:unit"]
    assert record["result"] == "passed"


def test_the_e2e_env_switch_runs_it(ws: Path, monkeypatch):
    monkeypatch.setenv(accept.E2E_ENV, "1")
    write_workspace_json(ws, {"acceptCmds": [{"cmd": "pnpm test:e2e", "kind": "e2e"}]})
    runner, seen = make_runner()
    record = accept.run_accept(ws, DONE_RUN, runner=runner)
    assert [c[1] for c in seen] == ["typecheck", "test:unit", "test:e2e"]
    assert record["skippedCmds"] == []
    assert record["results"][-1]["id"] == "pnpm test:e2e"


def test_a_failing_e2e_fails_the_record_when_it_was_switched_on(ws: Path, monkeypatch):
    monkeypatch.setenv(accept.E2E_ENV, "1")
    write_workspace_json(ws, {"acceptCmds": [{"cmd": "pnpm test:e2e", "kind": "e2e"}]})
    runner, _seen = make_runner({"pnpm test:e2e": 1})
    record = accept.run_accept(ws, DONE_RUN, runner=runner)
    assert record["result"] == "failed"


def test_log_files_keep_their_slot_when_a_cmd_is_skipped(ws: Path, monkeypatch):
    # The index comes from the candidate list, not from a run counter: with the
    # switch off, the two logs are -0/-1; with it on, three are -0/-1/-2. A
    # counter would silently renumber the same config between two runs.
    monkeypatch.delenv(accept.E2E_ENV, raising=False)
    write_workspace_json(ws, {"acceptCmds": [{"cmd": "pnpm x", "kind": "e2e"}]})
    runner, _seen = make_runner()
    record = accept.run_accept(ws, DONE_RUN, runner=runner)
    assert [r["logPath"] for r in record["results"]] == [
        f".ai-studio/accept/{record['id']}-0.log",
        f".ai-studio/accept/{record['id']}-1.log",
    ]
    assert (ws / record["results"][1]["logPath"]).is_file()


def test_a_plain_string_cmd_is_still_accepted(ws: Path, monkeypatch):
    # Backwards shape: every workspace written before this ticket uses strings.
    monkeypatch.delenv(accept.E2E_ENV, raising=False)
    write_workspace_json(ws, {"acceptCmds": ["pnpm audit"]})
    assert accept.accept_cmds(ws)[-1] == ["pnpm", "audit"]
    assert accept._cmd_kinds(ws) == {}


def test_an_unknown_kind_is_an_ordinary_cmd(ws: Path, monkeypatch):
    monkeypatch.delenv(accept.E2E_ENV, raising=False)
    write_workspace_json(ws, {"acceptCmds": [{"cmd": "pnpm seed", "kind": "fixture"}]})
    runner, seen = make_runner()
    record = accept.run_accept(ws, DONE_RUN, runner=runner)
    assert [c[1] for c in seen] == ["typecheck", "test:unit", "seed"]
    assert record["skippedCmds"] == []


# ---------------------------------------------------------------------------
# 第 2 条：AC 覆盖


GRAPH_TWO_AC = {
    "page": "备件台账",
    "acceptance": [
        {"id": "AC-1", "text": "列表按更新时间倒序"},
        {"id": "AC-2", "text": "保存后列表刷新"},
    ],
}


def test_ac_coverage_lists_ids_no_test_references(ws: Path):
    write_graph(ws, "备件台账", GRAPH_TWO_AC)
    write_file(ws, "apps/web/src/__tests__/list.spec.ts", "it('AC-1 ok', () => {})\n")
    missing = accept.ac_coverage(ws, ["备件台账"])
    # exactly the uncovered one: 「AC-2」 is nowhere in the corpus
    assert missing == [{"page": "备件台账", "id": "AC-2"}]


def test_ac_coverage_is_green_when_every_id_is_referenced(ws: Path):
    write_graph(ws, "备件台账", GRAPH_TWO_AC)
    write_file(ws, "e2e/spare.spec.ts", "// AC-1 and AC-2\n")
    assert accept.ac_coverage(ws, ["备件台账"]) == []


@pytest.mark.parametrize(
    "rel",
    [
        "apps/api/test/test_spare.py",  # apps/**/test/**
        "apps/web/src/b.test.ts",  # apps/**/*.test.ts*
        "apps/web/src/c.spec.tsx",  # the vitest spelling of the same
        "e2e/notes.txt",  # e2e/** whatever the file is named
    ],
)
def test_each_named_test_location_counts_as_coverage(ws: Path, rel: str):
    # The locations are the ticket's, verbatim. One case each: a single test
    # that deletes files mid-way proves where the corpus ENDS only by accident.
    write_graph(ws, "备件台账", {"acceptance": [{"id": "AC-1"}]})
    write_file(ws, rel, "AC-1")
    assert accept.ac_coverage(ws, ["备件台账"]) == []


def test_a_source_file_outside_the_named_locations_does_not_count(ws: Path):
    # The mirror of the case above: if the search walked src, an AC mentioned in
    # a TODO comment would read as covered and the gate would be decorative.
    write_graph(ws, "备件台账", {"acceptance": [{"id": "AC-1"}]})
    write_file(ws, "apps/web/src/App.tsx", "// TODO AC-1 还没测")
    assert [m["id"] for m in accept.ac_coverage(ws, ["备件台账"])] == ["AC-1"]


def test_a_test_under_node_modules_does_not_count_as_coverage(ws: Path):
    # The package is full of its own *.test.ts. If walking found those, every
    # AC would be covered by someone else's suite and the gate would be green
    # forever — and it would take a minute per run to say so.
    write_graph(ws, "备件台账", GRAPH_TWO_AC)
    write_file(ws, "apps/web/node_modules/dep/test/index.ts", "AC-1 AC-2")
    missing = accept.ac_coverage(ws, ["备件台账"])
    assert [m["id"] for m in missing] == ["AC-1", "AC-2"]


def test_ac_coverage_without_any_test_dir_reports_every_id(ws: Path):
    # 「没写测试」 and 「找不到测试」 are the same answer here, and it is the
    # honest one: nothing references the AC.
    write_graph(ws, "备件台账", GRAPH_TWO_AC)
    missing = accept.ac_coverage(ws, ["备件台账"])
    assert [m["id"] for m in missing] == ["AC-1", "AC-2"]


def test_ac_coverage_on_a_page_with_no_graph_is_empty(ws: Path):
    assert accept.ac_coverage(ws, ["不存在的页"]) == []


def test_an_acceptance_row_without_an_id_is_not_reported(ws: Path):
    # Searching a string the graph never states always yields zero hits, so
    # counting these would manufacture a defect out of a schema difference.
    write_graph(ws, "备件台账", {"acceptance": ["保存后列表刷新", {"text": "无 id"}]})
    assert accept.ac_coverage(ws, ["备件台账"]) == []


def test_pages_come_from_the_run_not_from_the_directory(ws: Path):
    # A page added to the graph mid-round was not promised by this round; a
    # page deleted since still was. The run's hashes are the contract.
    write_graph(ws, "备件台账", GRAPH_TWO_AC)
    write_graph(ws, "新加的页", {"acceptance": [{"id": "AC-9"}]})
    pages = accept._run_pages(DONE_RUN, ws)
    assert pages == ["备件台账"]
    assert accept._run_pages({"graphHashes": {}}, ws) == sorted(["新加的页", "备件台账"])


# ---------------------------------------------------------------------------
# 第 3 条：改松测试检测（真 git，tmp 里的一次性仓库，无远端）


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, f"git {' '.join(args)}: {proc.stdout}{proc.stderr}"
    return proc.stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "test")
    write_file(root, "apps/web/test/a.spec.ts", "it('x', () => {\n  expect(1).toBe(1)\n})\n")
    write_file(root, "apps/web/src/a.ts", "export const a = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def test_head_without_a_base_is_not_guessed(repo: Path):
    # No base means no comparison, and 「查不出」 is not 「没人改测试」.
    head = _git(repo, "rev-parse", "HEAD")
    assert accept.weakened_tests(repo, "", head) == []
    assert accept.weakened_tests(repo, "0" * 40, head) == []


def test_a_deleted_test_file_is_caught(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "apps/web/test/a.spec.ts").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "delete the awkward test")
    found = accept.weakened_tests(repo, base, _git(repo, "rev-parse", "HEAD"))
    assert found == [
        {"file": "apps/web/test/a.spec.ts", "reason": "deleted", "before": None, "after": 0}
    ]


def test_fewer_assertions_in_a_test_file_are_caught(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    write_file(repo, "apps/web/test/a.spec.ts", "it('x', () => {})\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "make it pass")
    found = accept.weakened_tests(repo, base, _git(repo, "rev-parse", "HEAD"))
    assert [f["reason"] for f in found] == ["fewer-assertions"]
    assert (found[0]["before"], found[0]["after"]) == (1, 0)


def test_a_source_file_change_is_not_reported(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    write_file(repo, "apps/web/src/a.ts", "export const a = 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "real fix")
    assert accept.weakened_tests(repo, base, _git(repo, "rev-parse", "HEAD")) == []


def test_a_hardened_test_is_not_reported(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    write_file(
        repo,
        "apps/web/test/a.spec.ts",
        "it('x', () => {\n  expect(1).toBe(1)\n  assert(2)\n})\n",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "tighten")
    assert accept.weakened_tests(repo, base, _git(repo, "rev-parse", "HEAD")) == []


def test_a_deleted_non_test_file_is_not_reported(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "apps/web/src/a.ts").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "drop dead module")
    assert accept.weakened_tests(repo, base, _git(repo, "rev-parse", "HEAD")) == []


def test_the_base_is_the_first_node_start_commit(repo: Path):
    # 「本轮开发开始时的提交」: a fix node is appended LAST, so the last
    # startCommit already contains whatever the dev round did to the tests.
    run = {"nodes": [{"startCommit": ""}, {"startCommit": "second"}]}
    assert accept._first_start_commit(run) == "second"
    assert accept._first_start_commit({"nodes": []}) == ""
    assert accept._first_start_commit({}) == ""


def test_advisory_carries_the_weakened_gate_with_its_window(ws: Path, monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake(ws_arg: Path, base: str, head: str):
        calls.append((base, head))
        return [{"file": "apps/web/test/a.spec.ts", "reason": "deleted"}]

    monkeypatch.setattr(accept, "weakened_tests", fake)
    monkeypatch.setattr(accept, "_git_head", lambda _ws: "headsha")
    rows = accept.build_advisory(ws, DONE_RUN, runner=make_runner()[0])
    assert calls == [("abc123", "headsha")]
    row = [r for r in rows if r["id"] == "weakened-tests"][0]
    assert row["ok"] is False
    assert row["base"] == "abc123" and row["head"] == "headsha"


# ---------------------------------------------------------------------------
# 第 4 条：lint


def test_lint_is_skipped_when_the_workspace_has_no_lint_script(ws: Path):
    row = accept.lint_gate(ws, runner=make_runner()[0])
    assert row["skipped"] is True and row["ok"] is True
    assert row["detail"] == "工作区没有 lint 脚本"


def test_lint_runs_when_the_script_exists(ws: Path):
    write_file(ws, "package.json", json.dumps({"scripts": {"lint": "eslint ."}}))
    runner, seen = make_runner()
    row = accept.lint_gate(ws, runner=runner)
    assert seen == [["pnpm", "lint"]]
    assert row == {
        "id": "lint",
        "ok": True,
        "skipped": False,
        "detail": "pnpm lint",
        "tail": "output for pnpm lint",
    }


def test_a_failing_lint_is_a_red_advisory(ws: Path):
    write_file(ws, "package.json", json.dumps({"scripts": {"lint": "eslint ."}}))
    runner, _seen = make_runner({"pnpm lint": 1}, {"pnpm lint": "  10 problems (1 error)"})
    row = accept.lint_gate(ws, runner=runner)
    # the exit code decides, not the word 「error」 in a summary line
    assert row["ok"] is False and row["skipped"] is False


def test_a_broken_package_json_is_treated_as_no_lint(ws: Path):
    write_file(ws, "package.json", "{not json")
    assert accept.lint_gate(ws, runner=make_runner()[0])["skipped"] is True


def test_a_non_string_lint_script_is_no_lint(ws: Path):
    write_file(ws, "package.json", json.dumps({"scripts": {"lint": None}}))
    assert accept.lint_gate(ws, runner=make_runner()[0])["skipped"] is True


# ---------------------------------------------------------------------------
# 第 5 条：数据库对照需求


def _api_sql(ws: Path, sql: str) -> None:
    write_file(ws, "apps/api/src/db/schema.sql", sql)


def test_schema_reports_a_field_the_table_lacks(ws: Path):
    write_graph(ws, "备件台账", {"fields": [{"code": "deviceName"}, {"code": "spareNo"}]})
    _api_sql(ws, "CREATE TABLE spare (\n  id INTEGER,\n  device_name TEXT\n);")
    missing = accept.schema_vs_requirements(ws, ["备件台账"])
    assert missing == [{"page": "备件台账", "code": "spareNo", "column": "spare_no"}]


def test_a_camel_case_code_matches_a_snake_column(ws: Path):
    # deviceName → device_name is the one mapping worth betting on.
    write_graph(ws, "p", {"fields": [{"code": "deviceName"}]})
    _api_sql(ws, "CREATE TABLE t (device_name TEXT)")
    assert accept.schema_vs_requirements(ws, ["p"]) == []


def test_table_level_constraints_are_not_columns(ws: Path):
    # A composite PRIMARY KEY line starts with a word; counting it as a column
    # is how a schema checker starts reporting a column named 「primary」.
    write_graph(ws, "p", {"fields": [{"code": "primary"}]})
    _api_sql(ws, "CREATE TABLE t (\n  id INT,\n  PRIMARY KEY (id, org_id)\n)")
    missing = accept.schema_vs_requirements(ws, ["p"])
    assert [m["code"] for m in missing] == ["primary"]


def test_parens_inside_a_column_type_do_not_split_the_row(ws: Path):
    write_graph(ws, "p", {"fields": [{"code": "price"}]})
    _api_sql(ws, "CREATE TABLE t (id INT, price DECIMAL(10,2) NOT NULL)")
    assert accept.schema_vs_requirements(ws, ["p"]) == []


def test_schema_gate_is_green_even_when_it_reports(ws: Path):
    # The ticket states 只报告，不拦: name→column mapping has error margin, and
    # an observer in the observe phase must not hold a deploy hostage to noise.
    # The page name is the run's, because that is what build_advisory reads.
    write_graph(ws, "备件台账", {"fields": [{"code": "totallyMissing"}]})
    runner, _seen = make_runner()
    rows = accept.build_advisory(ws, DONE_RUN, runner=runner)
    row = [r for r in rows if r["id"] == "schema-requirements"][0]
    assert row["ok"] is True
    assert row["advisoryOnly"] is True
    assert [m["code"] for m in row["missing"]] == ["totallyMissing"]


def test_a_workspace_without_an_api_dir_reports_the_fields_it_has(ws: Path):
    # 「找不到建表语句」 is stated as 「找不到列」, never as a pass.
    write_graph(ws, "p", {"fields": [{"code": "deviceName"}]})
    missing = accept.schema_vs_requirements(ws, ["p"])
    assert [m["column"] for m in missing] == ["device_name"]


def test_a_non_latin_code_is_not_transcribed(ws: Path):
    # Pinyin would compare a spelling nobody used against a real table name;
    # every report would be a fabrication.
    write_graph(ws, "p", {"fields": [{"code": "设备名称"}]})
    _api_sql(ws, "CREATE TABLE t (device_name TEXT)")
    missing = accept.schema_vs_requirements(ws, ["p"])
    assert [m["column"] for m in missing] == ["设备名称"]


# ---------------------------------------------------------------------------
# 第 7 条：advisory 与 strict 进记录，判定的口径


def _all_green_gates(ws: Path) -> None:
    """Make every advisory green except AC coverage, which stays red.

    AC coverage is the cheapest red to produce (no git needed) and it is the
    one the ticket names, so the strict/non-strict split is proven on it.
    """
    write_graph(ws, "备件台账", {"acceptance": [{"id": "AC-404"}]})


def test_advisory_rows_land_in_the_record_and_do_not_change_the_result(ws: Path, monkeypatch):
    monkeypatch.delenv(accept.STRICT_ENV, raising=False)
    _all_green_gates(ws)
    runner, _seen = make_runner()
    record = accept.run_accept(ws, DONE_RUN, runner=runner)
    assert record["result"] == "passed"
    assert record["strict"] is False
    assert [r["id"] for r in record["advisory"]] == [
        "ac-coverage",
        "weakened-tests",
        "lint",
        "schema-requirements",
    ]
    assert [r for r in record["advisory"] if r["id"] == "ac-coverage"][0]["ok"] is False
    # the gate's red did not touch the verdict: the deploy gate reads `result`
    on_disk = json.loads((accept.accept_dir(ws) / f"{record['id']}.json").read_text("utf-8"))
    assert on_disk["result"] == "passed"


def test_strict_makes_a_red_advisory_fail_the_record(ws: Path, monkeypatch):
    monkeypatch.setenv(accept.STRICT_ENV, "1")
    _all_green_gates(ws)
    runner, _seen = make_runner()
    record = accept.run_accept(ws, DONE_RUN, runner=runner)
    assert record["strict"] is True
    assert record["result"] == "failed"


def test_strict_still_passes_when_every_gate_is_green(ws: Path, monkeypatch):
    monkeypatch.setenv(accept.STRICT_ENV, "1")
    write_graph(ws, "备件台账", {"acceptance": [{"id": "AC-1"}]})
    write_file(ws, "e2e/a.spec.ts", "// AC-1")
    record = accept.run_accept(ws, DONE_RUN, runner=make_runner()[0])
    assert record["result"] == "passed"
    assert all(r["ok"] for r in record["advisory"])


def test_a_failing_command_still_fails_in_non_strict(ws: Path, monkeypatch):
    # The 口径 of the existing two commands is unchanged by this ticket.
    monkeypatch.delenv(accept.STRICT_ENV, raising=False)
    runner, _seen = make_runner({"pnpm test:unit": 1})
    record = accept.run_accept(ws, DONE_RUN, runner=runner)
    assert record["result"] == "failed"
    assert record["strict"] is False


@pytest.mark.parametrize("value", ["", "0", "true", "2"])
def test_strict_only_turns_on_for_exactly_one(monkeypatch, value: str):
    # A gate that flips on for 「strict=false」 would be the worst possible
    # default mistake.
    monkeypatch.setenv(accept.STRICT_ENV, value)
    assert accept.strict_mode() is False
    monkeypatch.setenv(accept.E2E_ENV, value)
    assert accept.e2e_enabled() is False


def test_a_crashing_gate_becomes_a_note_not_a_lost_run(ws: Path, monkeypatch):
    # An observer that can take the verdict down is not an observer. The
    # commands already ran; a KeyError in a new checker must not eat that.
    def boom(*_a: Any, **_k: Any):
        raise RuntimeError("graph had a shape I did not expect")

    monkeypatch.setattr(accept, "ac_coverage", boom)
    monkeypatch.setattr(accept, "schema_vs_requirements", boom)
    record = accept.run_accept(ws, DONE_RUN, runner=make_runner()[0])
    assert record["result"] == "passed"
    assert record["advisory"][0]["missing"] == []


def test_advisory_reuses_the_injected_runner_for_lint(ws: Path):
    # Without this the unit test would fork a real `pnpm lint`, and so would
    # every CI run of this file.
    write_file(ws, "package.json", json.dumps({"scripts": {"lint": "eslint ."}}))
    runner, seen = make_runner()
    accept.run_accept(ws, DONE_RUN, runner=runner)
    assert ["pnpm", "lint"] in seen


def test_record_keeps_every_field_the_board_already_reads(ws: Path):
    # Additive-only contract: these names are what the frontend and the deploy
    # gate already depend on.
    record = accept.run_accept(ws, DONE_RUN, runner=make_runner()[0])
    for key in (
        "id",
        "phase",
        "result",
        "voided",
        "results",
        "requirementVersion",
        "commitHash",
        "at",
    ):
        assert key in record
    assert record["advisory"] and record["skippedCmds"] == []


def test_the_advisory_shape_is_what_the_board_renders(ws: Path):
    record = accept.run_accept(ws, DONE_RUN, runner=make_runner()[0])
    for row in record["advisory"]:
        assert isinstance(row["id"], str) and row["id"]
        assert isinstance(row["ok"], bool)
