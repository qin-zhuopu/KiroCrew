# 派工单：两个小缺口 ACP-2111、ACP-2112（今晚做完）

> 开工先 `git fetch` 不需要；先 `git merge --ff-only feature/ACP-2015-v1`（本地分支，含最新全部改动）。每单开工在 Jira 评论「开工」，完工评论结论并置完成。
> 每完成一步说「N 完成：<判据结果>」，一步接一步做完，不停下来等确认。只做单测，不起服务、不碰浏览器。
> 不许推 origin（推 fork）、不许 --no-verify、不许合进 feature/ACP-2015-v1（master 合）。

## 1. ACP-2111 网关重启后「创建中」的工作区永远卡住

- 文件：`src/kiro_crew/apps/builtins/ai_studio/backend/workspace.py`、`routes.py`、`test/test_ai_studio_workspace.py`。
- 加 `def recover_interrupted() -> int`：扫 `projects.list_projects()`，`status=="creating"` 且本进程里没有在跑它的任务（workspace.py 里已有的进程内任务表；没有的话加一个 `_RUNNING: set[str]`，run/retry 开始时加、结束时删）→ 把当时 `running` 的那一步改 `failed`、message「网关重启，中断」，`status="failed"`、`failedStep=<那一步>`。返回改了几个。
- 在路由注册（`register_routes`）时调一次（放线程里，异常只写日志）。
- 测试：造一条 creating 记录（第 2 步 running）→ 调用后 status=failed、failedStep=建个人仓、message 对；之后 retry 不再 409；正在跑的（在 `_RUNNING` 里）不动。

## 2. ACP-2112 开发服务器按钮刚打开时闪一下「已停止」

- 文件：`website/src/apps/ai-studio/DevServerControl.tsx` 和 `.test.tsx`，i18n 中英（en-XA 也加）。
- 第一次状态还没拿到时：灰点 + 文字「查询中…」，按钮禁用（testid 不变）。拿到后才显示真实状态。`ProdServerControl` 已经这么做了，照它抄。
- 测试：接口挂起不返回时显示「查询中…」且按钮禁用、不显示「已停止」；返回 stopped 后才出现「已停止」。

## 3. 判据与收尾

- `.venv/bin/python -m pytest test/test_ai_studio_*.py -q` 全过；`cd website && npx vitest run src/apps/ai-studio/` 全过；`npx tsc --noEmit -p .` 无输出。
- 提交 `fix(ai-studio): recover interrupted workspace creation; no false 已停止 flash (ACP-2111, ACP-2112)`，推 fork。最后只回复「2111-2112 全部完成」。
