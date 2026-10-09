# 派工单：ACP-2206 删除工作区 → ACP-2207 开发任务并行（今晚按顺序做，做完一个接下一个，不停）

> 先 `git merge --ff-only feature/ACP-2015-v1`（本地分支，含当晚全部改动）。每单开工在 Jira 评论「开工」，完工评论结论并置完成。
> 每完成一步说「N 完成：<判据结果>」。不停下等确认。
> **测试纪律（用户定案）**：不跑全量测试、不跑 e2e、不起浏览器、不起开发服务器。只跑你自己新增/改的那**一个**测试文件（`pytest test/<那个文件> -q` 或 `npx vitest run <那个文件>`）。全量测试由 master 合并后统一跑。
> 不许推 origin（推 fork）、不许 --no-verify、不许合进 feature/ACP-2015-v1。

## 一、ACP-2206 删除工作区

- 后端 `backend/projects.py` 加 `delete_project(project_id) -> dict`；路由 `DELETE /projects/{id}`：
  1. 开发服务器 / 正式服务器在跑 → 先调它们的 stop（`devserver.DevServer(...).stop()`、`prodserver.ProdServer(...).stop()`；没在跑的 409 忽略）。
  2. 开发在跑（dev-run.json 的 runState=running）→ 409 `dev_running`「开发进行中，先等它结束」。
  3. 把工作区目录**移到** `<AI_STUDIO_WORKSPACES_ROOT>/.trash/<代号>-<时间戳>/`（不真删，可找回），项目记录目录同样移到 `<projects_root>/.trash/`。远端个人仓**不删**（RFC 定的）。
  4. 返回 `{deleted:true, trash:<路径>}`。
- 前端 `ProjectsListPage.tsx` 卡片加〔删除〕（testid `project-delete-<id>`），确认框原文「删除后工作区移到回收站，远端仓库保留。确定删除「<名称>」吗？」；成功后列表刷新。
- 测试：新建一个测试文件 `test/test_ai_studio_delete.py`（替身 stop，tmp 目录），覆盖：移进回收站、服务先停、开发在跑 409、远端不动；前端在 `ProjectsListPage` 现有测试文件里加一条确认框 + 调用的用例（只跑这一个文件）。

## 二、ACP-2207 开发任务并行（照 07 设计的最小版）

- 现在 `devdag.DevRun._loop` 一次只跑一个节点。改成：同时可跑的节点数 = 环境变量 `AI_STUDIO_DEV_PARALLEL`（默认 2）；只挑 dependsOn 全 done 的。
- 并行的两个节点不能在同一目录里同时写代码：每个并行节点用一个 git worktree：`<工作区>/.ai-studio/wt/<节点序号>`，分支 `dev/<节点id 转成小写短横线>`，从工作区当前 HEAD 拉；节点完成后在**工作区主目录**里 `git merge --no-ff <分支>`，合并冲突 → 该节点 failed，message「合并冲突：<文件>」，保留 worktree 供人看。串行依赖的后一个节点（web 依赖 api）在 api 合并后再从主目录 HEAD 拉。
- 看板节点多显示 worktree 路径（只在进行中时显示，testid `ai-studio-dev-dag-node-worktree-<id>`）。
- 测试：只在 `test/test_ai_studio_devdag.py` 里加用例（替身 git、替身 dispatcher）：两页四节点时第 1 轮同时跑两个 api 节点；web 等自己的 api 合并后才开始；合并冲突 → failed；`AI_STUDIO_DEV_PARALLEL=1` 时退回串行。

## 收尾
每单单独提交（`feat(ai-studio): delete a workspace into the trash (ACP-2206)`、`feat(ai-studio): run independent dev tasks in parallel worktrees (ACP-2207)`），推 fork。全部做完只回复「2206-2207 全部完成」。
