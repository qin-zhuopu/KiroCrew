# ACP-2060 现场记录

- `TASK.md` —— 派工单（需求与七步判据）
- `probe-devserver.sh` —— 第 6 步：用接口（不是浏览器）启停演示项目的开发服务器。
  `bash probe-devserver.sh [get|start|stop|log]`。
  **必须用 `http://localhost:6790` 而不是 `127.0.0.1`**：cookie 是按 `Set-Cookie` 的域记的，
  换 host 就不送，接口回 403 `Token required`（不是没登录）。一律 `--noproxy '*'`。
- `poll-devserver.py` —— 每 5 秒 `get` 一次，状态变化打一行，落到 `running|failed|stopped`
  打 `FINAL:` 退出。后台跑（`run_in_background`），不要在前台空等：
  `python3 poll-devserver.py 300 > poll.log 2>&1`
- `i18n_gap_check.py` / `i18n_parity_blame.py` —— 度量 i18n 门禁红项归属的一次性脚本，
  **用完已删**（免得在 task-spec 目录里长草）。结论：`catalogParity` / `source-strings` /
  `changed-passthrough` / `manifest-sync` 四项红不是本单造成的，本单只加 12 个键。
  分诊方法见 `docs/pitfall-notes/20261008-164500-local-gate-red-list-is-mostly-not-yours.md`
