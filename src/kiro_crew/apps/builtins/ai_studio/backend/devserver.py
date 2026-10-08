"""开发服务器启停（RFC rfc-ai-studio-req-flow §9.6）。

一个项目一套 dev 服务器：后端 + 前端两个子进程，前端经共享网关 ``web-gateways``
挂到规则域名 ``<代号>-<工号>-dev.gb10.jereh-pe.cn`` 上。事实源是工作区里的
``.ai-studio/dev-server.json``（pid、端口、网址、状态），日志
``.ai-studio/dev-server.log``；状态查询按「pid 活着 + 网址 200」重算，文件只是缓存。

所有能碰外部世界的动作都收在可注入的替身后面（runner / prober / ports / gateway），
和 :class:`deploy.Deployer` 同一个理由：单测绝不起真进程、绝不连真网关
（testing-conventions）。真的那套只在 :meth:`DevServer._real_*` 里，靠
``platform_compat`` 过 POSIX 调用。
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from kiro_crew import platform_compat

#: 域名后缀，可被 AI_STUDIO_DEV_DOMAIN_SUFFIX 覆盖。
DOMAIN_SUFFIX_DEFAULT = "-dev.gb10.jereh-pe.cn"

#: 端口段：只许在这段里申请（派工单硬约束，避开本机其他服务的端口）。
PORT_RANGE = (6800, 6999)

STATES = ("stopped", "starting", "running", "failed")

#: 启动步骤名，``failedStep`` 用这些原文。
STEP_INSTALL = "装依赖"
STEP_PORT = "申请端口"
STEP_API = "启动后端"
STEP_WEB = "启动前端"
STEP_CONF = "挂网址"
STEP_PROBE = "检查网址"

#: 代号与工号的字符集。代号同时受 DNS 单标签长度限制（≤63），这里更严。
_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")
_STAFF_RE = re.compile(r"^[a-z0-9]+$")

#: 状态文件与日志文件名，都在工作区的 ``.ai-studio/`` 下（不进 Git）。
_STATE_FILE = "dev-server.json"
_LOG_FILE = "dev-server.log"
_STUDIO_DIR = ".ai-studio"

#: 装依赖的天花板：pnpm 装一个 monorepo 冷启动是分钟级，这个只挡死住的孩子。
_INSTALL_TIMEOUT_S = 900

#: 网址检查：每 2 秒一次，120 秒内 200 才算 running。
_PROBE_INTERVAL_S = 2.0
_PROBE_TIMEOUT_S = 120.0

#: SIGTERM 后等多久升 SIGKILL。
_KILL_WAIT_S = 5.0

#: ``resreg`` 一次调用的天花板（它是本机 sqlite，正常是毫秒级）。
_RESREG_TIMEOUT_S = 20

#: 子进程环境里必须剥掉的键前缀：网关自己的模型/密钥/数据目录不许漏给开发服务器。
_ENV_DROP_PREFIXES = ("ANTHROPIC_", "KIROCREW_", "CLAUDE_")

#: 连本地端口也不能走代理——挂了代理这一步等于把 localhost 送到国外。
_ENV_DROP_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")


class DevServerError(Exception):
    """一次被拒的启停，带 HTTP 层要用的 code 与 status（同 requirements.RequirementError）。"""

    def __init__(self, message: str, code: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def dev_domain(project: dict[str, Any], staff_id: str | None) -> str:
    """``<代号>-<工号><后缀>``。

    代号取 ``project['code']``，没有就退化成项目 id；两者都先转小写再验字符集。
    工号来自 ``KIROCREW_STAFF_ID``，只许数字或小写字母。
    """
    raw = project.get("code")
    if not (isinstance(raw, str) and raw.strip()):
        fallback = project.get("id")
        raw = fallback if isinstance(fallback, str) else ""
    code = raw.strip().lower()
    if not _CODE_RE.match(code):
        raise DevServerError(f"代号不合规：{raw}", "bad_code", 400)
    staff = (staff_id or "").strip().lower()
    if not staff:
        raise DevServerError("没有工号：请设置 KIROCREW_STAFF_ID", "no_staff_id", 400)
    if not _STAFF_RE.match(staff):
        raise DevServerError("没有工号：请设置 KIROCREW_STAFF_ID", "no_staff_id", 400)
    return f"{code}-{staff}{domain_suffix()}"


def domain_suffix() -> str:
    raw = os.environ.get("AI_STUDIO_DEV_DOMAIN_SUFFIX", "").strip()
    return raw or DOMAIN_SUFFIX_DEFAULT


def gateway_upstream() -> str:
    raw = os.environ.get("AI_STUDIO_GATEWAY_UPSTREAM", "").strip()
    return raw or "10.244.2.1"


def gateway_conf_dir() -> Path:
    raw = os.environ.get("AI_STUDIO_GATEWAY_CONF_DIR", "").strip()
    base = Path(raw) if raw else Path.home() / "docker" / "web-gateways" / "conf.d"
    return base


def gateway_reload_cmd() -> list[str]:
    raw = os.environ.get("AI_STUDIO_GATEWAY_RELOAD_CMD", "").strip()
    parts = shlex.split(raw) if raw else []
    return parts or ["docker", "exec", "web-gateways", "nginx", "-s", "reload"]


def gateway_conf(domain: str, web_port: int, upstream: str) -> str:
    """一份 nginx ``server{}``：反代到宿主上的前端端口，带 websocket 头。

    网关容器已有一条正则 ``server_name`` 收所有 ``*-dev.gb10.jereh-pe.cn``，但它
    的上游是固定的；这里写的是**字面** server_name，nginx 的精确匹配优先于正则，
    所以新域名会走到这份 conf 上，不需要重建任何容器。
    """
    return (
        f"# AI Studio 开发服务器 {domain}\n"
        "server {\n"
        "  listen 80;\n"
        f"  server_name {domain};\n"
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


def launch_plan(ws: Path, web_port: int, api_port: int, domain: str) -> list[dict]:
    """两条命令（先后端、后前端），cwd 一律是工作区目录。

    工作区 ``.ai-studio/workspace.json`` 里写了 ``dev.web`` / ``dev.api`` 就照它
    （cmd 字符串按 shlex 拆），没有就用 webapp-template 的默认两条。默认两条**不
    走**模板根的 ``dev:web`` / ``dev:api``——那两条在 package.json 里把端口写死了。
    """
    custom = _custom_dev_cmds(ws)
    api_env = {"PORT": str(api_port), "DWS_BIN_PATH": str(ws / "e2e" / "dws-mock" / "dws")}
    web_env = {
        "PORT": str(web_port),
        "VITE_PROXY_TARGET": f"http://127.0.0.1:{api_port}",
        "__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS": domain,
    }
    plan: list[dict] = []
    for name, key, env in ((STEP_API, "api", api_env), (STEP_WEB, "web", web_env)):
        cmd = custom.get(key)
        if cmd is None:
            if key == "api":
                cmd = ["pnpm", "--filter", "@webapp-template/api", "dev"]
            else:
                cmd = ["pnpm", "--filter", "@webapp-template/web", "dev"]
        plan.append({"name": name, "cmd": list(cmd), "env": dict(env)})
    return plan


def _custom_dev_cmds(ws: Path) -> dict[str, list[str]]:
    """读 workspace.json 的 dev.web / dev.api（§9.2 契约），只收能用的那条。

    形状不对（cmd 不是非空字符串）就整条忽略，退回默认命令——契约是外部的，
    一个写坏的文件不该让启动崩在解析上。
    """
    try:
        data = json.loads((ws / _STUDIO_DIR / "workspace.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    dev = data.get("dev") if isinstance(data, dict) else None
    if not isinstance(dev, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key in ("web", "api"):
        entry = dev.get(key)
        raw = entry.get("cmd") if isinstance(entry, dict) else None
        if isinstance(raw, str) and raw.strip():
            parts = shlex.split(raw)
            if parts:
                out[key] = parts
    return out


def child_env(extra: dict) -> dict:
    """网关环境剥密后并上 extra。

    剥的是模型/密钥类（``ANTHROPIC_*`` / ``KIROCREW_*`` / ``CLAUDE_*``）和代理变量：
    开发服务器是本机进程，挂上代理连自己的域名反而不通。
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(_ENV_DROP_PREFIXES) and k not in _ENV_DROP_KEYS
    }
    env.update({str(k): str(v) for k, v in (extra or {}).items()})
    return env


def staff_id() -> str:
    return (os.environ.get("KIROCREW_STAFF_ID") or "").strip()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def _proc_alive(pid: Any) -> bool:
    return isinstance(pid, int) and pid > 1 and platform_compat.pid_exists(pid)


def _proc_start_time(pid: int) -> str | None:
    try:
        return platform_compat.process_start_time(pid)
    except OSError:
        return None


def conf_stem(domain: str) -> str:
    """conf 文件名（不含后缀）：``ais-<代号>-<工号>``。

    域名去掉后缀就是标签；后缀被改过（`AI_STUDIO_DEV_DOMAIN_SUFFIX`）也要能算出
    稳定的名字，所以拿不到标签时退回清洗整个域名。名字最后要进文件路径，这里
    顺手把不是 ``[a-z0-9-]`` 的字符全换成 ``-``。
    """
    suffix = domain_suffix()
    label = domain[: -len(suffix)] if suffix and domain.endswith(suffix) else domain
    safe = re.sub(r"[^a-z0-9-]+", "-", label.lower()).strip("-")
    return f"ais-{safe or 'default'}"


def _proc_entries(state: dict[str, Any]) -> list[dict[str, Any]]:
    """状态里的进程清单 ``[{pid, name, startTime}]``，形状不对的一律丢掉。

    状态文件是磁盘上的旧 JSON，可能被手改过、也可能是上一版代码写的：读它不能
    崩，也不能拿一个认不出的条目去发信号。
    """
    raw = state.get("procs")
    if not isinstance(raw, list):
        return []
    return [one for one in raw if isinstance(one, dict)]


def _identity_matches(pid: int, expected: str | None) -> bool:
    """pid 是否仍是我们起的那个进程。

    没有签名可比时放行（本机开发服务器，签名读不到通常是进程刚没了）；有签名就
    必须相等——对 recycled pid 发信号会杀掉无关的进程。
    """
    if not expected:
        return True
    return _proc_start_time(pid) == expected


def _tail(text: str, limit: int = 600) -> str:
    text = (text or "").strip()
    return text[-limit:] if len(text) > limit else text


def _pos_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


class DevServer:
    """一个项目一套开发服务器。四个外部世界全走注入：

    * ``runner(cmd, cwd, env, log_path) -> pid``：起子进程（真版 Popen + 独立会话）
    * ``prober(url) -> int``：拿 HTTP 状态码（真版 urllib，**不走代理**）
    * ``ports``：端口申请与释放
    * ``gateway``：挂网址与 reload
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
        installer: Callable[[Path, dict, Path], int] | None = None,
        probe_timeout_s: float = _PROBE_TIMEOUT_S,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.ws = Path(ws)
        self.project = project
        self._runner = runner
        self._prober = prober
        self._installer = installer
        self.ports = ports if ports is not None else ResregPorts(str(project.get("id") or ""))
        self.gateway = gateway if gateway is not None else NginxGateway()
        self._probe_timeout_s = probe_timeout_s
        self._sleep = sleep
        # 后台启动线程占用的代次：期间有人 stop() 过，这个数就变，线程自己收工走人
        self._generation = 0
        # 「本进程正有一次启动在跑」是哪一代（0 = 没有）。它是「启动中」的唯一凭据：
        # 状态文件里那句 starting 在网关重启后就是句谎话，不能据此挡住重新点。
        self._busy_gen = 0

    # -- 路径与状态文件 --------------------------------------------------

    @property
    def state_path(self) -> Path:
        return self.ws / _STUDIO_DIR / _STATE_FILE

    @property
    def log_path(self) -> Path:
        return self.ws / _STUDIO_DIR / _LOG_FILE

    def _read_state(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_state(self, **fields: Any) -> dict[str, Any]:
        merged = self._read_state()
        merged.update(fields)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return merged

    # -- 读 --------------------------------------------------------------

    def status(self) -> dict:
        """当前状态：文件只是缓存，``starting`` / ``running`` 都要重算。

        「运行中」= pid 都活着 **且** 网址 200 —— 刷新页面、换浏览器、网关重启后
        看到的都是真实情况（验收 19：手动 kill 前端后不再显示运行中）。
        「启动中」只在两件事之一成立时才成立：本进程真有一个在跑的启动线程，或
        pid 已经写上且活着。状态文件孤零零写着 starting 而本进程没有线程，那是
        上一次启动跟着网关一起没了，报 stopped 才允许人重新点。
        """
        state = self._read_state()
        raw = state.get("state") if state.get("state") in STATES else "stopped"
        stored_url = state.get("url")
        url = stored_url if isinstance(stored_url, str) else ""
        if raw == "failed":
            return self._view("failed", url, state)
        alive = self._children_ok(state)
        if not alive:
            if raw == "starting" and self._launching():
                return self._view("starting", url, state)
            return self._view("stopped", url, state)
        if self._probe_ok(url):
            return self._view("running", url, state)
        if raw == "starting":
            return self._view("starting", url, state)
        return self._view("stopped", url, state)

    def _launching(self) -> bool:
        return self._busy_gen != 0

    def _view(self, state: str, url: str, stored: dict[str, Any]) -> dict:
        raw_ports = stored.get("ports")
        ports: dict[str, Any] = raw_ports if isinstance(raw_ports, dict) else {}
        return {
            "state": state,
            "url": url,
            "ports": {"web": ports.get("web"), "api": ports.get("api")},
            "failedStep": stored.get("failedStep") if state == "failed" else None,
            "message": stored.get("message") if state == "failed" else None,
            "startedAt": stored.get("startedAt"),
        }

    def log_tail(self, lines: int = 50) -> list[str]:
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        all_lines = text.splitlines()
        count = lines if isinstance(lines, int) and 0 < lines <= 500 else 50
        return all_lines[-count:]

    # -- 启 --------------------------------------------------------------

    def start(self) -> dict:
        """立刻落一条 ``starting`` 并返回；真活在后台线程里跑。

        域名规则（代号 / 工号）在返回**之前**验：不合规就是 400，一个进程都不起。
        """
        current = self.status()
        if current["state"] in ("running", "starting"):
            raise DevServerError("开发服务器已在运行", "already_running", 409)
        domain = dev_domain(self.project, staff_id())
        self._generation += 1
        generation = self._generation
        self._write_state(
            state="starting",
            url=f"https://{domain}/",
            domain=domain,
            failedStep=None,
            message=None,
            pid=None,
            procs=[],
            ports={},
            startedAt=_now_iso(),
        )
        self._busy_gen = generation
        try:
            self._start_launch(generation, domain)
        except Exception as exc:
            # 连后台线程都起不来（资源耗尽一类）：什么都没起，退回 stopped 让人重试，
            # 不许留一条没人认领的 starting。
            self._busy_gen = 0
            self._write_state(
                state="stopped", pid=None, procs=[], ports={}, failedStep=None, message=None
            )
            raise DevServerError(f"启动任务起不来：{exc}", "launch_failed", 503) from exc
        return self._view("starting", f"https://{domain}/", self._read_state())

    def _start_launch(self, generation: int, domain: str) -> None:
        """后台起一次启动。单测覆盖它改成同步跑，断言就不必等线程。"""
        threading.Thread(
            target=self._launch,
            args=(generation, domain),
            name=f"ai-studio-devserver-{self.project.get('id')}",
            daemon=True,
        ).start()

    def _abandoned(self, generation: int) -> bool:
        return generation != self._generation

    def _fail(self, generation: int, step: str, detail: str) -> None:
        if self._abandoned(generation):
            return
        self._write_state(state="failed", failedStep=step, message=f"{step}失败：{detail}")

    def _launch(self, generation: int, domain: str) -> None:
        """六步流水：装依赖 → 申请端口 → 起后端 → 起前端 → 挂网址 → 检查网址。

        任一步失败就回滚（杀进程组、删 conf + reload、退端口）并落 failed。
        """
        spawned: list[dict[str, Any]] = []
        claimed: list[int] = []
        conf_written = False
        web_port = 0
        api_port = 0
        try:
            try:
                self._install_deps()
            except DevServerError as exc:
                raise _StepError(STEP_INSTALL, str(exc)) from exc
            try:
                api_port, web_port = self._pick_ports()
                claimed = [api_port, web_port]
                self._write_state(ports={"web": web_port, "api": api_port})
            except DevServerError as exc:
                raise _StepError(STEP_PORT, str(exc)) from exc
            plan = launch_plan(self.ws, web_port, api_port, domain)
            for entry in plan:
                step = str(entry["name"])
                try:
                    spawned.append(self._spawn(entry))
                except DevServerError as exc:
                    raise _StepError(step, str(exc)) from exc
            for one in spawned:
                one["startTime"] = _proc_start_time(int(one["pid"]))
            self._write_state(procs=spawned, pid=int(spawned[0]["pid"]))
            if self._abandoned(generation):
                raise _Abandoned()
            try:
                # 先立标志再写：reload 失败时 conf 已经落盘，回滚必须去删它，
                # 而 remove 对不存在的文件是静默的，所以先立不会误删。
                conf_written = True
                self.gateway.write(
                    self.conf_path(domain), gateway_conf(domain, web_port, gateway_upstream())
                )
            except Exception as exc:  # 网关是外部命令，任何异常都算这一步失败
                raise _StepError(STEP_CONF, str(exc)) from exc
            if self._abandoned(generation):
                raise _Abandoned()
            url = f"https://{domain}/"
            # 轮数而不是墙上时钟：注入 sleep 的测试里循环必须确定性走完，
            # 拿 monotonic 比时界会变成空转（真跑时 60 轮 × 2 秒 = 120 秒，等价）。
            for _ in range(max(1, int(self._probe_timeout_s // _PROBE_INTERVAL_S))):
                if self._abandoned(generation):
                    raise _Abandoned()
                if self._probe_ok(url):
                    if not self._children_ok({"procs": spawned}):
                        raise _StepError(STEP_PROBE, "进程已退出")
                    self._write_state(state="running", failedStep=None, message=None, url=url)
                    return
                self._sleep(_PROBE_INTERVAL_S)
            raise _StepError(STEP_PROBE, f"{self._probe_timeout_s:.0f} 秒内网址没通")
        except _Abandoned:
            self._rollback(spawned, claimed, conf_written, domain)
        except _StepError as exc:
            self._rollback(spawned, claimed, conf_written, domain)
            self._fail(generation, exc.step, exc.detail)
        except Exception as exc:  # 后台线程绝不把异常抛回 threading 的默认处理器
            self._rollback(spawned, claimed, conf_written, domain)
            self._fail(generation, STEP_PORT, f"{type(exc).__name__}: {exc}")
        finally:
            if self._busy_gen == generation:
                self._busy_gen = 0

    def _install_deps(self) -> None:
        """``node_modules`` 不存在才装；装了就是 900 秒天花板。

        跑 ``pnpm`` 这一步也留了接缝（``installer``），单测不许装依赖。
        """
        if (self.ws / "node_modules").is_dir():
            return
        if self._installer is not None:
            code = self._installer(self.ws, child_env({}), self.log_path)
            if code != 0:
                raise DevServerError(f"退出码 {code}，见开发服务器日志", "install_failed", 500)
            return
        try:
            with self.log_path.open("ab") as log_file:
                proc = subprocess.run(
                    ["pnpm", "install"],
                    cwd=str(self.ws),
                    env=child_env({}),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    timeout=_INSTALL_TIMEOUT_S,
                    check=False,
                )
        except subprocess.TimeoutExpired as exc:
            raise DevServerError(
                f"超时（{_INSTALL_TIMEOUT_S} 秒）：{exc.cmd}", "install_failed", 500
            ) from exc
        except OSError as exc:
            raise DevServerError(str(exc), "install_failed", 500) from exc
        if proc.returncode != 0:
            raise DevServerError(
                f"退出码 {proc.returncode}，见开发服务器日志", "install_failed", 500
            )

    def _pick_ports(self) -> tuple[int, int]:
        """在 PORT_RANGE 里找两个可用端口并 claim。

        「可用」= 能 bind 且 ``resreg check`` 空闲，两样都归 ``ports`` 这个接缝
        （真版是 :class:`ResregPorts`）：bind 过了不 claim 就是往登记处写垃圾，
        而 claim 之前不 bind 就是抢一个已被占用的端口。测试注入替身，一个真
        socket 都不碰。
        """
        found: list[int] = []
        for port in range(PORT_RANGE[0], PORT_RANGE[1] + 1):
            if len(found) == 2:
                break
            try:
                if not self.ports.free(port):
                    continue
            except Exception as exc:
                raise DevServerError(str(exc), "port_registry_unavailable", 503) from exc
            found.append(port)
        if len(found) < 2:
            raise DevServerError(
                f"{PORT_RANGE[0]}~{PORT_RANGE[1]} 里没有两个可用端口", "no_free_port", 503
            )
        owner = f"ai-studio-{self.project.get('id') or 'unknown'}"
        for port in found:
            try:
                self.ports.claim(port, owner)
            except Exception as exc:
                raise DevServerError(str(exc), "port_registry_unavailable", 503) from exc
        return found[0], found[1]

    def _spawn(self, entry: dict) -> dict[str, Any]:
        runner = self._runner if self._runner is not None else self._real_runner
        env = child_env(entry.get("env") or {})
        try:
            pid = runner(list(entry["cmd"]), self.ws, env, self.log_path)
        except Exception as exc:
            raise DevServerError(str(exc), "spawn_failed", 500) from exc
        pid_int = _pos_int(pid)
        if pid_int is None:
            raise DevServerError(f"拿不到 pid：{pid!r}", "spawn_failed", 500)
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
        prober = self._prober if self._prober is not None else self._real_prober
        try:
            code = prober(url)
        except Exception:
            return False
        return code == 200

    @staticmethod
    def _real_prober(url: str) -> int:
        """GET 首页拿状态码，**不走代理**（挂了代理连自己的域名就是自寻死路）。"""
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(url, timeout=5) as resp:
                code = getattr(resp, "status", None)
                return int(code) if code is not None else 200
        except urllib.error.HTTPError as exc:
            # 有状态码就如实报（502 = 网关通但上游没起，是「还没通」而不是异常）
            return int(exc.code)
        # 连接被拒 / DNS 还没生效 / 超时：调用方按「还没通」处理，异常往上抛即可

    # -- 停与回滚 --------------------------------------------------------

    def stop(self) -> dict:
        """清理一切能查到的痕迹；真没东西可清才 409。

        判据**不能**是 ``status() == stopped``。``stopped`` 的含义是「网址没通」，
        而一个「进程活着 + 端口占着 + conf 挂着，只是网址不通」的现场（实测：vite
        5.4 拦下陌生 Host 回 403）恰恰是 stopped —— 拿它当「没在运行」，停止就成了
        409，界面上一个按钮都清不掉它，进程、端口、conf 全泄漏（2026-10-08 真跑踩过，
        只能手工杀组 + ``resreg release``）。所以这里问的是三件具体的事：有没有活着的
        进程、有没有记着的端口、有没有挂着的 conf。
        """
        state = self._read_state()
        stored_domain = state.get("domain")
        domain = stored_domain if isinstance(stored_domain, str) else ""
        stored_url = state.get("url")
        url = stored_url if isinstance(stored_url, str) else ""
        conf = self.conf_path(domain) if domain else None
        ports = self._stored_ports(state)
        if not self._anything_to_clean(state, conf, ports):
            raise DevServerError("开发服务器没在运行", "not_running", 409)
        # 先作废后台线程，否则它会在我们回滚之后继续往下跑并写回 running
        self._generation += 1
        self._busy_gen = 0
        self._kill_group(state)
        if conf is not None:
            self.gateway.remove(conf)
        for port in ports:
            self.ports.release(port)
        self._write_state(
            state="stopped",
            pid=None,
            procs=[],
            ports={},
            failedStep=None,
            message=None,
        )
        return self._view("stopped", url, self._read_state())

    def _anything_to_clean(
        self, state: dict[str, Any], conf: Path | None, ports: list[int]
    ) -> bool:
        """停止按钮有没有活可干：活进程 / 记着的端口 / 挂着的 conf，三者有一即有活。

        端口与 conf 单独查是因为它们各自都是要花钱的资源：占着端口下一轮就没得用，
        conf 挂着则把域名一直指到一个不存在的上游。
        """
        if self._children_ok(state):
            return True
        if self._launching():
            return True
        if ports:
            return True
        if conf is not None:
            return conf.exists()
        return False

    def _rollback(
        self,
        spawned: list[dict[str, Any]],
        claimed: list[int],
        conf_written: bool,
        domain: str,
    ) -> None:
        if spawned:
            self._kill_group({"procs": spawned})
        if conf_written:
            self.gateway.remove(self.conf_path(domain))
        for port in claimed:
            self.ports.release(port)

    def _stored_ports(self, state: dict[str, Any]) -> list[int]:
        raw = state.get("ports")
        ports: dict[str, Any] = raw if isinstance(raw, dict) else {}
        out: list[int] = []
        for key in ("api", "web"):
            value = _pos_int(ports.get(key))
            if value is not None and value not in out:
                out.append(value)
        return out

    def _children_ok(self, state: dict[str, Any]) -> bool:
        """两个进程都还在才算活着；状态文件只记了一个 pid 时只验那一个。"""
        procs = _proc_entries(state)
        if procs:
            return all(_proc_alive(one.get("pid")) for one in procs)
        return _proc_alive(state.get("pid"))

    def _kill_group(self, state: dict[str, Any]) -> None:
        """SIGTERM 整组，5 秒后还活着就 SIGKILL。

        子进程都是 ``start_new_session=True`` 的组长，杀组就覆盖它带起来的整棵子树
        （pnpm → node → esbuild）。pid 可能已被回收，所以发信号前先比 ``startTime``
        签名，身份不符就当它早不在了 —— 这是 platform_compat 对 os.kill 的硬教训
        （Windows 上 os.kill(pid, 0) 是杀进程不是探活）。
        """
        entries = _proc_entries(state)
        if not entries and _pos_int(state.get("pid")) is not None:
            entries = [{"pid": state.get("pid"), "startTime": state.get("startTime")}]
        targets: list[tuple[int, str | None]] = []
        seen: set[int] = set()
        for one in entries:
            pid = _pos_int(one.get("pid"))
            if pid is None or pid in seen:
                continue
            seen.add(pid)
            raw = one.get("startTime")
            targets.append((pid, raw if isinstance(raw, str) else None))
        self._signal(targets, platform_compat.SIGTERM)
        for _ in range(int(_KILL_WAIT_S / 0.1)):
            if not any(_proc_alive(pid) for pid, _ in targets):
                return
            self._sleep(0.1)
        self._signal(targets, platform_compat.SIGKILL)

    def _signal(self, targets: list[tuple[int, str | None]], sig: int) -> None:
        for pid, expected in targets:
            if not _proc_alive(pid) or not _identity_matches(pid, expected):
                continue
            try:
                platform_compat.kill_process_tree(pid, sig)
            except (ProcessLookupError, PermissionError, ValueError, OSError):
                continue  # 死了 / 不是我们的 / 拒绝对组广播 —— 都无需再动

    def conf_path(self, domain: str) -> Path:
        return gateway_conf_dir() / f"{conf_stem(domain)}.conf"


class _StepError(Exception):
    """内部用：某一步失败，带步骤名与错误原文。"""

    def __init__(self, step: str, detail: str) -> None:
        super().__init__(f"{step}失败：{detail}")
        self.step = step
        self.detail = detail


class _Abandoned(Exception):
    """后台启动跑到一半有人 stop 过：回滚并闭嘴，不写 failed。"""


def _port_bindable(port: int) -> bool:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


_SERVERS: dict[str, DevServer] = {}
_SERVERS_LOCK = threading.Lock()


def dev_server_for(project: dict[str, Any], ws: Path) -> DevServer:
    """同一个项目的同一个工作区共用一个 :class:`DevServer`。

    必须有这道缓存：「启动中」的凭据（``_busy_gen``）活在对象里，每个请求新建一个
    对象的话，前端轮询看到的下一个对象不知道自己有没有在启动，会把正在启动的
    项目报成「已停止」，再点一次还会起第二套进程。键里带工作区路径，改了
    ``workspaceDir`` 自然换一个新的。
    """
    key = f"{project.get('id')}\x00{ws}"
    with _SERVERS_LOCK:
        server = _SERVERS.get(key)
        if server is None:
            server = DevServer(ws, project)
            _SERVERS[key] = server
        else:
            server.project = project
        return server


class ResregPorts:
    """端口资源登记（本机 ``resreg``）。命令不存在就退化成「只做 bind 检查」。"""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id

    def _argv(self, verb: str, port: int, extra: list[str] | None = None) -> list[str]:
        return [
            "resreg",
            verb,
            "--type",
            "port",
            "--value",
            str(port),
            *(extra or []),
        ]

    def _run(self, argv: list[str]) -> int:
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=_RESREG_TIMEOUT_S,
                check=False,
            )
        except FileNotFoundError:
            return 0  # 没有登记处：不做声明，bind 检查已经够用
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"resreg {argv[1]} 执行失败：{_tail(str(exc))}") from exc
        if proc.returncode != 0:
            detail = _tail(proc.stderr or proc.stdout or "")
            raise RuntimeError(f"resreg {argv[1]} 退出码 {proc.returncode}：{detail}")
        return proc.returncode

    def free(self, port: int) -> bool:
        """能 bind 且登记处说空闲。命令不存在时只做 bind 检查。"""
        if not _port_bindable(port):
            return False
        if shutil.which("resreg") is None:
            return True
        try:
            proc = subprocess.run(
                self._argv("check", port),
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=_RESREG_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"resreg check 执行失败：{_tail(str(exc))}") from exc
        return proc.returncode == 0

    def claim(self, port: int, owner: str) -> None:
        if shutil.which("resreg") is None:
            return
        self._run(
            self._argv("claim", port, ["--owner", owner, "--purpose", "AI Studio 开发服务器"])
        )

    def release(self, port: int) -> None:
        if shutil.which("resreg") is None:
            return
        try:
            self._run(self._argv("release", port))
        except RuntimeError:
            # 端口退不回登记处不是启停的成败：bind 检查仍是真闸门，登记项有 TTL 会自己掉
            pass


class NginxGateway:
    """共享网关 ``web-gateways``：写一份 conf 再 reload，停止时删掉再 reload。"""

    def write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self.reload()

    def remove(self, path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            return
        self.reload()

    def reload(self) -> None:
        argv = gateway_reload_cmd()
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
        except OSError as exc:
            raise RuntimeError(f"网关 reload 无法执行：{exc}") from exc
        if proc.returncode != 0:
            raise RuntimeError(
                f"网关 reload 退出码 {proc.returncode}：{_tail(proc.stderr or proc.stdout)}"
            )
