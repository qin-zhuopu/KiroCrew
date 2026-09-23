"""The AI Studio release executor: build, stop-old, start-new (T3).

One project serves AT MOST one instance at any moment (08 §四 4): the
instance's process identity lives in ``publish/instance.json`` and every
successful publish replaces it — the old process is stopped and verified
gone BEFORE a new one starts, so old and new never coexist.

The stage seam is :class:`Deployer`: :func:`publish._execute_job` calls the
three stages through it in order and owns the job state machine and the log
lines around them; this module owns how each stage is actually done. Tests
stub the Deployer (the real one spawns children, which a unit test must not
do — see testing-conventions) and drive the log-order / failure-path
assertions through :mod:`publish`.

The build stage's minimal runnable form: an optional ``buildCommand`` from
``publish/config.json`` runs in the project directory (argv list, no shell),
then the project's ``dist/`` (when present) is frozen into
``publish/artifacts/<version>/``. The start stage's default command serves
that artifact directory over ``python -m http.server``; a real production
startup command is the T6 on-host tuning point — the interface here is the
boundary that stays.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from kiro_crew import platform_compat

#: How long ``stop_old`` waits for the old pid to actually disappear before
#: declaring the stage failed — long enough for a SIGTERM shutdown, short
#: enough that a publish never hangs the HTTP handler for minutes.
_STOP_TIMEOUT_S = 10.0

#: The per-instance state file: the single-instance fact IS this file's
#: presence plus the pinned process identity inside it.
_INSTANCE_FILE = "instance.json"

#: The per-project publish config: build/start commands and the port.
_CONFIG_FILE = "config.json"

#: Where a build freezes the serving artifact, per version.
_ARTIFACTS_DIRNAME = "artifacts"

#: The default start command: serve the frozen artifact directory. ``{port}``
#: and ``{artifact_dir}`` are filled by :meth:`ProcessDeployer.start_new`.
_DEFAULT_START_COMMAND = ["python3", "-m", "http.server", "{port}", "--directory", "{artifact_dir}"]

#: The subprocess environment keys the spawned instance receives so the
#: nginx-proxy discovery (VIRTUAL_HOST/VIRTUAL_PORT) can route the publish
#: URL to it without any per-instance nginx edit.
_URL_ENV_KEYS = ("VIRTUAL_HOST", "VIRTUAL_PORT")


class DeployError(Exception):
    """One executor stage failed; the message is the job's failure reason."""


@dataclass
class InstanceSpec:
    """What one new instance serves: frozen at trigger time."""

    version: str
    form: str
    url: str
    artifact_dir: Path
    port: int | None = None
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class InstanceHandle:
    """The pinned identity of a running instance (recorded, then used to
    stop exactly that process — a recycled pid must never be signalled)."""

    pid: int
    start_time: str | None
    port: int
    url: str
    version: str


class Deployer:
    """The stage seam :func:`publish._execute_job` drives. Subclass or stub
    this; the executor never touches processes or subprocesses directly."""

    def build(self, project_dir: Path, version: str, form: str, log: Callable[[str], None]) -> Path:
        raise NotImplementedError

    def stop_old(self, project_dir: Path, log: Callable[[str], None]) -> dict[str, Any] | None:
        raise NotImplementedError

    def start_new(
        self, project_dir: Path, spec: InstanceSpec, log: Callable[[str], None]
    ) -> InstanceHandle:
        raise NotImplementedError


def _log_tail(text: str, limit: int = 400) -> str:
    """The last ``limit`` chars of a command's output — enough to name the
    failure in the job log, small enough to keep the log readable."""
    text = (text or "").strip()
    return text[-limit:] if len(text) > limit else text


class ProcessDeployer(Deployer):
    """The real executor: subprocess build, pinned-identity stop, detached
    start. All process calls route through ``platform_compat`` (the Windows
    ``os.kill`` trap lives there, not here)."""

    # -- state files -------------------------------------------------------

    @staticmethod
    def _instance_path(project_dir: Path) -> Path:
        return project_dir / "publish" / _INSTANCE_FILE

    @staticmethod
    def _config(project_dir: Path) -> dict[str, Any]:
        path = project_dir / "publish" / _CONFIG_FILE
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _read_instance(self, project_dir: Path) -> dict[str, Any] | None:
        try:
            data = json.loads(self._instance_path(project_dir).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _write_instance(self, project_dir: Path, handle: InstanceHandle) -> None:
        path = self._instance_path(project_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "pid": handle.pid,
                    "startTime": handle.start_time,
                    "port": handle.port,
                    "url": handle.url,
                    "version": handle.version,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    # -- stages --------------------------------------------------------

    def build(self, project_dir: Path, version: str, form: str, log: Callable[[str], None]) -> Path:
        config = self._config(project_dir)
        command = config.get("buildCommand")
        if isinstance(command, list) and command and all(isinstance(a, str) for a in command):
            log(f"执行构建命令：{' '.join(command)}")
            try:
                proc = subprocess.run(
                    command,
                    cwd=str(project_dir),
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=600,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise DeployError(f"构建命令执行失败：{exc}") from exc
            if proc.returncode != 0:
                raise DeployError(
                    f"构建命令退出码 {proc.returncode}：{_log_tail(proc.stderr or proc.stdout)}"
                )
            out = _log_tail(proc.stdout)
            if out:
                log(f"构建命令输出：{out}")

        artifact_dir = project_dir / "publish" / _ARTIFACTS_DIRNAME / version
        dist = project_dir / "dist"
        try:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            if dist.is_dir():
                shutil.copytree(dist, artifact_dir, dirs_exist_ok=True)
        except OSError as exc:
            raise DeployError(f"产物目录写入失败：{exc}") from exc
        return artifact_dir

    def stop_old(self, project_dir: Path, log: Callable[[str], None]) -> dict[str, Any] | None:
        state = self._read_instance(project_dir)
        if state is None:
            log("无正在运行的旧实例")
            return None
        pid = state.get("pid")
        if not isinstance(pid, int) or pid <= 1:
            # A state file without a usable pid cannot name a process: drop
            # it, or every later publish would try to stop it forever.
            self._instance_path(project_dir).unlink(missing_ok=True)
            log("旧实例状态文件无有效 pid，按无旧实例处理")
            return None
        log(f"停止旧实例 {state.get('version', '?')}（pid {pid}）")
        self._stop_pid(
            project_dir,
            pid,
            state.get("startTime") if isinstance(state.get("startTime"), str) else None,
        )
        self._instance_path(project_dir).unlink(missing_ok=True)
        return state

    def _stop_pid(self, project_dir: Path, pid: int, expected_start_time: str | None) -> None:
        try:
            if not platform_compat.pid_exists(pid):
                return  # already gone — the single-instance fact already holds
            if expected_start_time:
                platform_compat.kill_process_tree_pinned(pid, expected_start_time)
            else:
                platform_compat.kill_process_tree(pid)
        except (ProcessLookupError, ValueError):
            return  # died between the probe and the signal — same happy end
        except OSError as exc:
            raise DeployError(f"停止旧实例失败（pid {pid}）：{exc}") from exc
        deadline = time.monotonic() + _STOP_TIMEOUT_S
        while time.monotonic() < deadline:
            if not platform_compat.pid_exists(pid):
                return
            time.sleep(0.1)
        raise DeployError(f"旧实例未在 {_STOP_TIMEOUT_S:.0f}s 内退出（pid {pid}）")

    def start_new(
        self, project_dir: Path, spec: InstanceSpec, log: Callable[[str], None]
    ) -> InstanceHandle:
        config = self._config(project_dir)
        command = config.get("startCommand")
        if not (isinstance(command, list) and command and all(isinstance(a, str) for a in command)):
            command = _DEFAULT_START_COMMAND
        port = spec.port or self._free_port()
        render = {"port": str(port), "artifact_dir": str(spec.artifact_dir)}
        try:
            argv = [part.format(**render) for part in command]
        except (KeyError, IndexError, ValueError) as exc:
            raise DeployError(f"启动命令模板无法渲染：{exc}") from exc

        env = {**spec.env, "PORT": str(port), "VIRTUAL_PORT": str(port), "VIRTUAL_HOST": spec.url}
        log(f"启动新实例 {spec.version}：{' '.join(argv)}（端口 {port}）")
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(project_dir),
                env={**os.environ, **env},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=platform_compat.IS_POSIX,
            )
        except OSError as exc:
            raise DeployError(f"新实例启动失败：{exc}") from exc
        handle = InstanceHandle(
            pid=proc.pid,
            start_time=platform_compat.process_start_time(proc.pid),
            port=port,
            url=spec.url,
            version=spec.version,
        )
        self._write_instance(project_dir, handle)
        log(f"新实例已启动：pid {handle.pid}，端口 {port}")
        return handle

    @staticmethod
    def _free_port() -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])
