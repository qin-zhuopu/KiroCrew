# 派工单 ACP-2218：开发和部署后把代码推到个人仓 develop

> 先 `git merge feature/ACP-2015-v1`。开工在 ACP-2218 评论「开工」，完工评论并置完成。不停下等确认。
> **测试纪律**：只跑 `test/test_ai_studio_devdag.py` 和 `test/test_ai_studio_prodserver.py` 这两个文件。

现象：「设备管理」4 个开发任务 + 2 次修复都提交在工作区本地，部署也打了 v1/v2 标签并推了标签，但个人仓 `develop` 分支还停在模板那一版——别人 clone 下来看不到代码。

1. 新增一个共用函数（放 `backend/devserver.py` 或新文件 `backend/gitpush.py`）：`push_branch(ws: Path, log) -> bool`：`git -C ws rev-parse --abbrev-ref HEAD` 拿当前分支，`git -C ws push origin HEAD:<分支>`（不走代理：env 用 `devserver.child_env({})`，加 `GIT_TERMINAL_PROMPT=0`，超时 120 秒）；失败只写日志、返回 False，不抛。
2. 调用点：
   - `devdag`：一轮开发**整轮结束且 runState=done** 时推一次（并行合并都在主目录完成之后）；修复节点完成、自动再验收之前也推一次。日志写进 dev-run.log：「推送 develop：成功 / 失败：<原文>」。
   - `prodserver`：部署成功、推标签之前先推一次分支。
3. 测试（替身 git）：done 时调用一次推送；failed 时不推；推送失败不影响 runState；prodserver 成功路径先推分支再推标签。
4. 提交 `feat(ai-studio): push the workspace branch after development and before deploy tags (ACP-2218)`，推 fork。只回复「2218 全部完成」。
