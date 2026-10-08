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
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from kiro_crew.apps.builtins.ai_studio.backend import devdag

#: 工作区没配 ``acceptCmds`` 时跑这两条（webapp-template 的根 script）。
DEFAULT_CMDS: list[list[str]] = [["pnpm", "typecheck"], ["pnpm", "test:unit"]]

#: 一条验收命令的上限。typecheck + 单测在正常仓里是分钟级；900 秒是给「装依赖
#: 顺带跑一遍」留的余量，同时保证一个卡死的子进程不会永远占着线程。
_CMD_TIMEOUT_S = 900

#: 输出只留最后这么多行：一条失败的 tsc 能喷几千行，整份塞进记录会把看板拖死，
#: 而判定要的证据恰恰在尾巴上。
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


def accept_cmds(ws: Path) -> list[list[str]]:
    """``.ai-studio/workspace.json`` 的 ``acceptCmds``（字符串列表，shlex 拆），
    没有/不合法就用 :data:`DEFAULT_CMDS`。

    形状不对就整份退回默认，而不是挑能用的几条：一半能跑一半被静默丢掉的验收，
    比一份明显跑错的验收更难发现。
    """
    path = ws / ".ai-studio" / "workspace.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [list(cmd) for cmd in DEFAULT_CMDS]
    if not isinstance(raw, dict):
        return [list(cmd) for cmd in DEFAULT_CMDS]
    rows = raw.get("acceptCmds")
    if not isinstance(rows, list) or not rows:
        return [list(cmd) for cmd in DEFAULT_CMDS]
    out: list[list[str]] = []
    for item in rows:
        if not isinstance(item, str):
            return [list(cmd) for cmd in DEFAULT_CMDS]
        parts = shlex.split(item)
        if not parts:
            return [list(cmd) for cmd in DEFAULT_CMDS]
        out.append(parts)
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


def run_accept(ws: Path, run: dict[str, Any], *, runner: Callable | None = None) -> dict:
    """逐条跑验收命令，落一条记录，返回该记录。

    ``runner(cmd, ws) -> (returncode, output)`` 是可注入的替身（单测不起真进程）。
    """
    if run.get("runState") != "done":
        raise AcceptError("dev not done", "dev_not_done", 409)
    call = runner or _run_cmd
    results: list[dict[str, Any]] = []
    for cmd in accept_cmds(ws):
        code, output = call(list(cmd), ws)
        results.append(
            {
                "id": " ".join(cmd),
                "ok": code == 0,  # 只认退出码：输出里有没有 error 字样是猜
                "tail": _text_tail(output),
            }
        )
    record = {
        "id": f"acc-{int(time.time())}-{uuid.uuid4().hex[:8]}",
        "phase": devdag.PHASE,
        "result": "passed" if all(r["ok"] for r in results) else "failed",
        # 字段必须存在：这一版没有回退，但它不许缺省
        "voided": False,
        "results": results,
        "requirementVersion": _requirement_version(run),
        "commitHash": _git_head(ws),
        "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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
