"""开发 / 正式服务器子进程不许继承网关的 stdin（2026-10-10 实战）。

网关在 tmux 里跑，stdin 是那个终端。网关一重启（终端关掉），vite preview / vite dev
这类监听键盘快捷键的进程读 stdin 拿到 EOF 就退出——正式网站 502、开发网站掉线，
而后端（不读 stdin）还活着，状态文件照样写着 running。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kiro_crew.apps.builtins.ai_studio.backend import devserver, prodserver


@pytest.mark.parametrize("cls", [devserver.DevServer, prodserver.ProdServer])
def test_real_runner_detaches_stdin(cls, tmp_path: Path, monkeypatch):
    seen: dict = {}

    class FakeProc:
        pid = 4242

    def fake_popen(cmd, **kw):
        seen.update(kw)
        return FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    pid = cls._real_runner(["true"], tmp_path, {}, tmp_path / "x.log")
    assert pid == 4242
    assert seen.get("stdin") is subprocess.DEVNULL
    assert seen.get("start_new_session") is True
