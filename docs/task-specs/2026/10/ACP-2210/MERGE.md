# ACP-2210 合并单（今晚要用，最急）

你的 ACP-2210 和刚合进 `feature/ACP-2015-v1` 的 ACP-2207（开发任务并行，重写了 `devdag._loop`）冲突。

1. 丢弃未提交的两个文件：`git checkout -- website/src/i18n/locales/zh-CN.json docs/pitfall-notes/README.md`。
2. `git merge feature/ACP-2015-v1`。
3. 冲突处理：
   - `devdag.py`：以 ACP-2207 的**并行循环**为准，把你的「修复节点」并进去：修复节点 `kind=fix`、`dependsOn=[]`，照常被并行调度挑中；「修完自动再验收」放在**整轮结束、所有节点 done** 的地方触发（只在这一轮里有 fix 节点时）；3 次上限照旧。
   - `test/test_ai_studio_devdag.py`：两边新增的用例都保留（import 两边都要）。
   - `docs/pitfall-notes/README.md`：两边的行都保留。
4. 只跑 `test/test_ai_studio_devdag.py` 和 `test/test_ai_studio_accept.py` 两个文件，全过。
5. 提交、推 fork，只回复「2210 合并完成」。
