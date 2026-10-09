# 派工单 ACP-2219：同一提交重复部署不升版

> 先 `git merge feature/ACP-2015-v1`。开工在 ACP-2219 评论「开工」，完工评论并置完成。不停下等确认。
> **测试纪律**：只跑 `test/test_ai_studio_prodserver.py` 这一个文件。

现象：「设备管理」同一份代码（commit d9d530d9）连续部署 5 次，版本从 v3 升到 v7，打了 5 个 tag、记了 5 条发布记录。

规则：
1. 部署成功后定版本号前，先看 `publish.list_release_records(项目id)` 最新一条：它的 `commitHash` == 本次 HEAD → **沿用它的版本号**，不打新 tag、不新增发布记录（日志写「代码没变，沿用版本 v<N>」），正式实例照常重启（用户点重新部署就是想重启）。
2. HEAD 变了才 v<N+1> + tag + 记录（现在的行为）。
3. 看板/顶栏显示的版本号照状态文件，不变。

测试：同一 HEAD 部署两次 → 第二次版本相同、tag 命令和 record_release 都只调一次；HEAD 变了 → 版本 +1。
提交 `fix(ai-studio): redeploying the same commit keeps its version (ACP-2219)`，推 fork。只回复「2219 全部完成」。
