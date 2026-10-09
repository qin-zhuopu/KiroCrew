"""跑验收（ACP-2085-S4 第 3 步）。

一轮开发跑完（``devdag`` 的 ``runState=="done"``）之后，对工作区产物跑一组命令，
**只认退出码**，结果一条一份 JSON 落在 ``<工作区>/.ai-studio/accept/``。

和 07 §〇-2 的验收区块比，这一版有意少做（别照文档补）：不跑 01~09 那套端到端
断言集，只跑工作区自己的 ``typecheck`` / ``test:unit`` 一类命令；不打 git tag；
没有「继续开发完整版 / 回退改需求」两个按钮，因此也就没有 ``voided`` 的翻转 ——
但 ``voided`` 字段**一定写**，07 §三 B4 明写「生成时必为 ``false``（字段必须存
在，不许靠缺省）」，缺了它下游（08 的形态判定）会按「没作废」的缺省猜，而这条
路径上没有任何东西保证那个缺省是对的。

命令是外部进程，环境里要去掉网关自己的模型/密钥与代理变量：验收跑的是工作区的
``pnpm``，它不该拿到网关的 key，也不该被网关的代理绕到国外去（同
``devserver._child_env`` 的道理）。

ACP-2226 加了一圈质量门禁（AC 覆盖、改松测试、lint、库表对照需求）。它们默认**只
报告不拦截**：结果里多出 ``advisory`` 几条，``result`` 仍旧只由命令的退出码决定。
只有 ``AI_STUDIO_ACCEPT_STRICT=1`` 才让 advisory 的红灯参与判定 —— 一个新加的
检查第一版必然有误报，误报去拦人的部署就是把一种病换成另一种病。唯一例外是底线
命令不可减（第 1 条）：那是拦截，因为它的价值恰恰在于绕不掉。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from kiro_crew.apps.builtins.ai_studio.backend import devdag, requirements

logger = logging.getLogger(__name__)

#: 工作区没配 ``acceptCmds`` 时跑这两条（webapp-template 的根 script）。
#: 从 ACP-2226 起它们同时是**平台底线**：工作区只能往后面加，不能换掉、不能删。
#: 之所以要升格：``acceptCmds`` 出自工作区里的一份 json，而工作区是被开发的仓 ——
#: 一句 ``"acceptCmds": ["echo ok"]`` 就把整道验收换了，而部署门禁（``deploy.py`` /
#: ``prodserver``）只认记录的 ``result=="passed"``，看不出跑的是什么。
DEFAULT_CMDS: list[list[str]] = [["pnpm", "typecheck"], ["pnpm", "test:unit"]]

#: 一条验收命令的上限。typecheck + 单测在正常仓里是分钟级；900 秒是给「装依赖
#: 顺带跑一遍」留的余量，同时保证一个卡死的子进程不会永远占着线程。
_CMD_TIMEOUT_S = 900

#: 输出只留最后这么多行：一条失败的 tsc 能喷几千行，整份塞进记录会把看板拖死，
#: 而判定要的证据恰恰在尾巴上。尾巴是给**人**在看板上扫的，完整输出落文件是给
#: 助手读的（ACP-2210：〔让助手修复〕的提示词只给路径，绝不把几千行塞进一轮对话）。
_TAIL_LINES = 40

#: 同 devserver 的子进程环境（``devserver.py:71``）：网关自己的模型/密钥/数据目录
#: 不许漏给工作区的命令。
_ENV_DROP_PREFIXES = ("ANTHROPIC_", "KIROCREW_", "CLAUDE_")

#: 代理变量也一律不带：验收跑的是本地 pnpm，挂了代理反而绕道国外（本机的
#: 全局纪律）。``NO_PROXY`` 留着 —— 它只做排除，不路由。
_ENV_DROP_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


class AcceptError(Exception):
    """A refused acceptance run, with the HTTP status the route maps."""

    def __init__(self, message: str, code: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def accept_dir(ws: Path) -> Path:
    return ws / ".ai-studio" / "accept"


#: 完整输出的落点（相对工作区，ACP-2210）。写成常量而不是从 :func:`accept_dir`
#: 反推：``logPath`` 是**记录里给助手读的路径**，它必须与工作区怎么解析无关 ——
#: ``workspace_dir`` 对同一项目可以给出不止一个绝对写法（软链、相对根），
#: ``relative_to`` 在那种现场会直接抛。
_LOG_DIR_REL = ".ai-studio/accept"


#: 一条 ``acceptCmds`` 行的两种写法：裸字符串，或 ``{"cmd": …, "kind": …}``。
#: ``kind`` 只有 ``e2e`` 有语义（见 :data:`E2E_KIND`），别的值按普通命令处理。
E2E_KIND = "e2e"

#: ``kind=e2e`` 的命令默认**不跑**。端到端要起服务、要浏览器，一轮几十分钟，把它
#: 塞进默认验收等于让每次〔跑验收〕都变成一次长跑。开关在 master 手里（ACP-2226
#: 第 6 条：这一版只做开关，不在网关侧跑 e2e）。
E2E_ENV = "AI_STUDIO_ACCEPT_E2E"

#: 质量检查参与判定的开关（ACP-2226 第 7 条）。
STRICT_ENV = "AI_STUDIO_ACCEPT_STRICT"


def _env_on(name: str) -> bool:
    return os.environ.get(name, "").strip() == "1"


def _read_workspace_json(ws: Path) -> dict[str, Any]:
    path = ws / ".ai-studio" / "workspace.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _bottom_line() -> list[list[str]]:
    return [list(cmd) for cmd in DEFAULT_CMDS]


def accept_cmds(ws: Path) -> list[list[str]]:
    """平台底线 :data:`DEFAULT_CMDS` **加上**工作区 ``acceptCmds`` 里的额外命令。

    ACP-2226 第 1 条改过语义：原来 ``acceptCmds`` 是**整体替换**底线，也就是工作区
    里一份谁都能写的 json 可以把验收换成一条 ``echo ok``。现在工作区只能往后面**加**
    （和底线重复的去重）。唯一保留的退出口是显式的 ``acceptCmdsReplace: true`` ——
    要换就白纸黑字换，看板与记录里看得见，不再由一份命令列表悄悄完成。

    额外命令的形状不对就整份丢掉额外、**底线照跑**（和改造前相反：那时形状不对是
    退回默认，因为默认就是全部；现在退回默认等于把「工作区加的没跑」说成「跑过了」）。
    """
    raw = _read_workspace_json(ws)
    if raw.get("acceptCmdsReplace") is True:
        extra = _extra_cmds(raw)
        return extra or _bottom_line()
    return _dedupe([*_bottom_line(), *_extra_cmds(raw)])


def _extra_cmds(raw: dict[str, Any]) -> list[list[str]]:
    """``acceptCmds`` 拆成 argv 列表；任何一行形状不对就整份作废（回空）。

    整份而不挑能用的：一半能跑一半被静默丢掉的验收，比一份明显跑错的更难发现。
    """
    rows = raw.get("acceptCmds")
    if not isinstance(rows, list) or not rows:
        return []
    out: list[list[str]] = []
    for item in rows:
        text = _cmd_text(item)
        if text is None:
            return []
        parts = shlex.split(text)
        if not parts:
            return []
        out.append(parts)
    return out


def _cmd_text(item: Any) -> str | None:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        cmd = item.get("cmd")
        if isinstance(cmd, str) and cmd.strip():
            return cmd
    return None


def _dedupe(cmds: list[list[str]]) -> list[list[str]]:
    """按 ``argv`` 拼出的字符串去重，保持先来后到的顺序。"""
    seen: set[str] = set()
    out: list[list[str]] = []
    for cmd in cmds:
        key = " ".join(cmd)
        if key in seen:
            continue
        seen.add(key)
        out.append(cmd)
    return out


def e2e_enabled() -> bool:
    return _env_on(E2E_ENV)


def strict_mode() -> bool:
    return _env_on(STRICT_ENV)


def _cmd_kinds(ws: Path) -> dict[str, str]:
    """``" ".join(argv) -> kind``，只收带 ``kind`` 的那些行。

    命令文本是键：``run_accept`` 手里只有 argv，而 ``id`` 就是 argv 拼出来的串，两边
    天然对得上。底线命令永远不带 ``kind``，所以这一份只可能由工作区的那些行产生。
    """
    raw = _read_workspace_json(ws)
    rows = raw.get("acceptCmds")
    if not isinstance(rows, list):
        return {}
    out: dict[str, str] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        text = _cmd_text(item)
        kind = item.get("kind")
        if text is None or not isinstance(kind, str) or not kind.strip():
            continue
        parts = shlex.split(text)
        if parts:
            out[" ".join(parts)] = kind.strip()
    return out


def child_env() -> dict[str, str]:
    """当前环境去掉模型/密钥类和代理变量。"""
    return {
        k: v
        for k, v in os.environ.items()
        if k not in _ENV_DROP_KEYS and not k.startswith(_ENV_DROP_PREFIXES)
    }


def _run_cmd(cmd: Sequence[str], ws: Path) -> tuple[int, str]:
    """真跑一条命令，回 (退出码, 合并输出)。命令不存在按退出码 127 记。"""
    try:
        proc = subprocess.run(
            list(cmd),
            cwd=str(ws),
            env=child_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_CMD_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError:
        return 127, f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {_CMD_TIMEOUT_S}s"
    except OSError as exc:
        return 127, f"could not run {cmd[0]}: {exc}"
    # 两路都留：pnpm 把报错丢 stderr，而尾巴是判定唯一的证据。用 \n 而不是
    # os.linesep，记录里的行形状就不随平台变。
    return proc.returncode, "\n".join(p for p in (proc.stdout, proc.stderr) if p)


def _text_tail(output: str) -> str:
    rows = (output or "").splitlines()
    return "\n".join(rows[-_TAIL_LINES:])


def _requirement_version(run: dict[str, Any]) -> str:
    """本轮各页图谱 hash 拼起来（07 §三 B4「验收记录可追溯到 requirementVersion」）。

    读的是**开发开始时**写进状态文件的那一份（``devdag.start`` 存），不在验收时
    重算 —— 重算会把「开发途中需求又改了」这件事抹平，而那条信息恰恰是这条记录
    唯一的用处。
    """
    hashes = run.get("graphHashes")
    if not isinstance(hashes, dict):
        return ""
    return "+".join(f"{page}:{hashes[page]}" for page in sorted(hashes))


def _git_head(ws: Path) -> str:
    return devdag.git_head(ws)


# ---------------------------------------------------------------------------
# 质量门禁（ACP-2226）：每条一个纯函数，默认只报告不拦截
# ---------------------------------------------------------------------------


def _git_out(ws: Path, args: list[str]) -> str | None:
    """跑一条只读的 git 命令，回 stdout；跑不动/不是仓库回 None。

    超时给 60 秒就够：这些命令只读对象库，不碰工作树。回 None 而不是抛 —— 一轮
    验收因为「查不到 base 提交」整个失败，会让人以为代码坏了。
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(ws), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _run_pages(run: dict[str, Any], ws: Path) -> list[str]:
    """本轮覆盖的页名。

    优先用**开发开始时**记下的那一份（``graphHashes`` 的键）：验收要对照的是这一轮
    承诺过的需求，不是此刻盘上长出来的新页。没记到才退回扫目录，否则状态文件一坏，
    AC 覆盖就变成「一条都没查」的空绿。
    """
    hashes = run.get("graphHashes")
    if isinstance(hashes, dict) and hashes:
        return sorted(str(p) for p in hashes)
    req_dir = ws / requirements.REQ_DIR
    if not req_dir.is_dir():
        return []
    return sorted(p.stem for p in req_dir.glob("*.json") if p.is_file())


def _graph_json(ws: Path, page: str) -> dict[str, Any]:
    path = ws / requirements.REQ_DIR / f"{page}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _ac_ids(graph: dict[str, Any]) -> list[str]:
    """图谱 ``acceptance`` 里的验收条 id（保持顺序）。

    条目可能是 ``{"id": "AC-1", …}``，也可能就是一句字符串（老图谱）：那种没有
    可搜的标识，跳过而不是判它「没覆盖」—— 搜一个不存在的串永远搜得到零结果，
    报出来就是一条假缺陷。
    """
    rows = graph.get("acceptance")
    if not isinstance(rows, list):
        return []
    out: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            rid = row.get("id")
            if isinstance(rid, str) and rid.strip():
                out.append(rid.strip())
        elif isinstance(row, str) and row.strip().startswith("AC-"):
            out.append(row.strip().split()[0])
    return out


#: 找测试文件的三处（派工单第 2 条）：apps 下的 test 目录、apps 下的 *.test.*、e2e。
_TEST_DIR_NAMES = ("test", "tests", "__tests__")
_TEST_SUFFIXES = (".test.ts", ".test.tsx", ".test.js", ".test.jsx", ".spec.ts", ".spec.tsx")
#: 单个测试文件读进来搜字符串的上限。一个仓里的测试文件是 KB 级，超一倍基本是
#: 误把构建产物当源码，读它只是把内存换成一次假阴性。
_TEST_MAX_BYTES = 2_000_000

#: 走目录时整棵剪掉的目录名。两重理由：一是**快**（真实工作区 `apps/**` 底下是几万
#: 个 node_modules 文件，走一遍就是几十秒，而验收后面还跟着部署）；二是**准**——
#: 依赖包里也有 `*.test.ts`，里面万一出现 `AC-12` 就把一条没测的需求算成已覆盖。
_SKIP_DIR_NAMES = frozenset(
    {
        "node_modules",
        ".git",
        "dist",
        "build",
        "coverage",
        ".next",
        ".vite",
        "__pycache__",
        ".venv",
        "venv",
        ".pytest_cache",
        ".ai-studio",
    }
)


def _walk_files(root: Path):
    """深度优先遍历 `root` 下的文件，命中 :data:`_SKIP_DIR_NAMES` 的目录整棵不进去。

    不用 `rglob`：它已经把目录走完了才让调用方过滤，剪不掉那几秒。
    """
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir():
                    if entry.name not in _SKIP_DIR_NAMES:
                        stack.append(entry)
                    continue
                if entry.is_file():
                    yield entry
            except OSError:
                # 悬空软链（is_dir/is_file 都 False）与走中途被删的文件都到这里
                continue


def _test_files(ws: Path) -> list[Path]:
    """工作区里可能引用 AC id 的文件（不存在就是空列表，新项目没测试是正常态）。"""
    out: list[Path] = []
    for root_name in ("apps", "e2e"):
        root = ws / root_name
        if not root.is_dir():
            continue
        for path in _walk_files(root):
            try:
                if path.stat().st_size > _TEST_MAX_BYTES:
                    continue
            except OSError:
                continue
            rel_parts = {p.lower() for p in path.relative_to(ws).parts[:-1]}
            name = path.name.lower()
            if (
                root_name == "e2e"
                or rel_parts & set(_TEST_DIR_NAMES)
                or name.endswith(_TEST_SUFFIXES)
            ):
                out.append(path)
    return sorted(out)


def ac_coverage(ws: Path, pages: Sequence[str]) -> list[dict[str, Any]]:
    """没被任何测试引用的需求验收条（第 2 条）。

    搜的是 id 字符串本身，不做语义匹配：需求写「AC-12 保存后列表刷新」，测试里只要
    出现 ``AC-12`` 就算挂上。这一层要拦的是「压根没写这条的测试」，不是「测试写得
    对不对」—— 后者判不了，硬判就是把门禁的信用花在一件猜不准的事上。
    """
    files = _test_files(ws)
    corpus: list[str] = []
    for path in files:
        try:
            corpus.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    missing: list[dict[str, Any]] = []
    for page in pages:
        for rid in _ac_ids(_graph_json(ws, page)):
            if not any(rid in text for text in corpus):
                missing.append({"page": page, "id": rid})
    return missing


#: 算「断言变少」的行。``expect(`` 是 vitest/playwright 的写法，``assert`` 是
#: Python 与测试里手写的；只数行首附近的关键字，注释里的 assert 少一行不算改松
#: （真要防注释里的断言，就得先有个 python 解析器，而这一条只需要抓「删测试」）。
_ASSERT_RE = re.compile(r"(?:^|[\s(.])(?:assert\b|expect\()")


def _is_test_path(path: str) -> bool:
    parts = [p.lower() for p in path.replace("\\", "/").split("/")[:-1]]
    name = path.rsplit("/", 1)[-1].lower()
    if name.endswith(_TEST_SUFFIXES):
        return True
    if name.startswith("test_") and name.endswith(".py"):
        return True
    return bool({p for p in parts if p in set(_TEST_DIR_NAMES)})


def _count_assertions(text: str) -> int:
    return sum(1 for line in text.splitlines() if _ASSERT_RE.search(line))


def _blob(ws: Path, rev: str, path: str) -> str | None:
    out = _git_out(ws, ["show", f"{rev}:{path}"])
    return out if out is not None else None


def weakened_tests(ws: Path, base: str, head: str) -> list[dict[str, Any]]:
    """本轮里被删掉的测试文件、或断言变少的测试文件（第 3 条）。

    为什么单独查这一条：单测是开发助手自己写的，验收又只认退出码 —— 改松一条断言
    就能把红灯改成绿灯，而记录上写着 passed。修复轮（``kind=="fix"``）之后尤其要看：
    那一轮的目标就是「让验收过」，最省力的走法正是动测试。

    两个保守处：
      * 只比**同一文件**在 base 与 head 的断言行数。文件被改名成非测试路径、或把断言
        拆进 helper，都会报出来 —— 这一条是提示，让人去看一眼，不替人定罪。
      * 拿不到 base/head（没提交、不是仓库、base 已被改写）就回空列表。查不出是查
        不出，不是「有人改了测试」。
    """
    if not base or not head:
        return []
    diff = _git_out(ws, ["diff", "--name-status", f"{base}..{head}"])
    if diff is None:
        return []
    out: list[dict[str, Any]] = []
    for line in diff.splitlines():
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        status, path = fields[0], fields[1]
        new_path = fields[2] if len(fields) > 2 else path
        if status.startswith("D"):
            if _is_test_path(path):
                out.append({"file": path, "reason": "deleted", "before": None, "after": 0})
            continue
        if not _is_test_path(new_path):
            continue
        # 改名的旧路径在 fields[1]，其余状态两者同值
        before_text = _blob(ws, base, path)
        after_text = _blob(ws, head, new_path)
        if before_text is None or after_text is None:
            continue
        before = _count_assertions(before_text)
        after = _count_assertions(after_text)
        if after < before:
            out.append(
                {"file": new_path, "reason": "fewer-assertions", "before": before, "after": after}
            )
    return out


def lint_gate(ws: Path, runner: Callable | None = None) -> dict[str, Any]:
    """工作区根 ``package.json`` 有 ``lint`` 脚本就跑 ``pnpm lint``（第 4 条）。

    只认退出码，和命令验收一个口径：lint 的输出里出现 error 字样不代表失败（一条
    warning 的文案里就可能写着 error）。没有 lint 脚本是**跳过**而不是失败 —— 模板
    里没配 lint 的项目不少，把它算成红灯就是逼每个项目先补一份 eslint 配置。
    """
    pkg = ws / "package.json"
    try:
        raw = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = None
    scripts = raw.get("scripts") if isinstance(raw, dict) else None
    has_lint = isinstance(scripts, dict) and isinstance(scripts.get("lint"), str)
    if not has_lint:
        return {"id": "lint", "ok": True, "skipped": True, "detail": "工作区没有 lint 脚本"}
    call = runner or _run_cmd
    code, output = call(["pnpm", "lint"], ws)
    return {
        "id": "lint",
        "ok": code == 0,
        "skipped": False,
        "detail": "pnpm lint",
        "tail": _text_tail(output),
    }


#: 建表语句开头。表名后面到**配平的右括号**之间是列定义，所以这里只吃开头，正文
#: 交给 :func:`_split_column_defs`（列里可能带 ``DECIMAL(10,2)``，按逗号切会切错）。
_CREATE_RE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([`\"\[]?[\w.]+[`\"\]]?)", re.I)


def _table_body(sql: str, open_at: int) -> str:
    """从第一个 ``(`` 起取到配平的右括号。取不平（语句被截断）就到文末。"""
    depth = 0
    for i in range(open_at, len(sql)):
        if sql[i] == "(":
            depth += 1
        elif sql[i] == ")":
            depth -= 1
            if depth == 0:
                return sql[open_at + 1 : i]
    return sql[open_at + 1 :]


def _split_column_defs(body: str) -> list[str]:
    """按**顶层**逗号切列定义（括号里的逗号不算）。"""
    rows: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            rows.append("".join(current))
            current = []
            continue
        current.append(ch)
    rows.append("".join(current))
    return [r.strip() for r in rows if r.strip()]


#: 不是列名的开头（表级约束）。它们的第一个词会被当成列名，必须跳过。
_CONSTRAINT_WORDS = (
    "primary",
    "foreign",
    "unique",
    "key",
    "index",
    "constraint",
    "check",
    "fulltext",
    "spatial",
    "exclude",
    "period",
)


def _schema_columns(ws: Path) -> dict[str, set[str]]:
    """``apps/api/src/**`` 里 CREATE TABLE 的 ``{表名: {列名,…}}``。

    只扫 SQL 和迁移常待的那几种后缀。alembic 的 ``op.create_table`` 这类 python DSL
    没解析（派工单第 5 条要的是「对照需求找缺列」，抓不到建表语句就报「找不到」，
    比假装抓到强）。
    """
    root = ws / "apps" / "api" / "src"
    out: dict[str, set[str]] = {}
    if not root.is_dir():
        return out
    for path in _walk_files(root):
        if path.suffix.lower() not in (".sql", ".py", ".ts", ".js"):
            continue
        try:
            if path.stat().st_size > _TEST_MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in _CREATE_RE.finditer(text):
            open_at = text.find("(", match.end())
            if open_at < 0:
                continue
            table = match.group(1).strip('`"[]').split(".")[-1].lower()
            cols = out.setdefault(table, set())
            for row in _split_column_defs(_table_body(text, open_at)):
                first = row.split()[0].strip('`"[]').lower()
                if first and first not in _CONSTRAINT_WORDS:
                    cols.add(first)
    return out


def _snake(code: str) -> str:
    """需求里的字段 ``code`` → 库名列的写法：驼峰转下划线、全小写。

    只处理拉丁字母的大小写边界。非拉丁（中文 ``code``）**原样留着**：不转拼音，
    转了就是拿一套没人用过的拼写去比真表名，报出来的缺列全是假的。
    """
    raw = (code or "").strip()
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", raw)
    return re.sub(r"[^0-9a-zA-Z_一-鿿]+", "_", spaced).strip("_").lower()


def schema_vs_requirements(ws: Path, pages: Sequence[str]) -> list[dict[str, Any]]:
    """需求里有、库表里找不到的字段（第 5 条）。

    比的是「需求 ``fields[].code`` 的下划线小写形」和「任一 CREATE TABLE 的任一列名」。
    故意宽（跨表找、不比表名）：字段名到列名的映射有误差（``deviceName`` vs
    ``dev_name``），先窄就是在制造误报。表名与列的对应关系另说，先观察。
    """
    tables = _schema_columns(ws)
    all_cols = {c for cols in tables.values() for c in cols}
    loose = {c.replace("_", "") for c in all_cols}
    missing: list[dict[str, Any]] = []
    for page in pages:
        fields = _graph_json(ws, page).get("fields")
        if not isinstance(fields, list):
            continue
        for row in fields:
            if not isinstance(row, dict):
                continue
            code = row.get("code")
            if not isinstance(code, str) or not code.strip():
                continue
            snake = _snake(code)
            if not snake:
                continue
            if snake in all_cols or snake.replace("_", "") in loose:
                continue
            missing.append({"page": page, "code": code, "column": snake})
    return missing


def build_advisory(
    ws: Path, run: dict[str, Any], *, runner: Callable | None = None
) -> list[dict[str, Any]]:
    """跑一圈质量门禁，返回 advisory 行（顺序固定，看板按它渲染）。

    每个门禁都包在 ``except`` 里：一条新加的检查崩了（图谱字段形状意外、git 对象库
    坏了）只能让它自己变成一条看不懂的提示，不能把整轮验收带走 —— 那一轮的命令其实
    已经跑完了，判定不该由一个旁路观察器来做。
    """
    pages = _run_pages(run, ws)
    rows: list[dict[str, Any]] = []

    # `or []` on every one: a gate that crashed returns None, and a record whose
    # `missing` is null makes the board do `null.map`. The shape of the record is
    # a contract the frontend reads without a guard, so it is normalised here.
    missing = _safe(ac_coverage, ws, pages) or []
    rows.append({"id": "ac-coverage", "ok": not missing, "missing": missing})

    base = _first_start_commit(run)
    head = _git_head(ws)
    weakened = _safe(weakened_tests, ws, base, head) or []
    rows.append(
        {
            "id": "weakened-tests",
            "ok": not weakened,
            "missing": weakened,
            "base": base,
            "head": head,
        }
    )

    rows.append(_safe(lint_gate, ws, runner=runner) or _gate_broke("lint"))

    # 第 5 条明写「只报告，不拦」：字段名 → 列名的映射有误差，误报拦在部署前就是把
    # 观察期的噪声变成人质。所以这一行恒 ok，缺的列进 missing 给人看。
    schema_missing = _safe(schema_vs_requirements, ws, pages) or []
    rows.append(
        {
            "id": "schema-requirements",
            "ok": True,
            "missing": schema_missing,
            "advisoryOnly": True,
        }
    )
    return rows


def _safe(fn: Callable[..., Any], *args: Any, **kw: Any) -> Any:
    """跑一个门禁，异常吞掉回 ``None``（调用方按「没查出东西」处理）。"""
    try:
        return fn(*args, **kw)
    except Exception:  # noqa: BLE001: 见 build_advisory —— 旁路观察器不许带走判定
        logger.exception("ai-studio quality gate %s crashed", fn.__name__)
        return None


def _gate_broke(gate_id: str) -> dict[str, Any]:
    return {
        "id": gate_id,
        "ok": True,
        "skipped": True,
        "detail": "该门禁执行失败，本轮未检查（看网关日志）",
    }


def _first_start_commit(run: dict[str, Any]) -> str:
    """本轮开发开始时的提交 = 第一个节点的 ``startCommit``。

    为什么是第一个而不是最后一个：要抓的是「这一整轮里测试被改松了没有」。修复节点
    是追加在末尾的，它的 ``startCommit`` 已经含着开发轮改过的测试，拿它当基准就只能
    看见修复那一步的改动，改在开发轮里的断言正好溜过去。
    """
    nodes = run.get("nodes")
    if not isinstance(nodes, list):
        return ""
    for node in nodes:
        if not isinstance(node, dict):
            continue
        start = node.get("startCommit")
        if isinstance(start, str) and start.strip():
            return start.strip()
    return ""


def run_accept(ws: Path, run: dict[str, Any], *, runner: Callable | None = None) -> dict:
    """逐条跑验收命令，落一条记录，返回该记录。

    ``runner(cmd, ws) -> (returncode, output)`` 是可注入的替身（单测不起真进程）。

    每条命令的**完整输出**另外落一份 ``.ai-studio/accept/<记录id>-<序号>.log``，
    记录里带 ``logPath``（相对工作区）。为什么要两份：看板要的是尾巴 40 行，而
    〔让助手修复〕要把证据交给助手 —— 塞进提示词是几千行 token，只给尾巴又常常
    看不到失败的那一行（pytest 的 traceback 在中间，尾巴是覆盖率表）。

    ACP-2226 之后另外落两件事：``kind=="e2e"`` 的命令默认不跑（记在 ``skippedCmds``，
    不冒充成一条绿灯），以及一圈质量门禁 ``advisory`` —— 默认 ``strict=False``，
    ``result`` 仍旧**只由命令的退出码决定**。
    """
    if run.get("runState") != "done":
        raise AcceptError("dev not done", "dev_not_done", 409)
    call = runner or _run_cmd
    record_id = f"acc-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    directory = accept_dir(ws)
    directory.mkdir(parents=True, exist_ok=True)
    kinds = _cmd_kinds(ws)
    run_e2e = e2e_enabled()
    results: list[dict[str, Any]] = []
    skipped: list[str] = []
    for index, cmd in enumerate(accept_cmds(ws)):
        cmd_id = " ".join(cmd)
        # 序号按**候选列表**走，不按「实际跑了几条」走：跳过一个 e2e 之后，后面那条
        # 的 log 名字不该跟着往前挪，否则同一份配置两次运行会写出互相错位的文件名。
        if kinds.get(cmd_id) == E2E_KIND and not run_e2e:
            skipped.append(cmd_id)
            continue
        code, output = call(list(cmd), ws)
        # 先写 log 再拼记录：logPath 要在记录落盘之前就定下来，否则一条「有 logPath
        # 指向不存在的文件」的记录会骗到下游（修复节点的提示词）。
        log_name = f"{record_id}-{index}.log"
        (directory / log_name).write_text(output or "", encoding="utf-8", errors="replace")
        results.append(
            {
                "id": cmd_id,
                "ok": code == 0,  # 只认退出码：输出里有没有 error 字样是猜
                "tail": _text_tail(output),
                "logPath": f"{_LOG_DIR_REL}/{log_name}",
            }
        )
    advisory = build_advisory(ws, run, runner=call)
    strict = strict_mode()
    # 口径不变的那一条：非 strict 时 result 只看命令。advisory 里最刺眼的
    # 「AC 没测试引用」恰恰是新写的检查最容易误报的一条（id 写在测试的 fixture 里、
    # 写在需求文档里被搜到了也算覆盖），让它去拦部署就是拿噪声扣人。
    passed = all(r["ok"] for r in results) and (not strict or all(g["ok"] for g in advisory))
    record = {
        "id": record_id,
        "phase": devdag.PHASE,
        "result": "passed" if passed else "failed",
        # 字段必须存在：这一版没有回退，但它不许缺省
        "voided": False,
        "results": results,
        "requirementVersion": _requirement_version(run),
        "commitHash": _git_head(ws),
        "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "advisory": advisory,
        "strict": strict,
        "skippedCmds": skipped,
    }
    _write_record(ws, record)
    return record


def _write_record(ws: Path, record: dict[str, Any]) -> None:
    directory = accept_dir(ws)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{record['id']}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def list_records(ws: Path) -> list[dict[str, Any]]:
    """历史验收记录，按时间倒序（新的在前）。读不动的文件跳过。"""
    directory = accept_dir(ws)
    if not directory.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in directory.glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(raw, dict):
            records.append(raw)
    records.sort(key=lambda r: str(r.get("at") or ""), reverse=True)
    return records
