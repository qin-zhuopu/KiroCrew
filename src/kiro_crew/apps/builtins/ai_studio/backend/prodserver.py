"""正式服务器启停（ACP-2085-S5，08-publish-app §域名模板 + RFC §9.6 的正式版）。

一个项目一套正式服务器：构建 → 停旧 → 起后端 + 前端 → 挂两个网址（固定正式
网址 + 版本网址）。它和开发服务器（:mod:`devserver`）是同一套骨架换了一身皮：
端口段不同（正式用 7000~7199，和开发的 6800~6999 互不占用）、域名后缀不同
（正式没有 ``-dev``，见 :data:`STABLE_SUFFIX`）、多一条**必须先通过验收**的闸门、
多一步构建、成功之后要打 tag 并记一条发布记录。

因此这里**能 import 的全 import**（``child_env`` / 端口申请 / 杀进程组 / 探活 /
状态文件读写 / 代号-工号规则），一份逻辑只有一份。真要复用必须改 devserver 的，
只把它的私有函数提成公开名，行为一字不改。

事实源是工作区里的 ``.ai-studio/prod-server.json``（部署 id、pid、端口、网址、
版本、提交号、部署时间），日志 ``.ai-studio/prod-server.log``，正式数据库放在
``.ai-studio/prod/app.db``（与工作区的开发库分开）。

所有能碰外部世界的动作都收在可注入的替身后面（runner / prober / ports /
gateway / builder / git），单测绝不起真进程、绝不连真网关、绝不真跑 git
（testing-conventions），和 :class:`devserver.DevServer` 同一个理由。
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from kiro_crew.apps.builtins.ai_studio.backend import accept, devserver, publish

#: 端口段：正式服务器专用，和开发服务器的 6800~6999 分开，一个项目的两套
#: 服务器可以同时活着。
PORT_RANGE = (7000, 7199)

#: 七步的原文顺序。界面上的进度显示的就是这些字，``failedStep`` 也写这些字。
STEPS = ("检查验收", "构建", "停旧实例", "启动后端", "启动前端", "挂网址", "检查网址")

STEP_ACCEPT = STEPS[0]
STEP_BUILD = STEPS[1]
STEP_STOP = STEPS[2]
STEP_API = STEPS[3]
STEP_WEB = STEPS[4]
STEP_CONF = STEPS[5]
STEP_PROBE = STEPS[6]

#: 正式域名后缀。开发服务器的是 ``-dev.gb10.jereh-pe.cn``（后缀本身带 ``-dev``
#: 标签），正式的是裸的 ``.gb10.jereh-pe.cn``：固定网址 ``<代号>-<工号>…``，
#: 版本网址 ``<版本>-<代号>-<工号>…``（08 的模板 ``{版本号}-{应用名}-{工号}``）。
STABLE_SUFFIX = ".gb10.jereh-pe.cn"

#: 版本号只许 ``v<N>``：它直接进 DNS 标签，``v1.0`` 这种带点的会把一个域名拆成
#: 两段，``v;rm`` 这种会进文件路径。版本本身不由人填（= 发布记录条数 + 1），但
#: 它照样要在进域名之前验一次。
_VERSION_RE = re.compile(r"^v[0-9]+$")

STATES = ("stopped", "deploying", "running", "failed")

#: 状态文件、日志、数据库目录，全在工作区 ``.ai-studio/`` 下（不进 Git）。
_STATE_FILE = "prod-server.json"
_LOG_FILE = "prod-server.log"
_STUDIO_DIR = ".ai-studio"
_PROD_DIR = "prod"
_DB_NAME = "app.db"

#: conf 文件名前缀。和开发服务器的 ``ais-`` 分开：一个项目的开发实例与正式实例
#: 可以同时挂在网关上，删一个不许碰另一个。
CONF_PREFIX = "ais-prod"

#: 一条构建命令的天花板。前端打包 + 后端编译在正常仓里是分钟级；900 秒是给
#: 「顺带装依赖」留的余量，同时保证一个卡死的孩子不会永远占着线程。
_BUILD_TIMEOUT_S = 900

#: 网关重启后文件里那句 deploying 就是句谎话：超过这个秒数还没有线程认领，就
#: 当它没在部署，报 stopped 让人重新点（同 devserver 对 starting 的处理）。
_DEPLOY_STALE_S = 1800.0


class ProdServerError(Exception):
    """一次被拒的部署，带 HTTP 层要用的 code 与 status（同 DevServerError）。"""

    def __init__(self, message: str, code: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def prod_domains(project: dict[str, Any], staff: str, version: str) -> tuple[str, str]:
    """``(固定正式网址, 版本网址)``。

    固定 = ``<代号>-<工号>.gb10.jereh-pe.cn``，版本 = ``<版本>-<代号>-<工号>…``
    （08 的域名模板）。代号/工号的规矩**整份借用** :func:`devserver.domain_label`
    —— 不合规同样是 ``bad_code`` / ``no_staff_id`` 两个 400，两套服务器各自验一遍
    迟早会一边松一边紧。借用来的异常换成本模块的类型：路由只认一种 error 对象，
    但 code 与 status 一字不改地传过去。
    """
    try:
        label = devserver.domain_label(project, staff)
    except devserver.DevServerError as exc:
        raise ProdServerError(str(exc), exc.code, exc.status) from exc
    ver = (version or "").strip().lower()
    if not _VERSION_RE.match(ver):
        raise ProdServerError(f"版本号不合规：{version}", "bad_version", 400)
    return f"{label}{STABLE_SUFFIX}", f"{ver}-{label}{STABLE_SUFFIX}"


def gateway_conf_two(domains: tuple[str, str], web_port: int, upstream: str) -> str:
    """一份 nginx ``server{}``，``server_name`` 写两个域名（固定 + 版本）。

    一个 server 块挂两个名字是 nginx 的常规做法：两条网址反代到同一个前端端口，
    reload 一次就够，两份 conf 则会 reload 两次并且互相看不见对方的存活状态。
    """
    names = " ".join(d for d in domains if d)
    return (
        f"# AI Studio 正式服务器 {names}\n"
        "server {\n"
        "  listen 80;\n"
        f"  server_name {names};\n"
        "  location / {\n"
        f"    proxy_pass http://{upstream}:{web_port};\n"
        "    proxy_set_header Host $host;\n"
        "    proxy_set_header X-Real-IP $remote_addr;\n"
        "    proxy_http_version 1.1;\n"
        "    proxy_set_header Upgrade $http_upgrade;\n"
        '    proxy_set_header Connection "upgrade";\n'
        "    proxy_read_timeout 300s;\n"
        "  }\n"
        "}\n"
    )


def prod_conf_stem(label: str) -> str:
    """conf 文件名（不含后缀）：``ais-prod-<代号>-<工号>``。"""
    return devserver.safe_conf_name(CONF_PREFIX, label)


def _custom_prod_cmds(ws: Path) -> dict[str, Any]:
    """读 workspace.json 的 ``prod`` 区块，形状不对就整份退回默认。

    契约是外部的（工作区由模板复制出来，人可能改），一个写坏的文件不该让部署
    崩在解析上 —— 同 ``devserver._custom_dev_cmds`` 的取舍。
    """
    data = devserver.read_json_file(ws / _STUDIO_DIR / "workspace.json")
    prod = data.get("prod")
    return prod if isinstance(prod, dict) else {}


def build_cmds(ws: Path) -> list[list[str]]:
    """构建命令清单。``prod.build`` 是字符串列表就用它（shlex 拆），否则用
    webapp-template 的三条。

    整份退回而不是挑能用的几条：一半构建一半被静默跳过，产出一个「构建成功」的
    残缺产物，比一条明显跑错的命令更危险。
    """
    rows = _custom_prod_cmds(ws).get("build")
    if not isinstance(rows, list) or not rows:
        return [list(cmd) for cmd in DEFAULT_BUILD_CMDS]
    out: list[list[str]] = []
    for item in rows:
        if not isinstance(item, str):
            return [list(cmd) for cmd in DEFAULT_BUILD_CMDS]
        parts = shlex.split(item)
        if not parts:
            return [list(cmd) for cmd in DEFAULT_BUILD_CMDS]
        out.append(parts)
    return out


DEFAULT_BUILD_CMDS: list[list[str]] = [
    ["pnpm", "--filter", "@webapp-template/core", "build"],
    ["pnpm", "build:api"],
    ["pnpm", "--filter", "@webapp-template/web", "build"],
]


def launch_plan(ws: Path, web_port: int, api_port: int, domains: tuple[str, str]) -> list[dict]:
    """两条常驻命令（先后端、后前端），cwd 一律是工作区。

    前端跑的是 ``preview``（构建产物）而不是 ``dev``：正式服务器不许带 HMR。
    数据库单独开一份 ``.ai-studio/prod/app.db``，别把开发库当正式库用。
    ``workspace.json`` 写了 ``prod.web`` / ``prod.api`` 就照它的 cmd，端口仍按
    开发那套 ``portEnv`` 约定用 ``PORT`` 注进去。
    """
    custom = _custom_prod_cmds(ws)
    stable = domains[0] if domains else ""
    api_env = {
        "PORT": str(api_port),
        "APP_DB_PATH": str(ws / _STUDIO_DIR / _PROD_DIR / _DB_NAME),
        "DWS_BIN_PATH": str(ws / "e2e" / "dws-mock" / "dws"),
    }
    web_env = {
        "PORT": str(web_port),
        "VITE_PROXY_TARGET": f"http://127.0.0.1:{api_port}",
        "__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS": ",".join(d for d in domains if d),
    }
    plan: list[dict] = []
    for name, key, env in ((STEP_API, "api", api_env), (STEP_WEB, "web", web_env)):
        entry = custom.get(key)
        cmd = entry.get("cmd") if isinstance(entry, dict) else None
        parts = shlex.split(cmd) if isinstance(cmd, str) and cmd.strip() else []
        if not parts:
            if key == "api":
                parts = ["pnpm", "start:api"]
            else:
                parts = [
                    "pnpm",
                    "--filter",
                    "@webapp-template/web",
                    "preview",
                    "--",
                    "--port",
                    str(web_port),
                    "--strictPort",
                    "--host",
                ]
        plan.append({"name": name, "cmd": parts, "env": dict(env), "host": stable})
    return plan


class ProdServer:
    """一个项目一套正式服务器。外部世界全走注入（构造参数同 DevServer）：

    * ``runner(cmd, cwd, env, log_path) -> pid``：起常驻子进程
    * ``prober(url) -> int``：拿 HTTP 状态码（真版 urllib，**不走代理**）
    * ``ports`` / ``gateway``：端口申请与挂网址
    * ``builder(cmd, cwd, env, log_path, timeout_s) -> (code, tail)``：跑构建
    * ``git(argv) -> (code, 输出)``：打 tag 与推 tag（单测绝不真跑 git）
    * ``recorder(...)``：记发布记录（真版是 :func:`publish.record_release`）
    """

    def __init__(
        self,
        ws: Path,
        project: dict,
        *,
        runner: Callable[[list[str], Path, dict, Path], int] | None = None,
        prober: Callable[[str], int] | None = None,
        ports: Any | None = None,
        gateway: Any | None = None,
        builder: Callable[[list[str], Path, dict, Path, float], tuple[int, str]] | None = None,
        git: Callable[[list[str]], tuple[int, str]] | None = None,
        recorder: Callable[..., dict] | None = None,
        probe_timeout_s: float = devserver.PROBE_TIMEOUT_S,
        nap: Callable[[float], None] = time.sleep,
    ) -> None:
        self.ws = Path(ws)
        self.project = project
        self._runner = runner
        self._prober = prober
        self.ports = (
            ports if ports is not None else devserver.ResregPorts(str(project.get("id") or ""))
        )
        self.gateway = gateway if gateway is not None else devserver.NginxGateway()
        self._builder = builder
        self._git = git
        self._recorder = recorder
        self._probe_timeout_s = probe_timeout_s
        self._nap = nap
        # 代次：部署跑一半有人 stop 过，这个数就变，线程自己收工走人
        self._generation = 0
        # 「本进程正有一次部署在跑」是哪一代（0 = 没有）：deploying 的唯一凭据
        self._busy_gen = 0

    # -- 路径与状态文件 --------------------------------------------------

    @property
    def state_path(self) -> Path:
        return self.ws / _STUDIO_DIR / _STATE_FILE

    @property
    def log_path(self) -> Path:
        return self.ws / _STUDIO_DIR / _LOG_FILE

    @property
    def db_dir(self) -> Path:
        return self.ws / _STUDIO_DIR / _PROD_DIR

    def _read_state(self) -> dict[str, Any]:
        return devserver.read_json_file(self.state_path)

    def _write_state(self, **fields: Any) -> dict[str, Any]:
        """合并写状态文件，**先写临时文件再 rename**。

        部署线程每进一步就写一次，界面每 2 秒读一次（:meth:`status` 走的是同
        一个文件）。``write_text`` 不是原子的：读到一半会拿到截断的 JSON，
        :func:`read_json_file` 容错成 ``{}``，于是 running 会闪一下成「已停止」
        —— 用户看到的就是「部署好了又显示没部署」。rename 在同目录内是原子的，
        读侧永远看到完整的一份。
        """
        path = self.state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        # 临时文件名带 pid + 线程 id：停止按钮和部署线程可能同时在写，共用一个
        # 名字会互相盖掉对方的临时文件
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        payload = devserver.read_json_file(path)
        payload.update(fields)
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return payload

    # -- 读 --------------------------------------------------------------

    def status(self) -> dict:
        """当前状态。文件只是缓存：``deploying`` 要有真线程才认，``running``
        要 pid 都活着 **且** 固定网址 200 才认。

        和开发服务器同一个理由：网关重启后文件里那句 deploying/running 可能是
        句谎话，界面上一个按钮都清不掉它就是泄漏（进程、端口、conf）。
        """
        state = self._read_state()
        raw = state.get("state") if state.get("state") in STATES else "stopped"
        url = _text(state.get("url"))
        if raw == "failed":
            return self._view("failed", state)
        # A deploy THIS process started and has not finished: that is the answer,
        # ahead of any probe. It must come first, because during 停旧实例~启动前端
        # the file still carries the previous deploy's pid — probing with it would
        # report 「正式运行中」 for a site a build is about to replace, and the
        # panel's 部署中 step would never show.
        if raw == "deploying" and self._launching():
            return self._view("deploying", state)
        alive = devserver.children_alive(state)
        if not alive:
            return self._view("stopped", state)
        if self._probe_ok(url):
            return self._view("running", state)
        if raw == "deploying":
            # a gateway restart left a deploying row nobody owns and the pids are
            # up: still not 「running」 until the URL answers, so say stopped
            return self._view("stopped", state)
        return self._view("stopped", state)

    def _launching(self) -> bool:
        return self._busy_gen != 0

    def _view(self, state: str, stored: dict[str, Any]) -> dict:
        raw_ports = stored.get("ports")
        table = raw_ports if isinstance(raw_ports, dict) else {}
        return {
            "state": state,
            "url": _text(stored.get("url")),
            "versionUrl": _text(stored.get("versionUrl")),
            "version": _text(stored.get("version")),
            "ports": {"web": table.get("web"), "api": table.get("api")},
            "step": _text(stored.get("step")) if state == "deploying" else None,
            "failedStep": _text(stored.get("failedStep")) if state == "failed" else None,
            "message": _text(stored.get("message")) if state == "failed" else None,
            "deployedAt": stored.get("deployedAt"),
            "commit": _text(stored.get("commit")),
        }

    def log_tail(self, lines: int = 80) -> list[str]:
        return devserver.log_tail_lines(self.log_path, lines, default=80)

    # -- 部署 ------------------------------------------------------------

    def deploy(self) -> dict:
        """同步验闸门（验收），过了立刻落一条 ``deploying`` 返回；七步在后台跑。

        「先通过验收」这条闸门**必须同步验**：它是给人看的 409，不能让人先看到
        「部署中」再看到失败。不满足就是 409 ``not_accepted``，一个进程都不起、
        状态文件一个字节都不写。
        """
        current = self.status()
        # Only a deploy already in flight is refused. A RUNNING server is not:
        # 「重新部署」 is a button the panel shows precisely while it is up, and the
        # 停旧实例 step exists to take the old one down inside this flow. Refusing
        # here would make redeploy mean「先点停止」— a two-click dance that drops the
        # domain for the length of a build for no reason.
        if current["state"] == "deploying":
            raise ProdServerError("部署正在进行中", "already_deploying", 409)
        # 域名规则先验（它是项目本身的属性，一次字符串判断），再验验收闸门（它要
        # 扫目录 + 跑 git）。一个没配代号的项目应该拿到 400 代号不合规，而不是
        # 先被验收闸门弹一个 409 —— 那会让人以为「补个代号就能部署」。
        staff = devserver.staff_id()
        version = self._next_version()
        domains = prod_domains(self.project, staff, version)
        label = devserver.domain_label(self.project, staff)
        record = self._acceptance()
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self._generation += 1
        generation = self._generation
        # procs/ports are deliberately NOT cleared here. 停旧实例 (step 3) reads
        # them out of this file to kill the previous instance's process groups and
        # release its ports; wiping them at deploy time means a 重新部署 silently
        # orphaned the old pnpm pair — the domain moves to the new one and the old
        # processes sit on 7000/7001 forever, invisible to stop() too, because the
        # row that named them is gone. Step 3 overwrites both with the new values.
        self._write_state(
            state="deploying",
            step=STEP_ACCEPT,
            url=f"https://{domains[0]}/",
            versionUrl=f"https://{domains[1]}/",
            domain=label,
            version=version,
            failedStep=None,
            message=None,
            commit=None,
            deployedAt=None,
            acceptRecordId=record.get("id"),
            deploymentId=_new_deployment_id(),
        )
        self._busy_gen = generation
        try:
            self._start_deploy(generation, label, domains, record)
        except Exception as exc:
            # 连后台线程都起不来：什么都没起，退回 stopped 让人重试，不许留一条
            # 没人认领的 deploying。
            self._busy_gen = 0
            self._write_state(
                state="stopped", procs=[], ports={}, step=None, failedStep=None, message=None
            )
            raise ProdServerError(f"部署任务起不来：{exc}", "deploy_failed", 503) from exc
        # The caller reads the state file, NOT the deploying row written above.
        # The dev server returns 「启动中」 because its next step is a minutes-long
        # install, so the poll is the only honest answer; here the next steps are
        # already underway and the file may well say running/failed by now.
        # Returning the stale row would make the UI show 「部署中」 for a deploy that
        # finished (and the 2s poll would then look like it disagreed with the
        # button it just pressed).
        return self.status()

    def _start_deploy(
        self, generation: int, label: str, domains: tuple[str, str], record: dict[str, Any]
    ) -> None:
        """后台起一次部署。单测覆盖它改成同步跑，断言就不必等线程。"""
        threading.Thread(
            target=self._deploy,
            args=(generation, label, domains, record),
            name=f"ai-studio-prodserver-{self.project.get('id')}",
            daemon=True,
        ).start()

    def _acceptance(self) -> dict[str, Any]:
        """最新一条验收必须「通过 + 未作废 + 之后没有新提交」。"""
        records = accept.list_records(self.ws)
        latest = records[0] if records else None
        if latest is None:
            raise ProdServerError(NOT_ACCEPTED, "not_accepted", 409)
        if latest.get("result") != "passed" or latest.get("voided"):
            raise ProdServerError(NOT_ACCEPTED, "not_accepted", 409)
        head = self._head()
        if not head or latest.get("commitHash") != head:
            raise ProdServerError(NOT_ACCEPTED, "not_accepted", 409)
        return latest

    def _head(self) -> str:
        code, out = self._run_git(["rev-parse", "HEAD"])
        return out.strip() if code == 0 else ""

    def _next_version(self) -> str:
        """``v<N>``，N = 已发布记录条数 + 1（版本号不由人填）。"""
        project_id = str(self.project.get("id") or "")
        try:
            n = len(publish.list_release_records(project_id)) + 1
        except publish.PublishError:
            # 项目目录还没建好（或 id 认不出）：从 v1 起，部署本身照样能跑
            n = 1
        return f"v{n}"

    def _deploy(
        self,
        generation: int,
        label: str,
        domains: tuple[str, str],
        record: dict[str, Any],
    ) -> None:
        """七步：检查验收 → 构建 → 停旧实例 → 起后端 → 起前端 → 挂网址 → 检查网址。

        任一步失败就回滚**本次**新起的东西（旧实例已停的就保持停，在 message 里
        写明），并落 failed。
        """
        spawned: list[dict[str, Any]] = []
        claimed: list[int] = []
        conf_written = False
        old_stopped = False
        try:
            self._step(generation, STEP_ACCEPT)
            self._build(generation)
            old_stopped = self._stop_old(generation)
            api_port, web_port = devserver.pick_two_ports(
                self.ports,
                PORT_RANGE,
                f"ai-studio-prod-{self.project.get('id') or 'unknown'}",
            )
            claimed = [api_port, web_port]
            self._write_state(ports={"web": web_port, "api": api_port})
            plan = launch_plan(self.ws, web_port, api_port, domains)
            for entry in plan:
                step = str(entry["name"])
                self._step(generation, step)
                try:
                    spawned.append(self._spawn(entry))
                except ProdServerError as exc:
                    raise _StepError(step, str(exc)) from exc
            for one in spawned:
                one["startTime"] = devserver.proc_start_time(int(one["pid"]))
            self._write_state(procs=spawned, pid=int(spawned[0]["pid"]))
            if self._abandoned(generation):
                raise _Abandoned()
            self._step(generation, STEP_CONF)
            conf_written = True
            try:
                # 先立标志再写：reload 失败时 conf 已落盘，回滚必须去删它，
                # 而 remove 对不存在的文件是静默的，所以先立不会误删。
                self.gateway.write(
                    self.conf_path(label),
                    gateway_conf_two(domains, web_port, devserver.gateway_upstream()),
                )
            except Exception as exc:  # 网关是外部命令，任何异常都算这一步失败
                raise _StepError(STEP_CONF, str(exc)) from exc
            self._step(generation, STEP_PROBE)
            url = f"https://{domains[0]}/"
            # 轮数而不是墙上时钟：注入 nap 的测试里循环必须确定性走完
            # （真跑时 60 轮 × 2 秒 = 120 秒，等价）。
            for _ in range(max(1, int(self._probe_timeout_s // devserver.PROBE_INTERVAL_S))):
                if self._abandoned(generation):
                    raise _Abandoned()
                if self._probe_ok(url):
                    if not devserver.children_alive({"procs": spawned}):
                        raise _StepError(STEP_PROBE, "进程已退出")
                    self._succeed(generation, domains, record)
                    return
                self._nap(devserver.PROBE_INTERVAL_S)
            raise _StepError(STEP_PROBE, f"{self._probe_timeout_s:.0f} 秒内网址没通")
        except _Abandoned:
            self._rollback(spawned, claimed, conf_written)
        except _StepError as exc:
            self._rollback(spawned, claimed, conf_written)
            detail = exc.detail
            if old_stopped and exc.step != STEP_STOP:
                detail = f"{detail}（旧实例已停）"
            self._fail(generation, exc.step, detail)
        except Exception as exc:  # 后台线程绝不把异常抛回 threading 的默认处理器
            self._rollback(spawned, claimed, conf_written)
            self._fail(generation, STEP_BUILD, f"{type(exc).__name__}: {exc}")
        finally:
            if self._busy_gen == generation:
                self._busy_gen = 0

    def _step(self, generation: int, step: str) -> None:
        if self._abandoned(generation):
            raise _Abandoned()
        self._write_state(step=step)

    def _build(self, generation: int) -> None:
        self._step(generation, STEP_BUILD)
        env = devserver.child_env({})
        for cmd in build_cmds(self.ws):
            if self._abandoned(generation):
                raise _Abandoned()
            try:
                code, tail = self._run_build(list(cmd), env)
            except Exception as exc:
                raise _StepError(STEP_BUILD, str(exc)) from exc
            if code != 0:
                raise _StepError(
                    STEP_BUILD, f"{' '.join(cmd)} 退出码 {code}：{devserver.tail_text(tail)}"
                )

    def _run_build(self, cmd: list[str], env: dict) -> tuple[int, str]:
        if self._builder is not None:
            return self._builder(cmd, self.ws, env, self.log_path, float(_BUILD_TIMEOUT_S))
        return devserver.run_capped(cmd, self.ws, env, self.log_path, float(_BUILD_TIMEOUT_S))

    def _stop_old(self, generation: int) -> bool:
        """杀掉上一次的进程组、删掉旧 conf、退掉旧端口。回旧进程有没有被杀过。

        端口退了但**不再用回来**：第 4 步重新申请，避免「刚杀掉的孩子还没退干净，
        bind 检查说忙」这种自摆乌龙。首次部署（没有旧进程）返回 False。
        """
        self._step(generation, STEP_STOP)
        state = self._read_state()
        procs = devserver.proc_entries(state)
        ports = devserver.stored_ports(state)
        if procs:
            devserver.kill_group({"procs": procs}, self._nap)
        self._clear_conf(state)
        for port in ports:
            self.ports.release(port)
        return bool(procs)

    def _clear_conf(self, state: dict[str, Any]) -> None:
        label = _text(state.get("domain"))
        if not label:
            return
        try:
            self.gateway.remove(self.conf_path(label))
        except Exception as exc:
            # 网关是外部命令。这里抛 _StepError 会被 _deploy 认成「停旧实例失败」，
            # 于是旧 conf 挂着、新实例也没起 —— 如实报这一步失败是对的。
            raise _StepError(STEP_STOP, str(exc)) from exc

    def _spawn(self, entry: dict) -> dict[str, Any]:
        runner = self._runner if self._runner is not None else self._real_runner
        env = devserver.child_env(entry.get("env") or {})
        try:
            pid = runner(list(entry["cmd"]), self.ws, env, self.log_path)
        except Exception as exc:
            raise ProdServerError(str(exc), "spawn_failed", 500) from exc
        pid_int = devserver.pos_int(pid)
        if pid_int is None:
            raise ProdServerError(f"拿不到 pid：{pid!r}", "spawn_failed", 500)
        return {"name": entry.get("name"), "pid": pid_int}

    @staticmethod
    def _real_runner(cmd: list[str], cwd: Path, env: dict, log_path: Path) -> int:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as log_file:
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        return proc.pid

    def _probe_ok(self, url: str) -> bool:
        if not url:
            return False
        prober = self._prober if self._prober is not None else devserver.probe_status
        try:
            return prober(url) == 200
        except Exception:
            return False

    # -- 成功：打 tag + 记发布 -------------------------------------------

    def _succeed(
        self,
        generation: int,
        domains: tuple[str, str],
        record: dict[str, Any],
    ) -> None:
        """三步里只有「落 running」是硬要求：打 tag / 推 tag / 记台账失败只写日志。

        网址已经通了，实例是真活着的。因为一个推不出去的 tag（fork 没配凭据是
        常态）把一套跑起来的正式服务器报成「部署失败」，会让人去点停止，那才是
        真损失。发布记录同理：它是台账，不是服务本身。
        """
        del generation  # 调用方已确认这一代没被作废；写状态前的再一次检查在 _write_state 之上
        state = self._read_state()
        version = _text(state.get("version"))
        commit = self._head()
        self._write_state(
            state="running",
            step=None,
            failedStep=None,
            message=None,
            url=f"https://{domains[0]}/",
            versionUrl=f"https://{domains[1]}/",
            commit=commit,
            deployedAt=devserver.now_iso(),
        )
        self._log(f"[prod] 部署成功：https://{domains[0]}/ 版本 {version}")
        code, out = self._run_git(
            ["tag", "-a", version, "-m", f"完整版通过验收（验收记录 {record.get('id')}）"]
        )
        if code != 0:
            self._log(f"[prod] 打 tag 失败（不影响部署）：{devserver.tail_text(out)}")
        else:
            code, out = self._run_git(["push", "origin", version])
            if code != 0:
                self._log(f"[prod] 推 tag 失败（不影响部署）：{devserver.tail_text(out)}")
        try:
            self._record_release(version, commit, domains[0], record, state)
        except Exception as exc:
            self._log(f"[prod] 发布记录没记上（不影响部署）：{exc}")

    def _record_release(
        self,
        version: str,
        commit: str,
        domain: str,
        record: dict[str, Any],
        state: dict[str, Any],
    ) -> dict:
        recorder = self._recorder if self._recorder is not None else publish.record_release
        return recorder(
            str(self.project.get("id") or ""),
            version=version,
            commit_hash=commit,
            form="full",
            requirement_version=_text(record.get("requirementVersion")),
            jira_task_ids=[],
            url=f"https://{domain}/",
            deployment_id=_text(state.get("deploymentId")),
        )

    # -- 停与回滚 --------------------------------------------------------

    def stop(self) -> dict:
        """杀掉进程、删 conf、退端口。真没东西可清才 409。

        判据同 devserver.stop()：问的是「有没有活进程 / 记着的端口 / 挂着的
        conf」三件具体的事，不是 ``status() == stopped`` —— 「网址没通」不等于
        「没在运行」，拿它当没在运行，停止就成了 409，界面上一个按钮都清不掉它。
        """
        state = self._read_state()
        label = _text(state.get("domain"))
        conf = self.conf_path(label) if label else None
        ports = devserver.stored_ports(state)
        if not self._anything_to_clean(state, conf, ports):
            raise ProdServerError("正式服务器没在运行", "not_running", 409)
        self._generation += 1
        self._busy_gen = 0
        devserver.kill_group(state, self._nap)
        if conf is not None:
            self.gateway.remove(conf)
        for port in ports:
            self.ports.release(port)
        self._write_state(
            state="stopped",
            pid=None,
            procs=[],
            ports={},
            step=None,
            failedStep=None,
            message=None,
        )
        return self._view("stopped", self._read_state())

    def _anything_to_clean(
        self, state: dict[str, Any], conf: Path | None, ports: list[int]
    ) -> bool:
        if devserver.children_alive(state):
            return True
        if self._launching():
            return True
        if ports:
            return True
        if conf is not None:
            return conf.exists()
        return False

    def _rollback(
        self, spawned: list[dict[str, Any]], claimed: list[int], conf_written: bool
    ) -> None:
        if spawned:
            devserver.kill_group({"procs": spawned}, self._nap)
        if conf_written:
            try:
                label = _text(self._read_state().get("domain"))
                self.gateway.remove(self.conf_path(label))
            except Exception:
                pass  # 回滚里的失败不许盖掉真正的失败原因
        for port in claimed:
            self.ports.release(port)
        # The row must stop naming things this deploy already destroyed: the next
        # 停旧实例 reads it to decide whether an old instance exists, and a stale
        # entry would make it report 「旧实例已停」 for processes that died in the
        # rollback two minutes ago.
        self._write_state(procs=[], ports={})

    def _abandoned(self, generation: int) -> bool:
        return generation != self._generation

    def _fail(self, generation: int, step: str, detail: str) -> None:
        if self._abandoned(generation):
            return
        self._write_state(
            state="failed", step=None, failedStep=step, message=f"{step}失败：{detail}"
        )

    def _run_git(self, argv: list[str]) -> tuple[int, str]:
        """``git -C <ws> …``。注入替身时一个真 git 都不跑。"""
        if self._git is not None:
            return self._git(list(argv))
        try:
            proc = subprocess.run(
                ["git", "-C", str(self.ws), *argv],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return 127, str(exc)
        return int(proc.returncode), (proc.stdout or "") + (proc.stderr or "")

    def _log(self, line: str) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("ab") as log_file:
                log_file.write((line.rstrip("\n") + "\n").encode("utf-8", errors="replace"))
        except OSError:
            pass

    def conf_path(self, label: str) -> Path:
        return devserver.gateway_conf_dir() / f"{prod_conf_stem(label)}.conf"


#: 闸门不通过时给人的那一句话：三件事（没通过 / 作废了 / 之后又有新提交）在
#: 界面上一行就够，差在哪条验收记录里去验收面板看。
NOT_ACCEPTED = "先通过验收（最新一次验收要通过，且之后没有新提交）"


class _StepError(Exception):
    """内部用：某一步失败，带步骤名与错误原文。"""

    def __init__(self, step: str, detail: str) -> None:
        super().__init__(f"{step}失败：{detail}")
        self.step = step
        self.detail = detail


class _Abandoned(Exception):
    """后台部署跑到一半有人 stop 过：回滚并闭嘴，不写 failed。"""


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _new_deployment_id() -> str:
    return f"dep-{int(time.time())}-{uuid.uuid4().hex[:8]}"


_SERVERS: dict[str, ProdServer] = {}
_SERVERS_LOCK = threading.Lock()


def prod_server_for(project: dict[str, Any], ws: Path) -> ProdServer:
    """同一个项目的同一个工作区共用一个 :class:`ProdServer`。

    必须有这道缓存：「部署中」的凭据（``_busy_gen``）活在对象里，每个请求新建
    一个对象的话，前端轮询看到的下一个对象不知道自己有没有在部署，会把正在部署
    的项目报成「已停止」，再点一次还会起第二套进程（同 devserver 的理由）。
    """
    key = f"{project.get('id')}\x00{ws}"
    with _SERVERS_LOCK:
        server = _SERVERS.get(key)
        if server is None:
            server = ProdServer(ws, project)
            _SERVERS[key] = server
        else:
            server.project = project
        return server
