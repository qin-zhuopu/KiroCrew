# 门禁红了先读测试自己的名词表，再决定是谁的债

日期：2026-10-08　会话：kc-ws（ACP-2085 新建工作区＝复制模板）

## 现象

改的是 ai-studio 的工作区创建链路（`backend/projects.py`、`backend/routes.py`、新
`backend/workspace.py` + 前端对话框），单测全绿。跑 `python3 scripts/local-gate.py`
时后端那一段整个红掉：

```
5 failed, 28994 passed, 164 skipped in 248.43s
FAILED test/test_apps_doc_catalogue.py::test_every_shipped_app_has_a_catalogue_row
FAILED test/test_apps_doc_catalogue.py::test_both_pages_state_the_shipped_count
FAILED test/test_builtin_skill_sync_safety.py::...::test_child_dir_mode_change_diverges_fingerprint
FAILED test/test_ci_file_shards.py::...::test_cannot_apply_item_splitting_on_top_of_file_splitting
FAILED test/test_ci_pytest_progress.py::TestCIProgress::test_split_records_only_selected_cases
```

最容易被误读成两条：

- `local-gate` 打印的是「related tests only」，看到红就以为**自己**弄坏了相关测试
- `test_apps_doc_catalogue` 里明晃晃有 `ai_studio` 这个词，而我正在改 ai-studio——
  第一反应是「我把应用文档搞坏了」，于是要去改 `src/kiro_crew/docs/apps.md`

## 根因

三个失败都不在本单的改动面里，而且**测试自己的报错名词表就是证据**：

- `test_every_shipped_app_has_a_catalogue_row`：`apps.md's catalogue does not mention
  shipped app(s): ['ai-studio']`。缺的是**整行目录**，不是某一行的措辞。`ai_studio`
  是 `bcc6240a7 feat(apps): add ai_studio builtin design workbench` 进的仓，而
  `apps.md` 最后一次改动是 `20261b763`（别人的 App Store 修正），从没写过这个应用。
  本单两笔提交连 `apps.md` 都没碰。
- `test_both_pages_state_the_shipped_count`：`apps.md's lead paragraph must say
  'Twenty-five'`——应用数量从 25 变成 26（ai_studio 入库那一笔就该改），同样是
  `bcc6240a7` 遗留。
- 另外三条（技能指纹、CI 分片、CI 进度）连文件名都不在本单 diff 里。

`local-gate` 的「相关」是按**改动面的传递闭包**选的：它把整个 ai-studio 内置应用的
路由层算进来，一路扩到 `spec_builder`、`agent_capabilities` 等无关模块，最后这段
跑了将近三万个用例。所以这一段红**不代表**红的是相关的测试，只说明这一片都被扫过了。

## 修法

分诊三步，别先动代码：

1. `git diff --name-only HEAD~2..HEAD`——本单到底改了哪些文件（两笔提交一起看）
2. 把失败测试的**断言原文**读完，看它报的名字是不是**整类缺失**（少一行目录、少一个
   计数）而不是**局部写错**（措辞、路径、字段）
3. `git log --oneline -3 -- <被报的文件>` + `git log --oneline -3 --diff-filter=A --
   <引入者的入口文件>`——找到是哪一笔提交的账，以及本单是否碰过那个文件

结论写进结束报告，不顺手替别人补 `apps.md`：补了就是把别人的债混进这一笔 diff，
评审时反而看不出两件事。

### 光有「名词表」还不够时：造一个干净对照点

上面的三步只能排除「文件根本不在我 diff 里」这种明显情况。剩下两类光读断言排不掉：
共享状态型（`test_spawn_audit` 扫 `src/kiro_crew` 全树、`test_error_code_contract`
数全仓无 `code` 的错误响应——**我改的文件确实在它们的扫描范围里**，光读断言看不出
是我引入的还是本来就红的）与竞态型（`test_eventlog_hooks` 报「ensure left a lease
held」，而它在我单跑时 43 条全过）。

唯一的硬证据是**同一批用例在我父提交上跑一遍**：

```bash
git -C <主仓> worktree add --detach <对照路径> <我的第一笔提交>^
ln -s <我的树>/.venv <对照路径>/.venv                       # 别重装依赖
ln -s <我的树>/website/node_modules <对照路径>/website/node_modules
```

对照结果（本单实测）：后端 34 条红里 **32 条在父提交上一字不差地同样红**；剩 2 条
在对照批量跑里是过的，在我这棵树单跑该文件 43 条也全过 → 归为 20 worker 满载下的
相互污染，不是本单的债。前端两批 59 条红，把那 10 个文件在**两棵树上单跑**，红集合
一致（只差 3 条超时抖动）→ 存量债 + flake，我的 ai-studio 用例一条没红。

对照点用完就拆：`git -C <主仓> worktree remove <对照路径>`（软链先解，否则它算未跟踪
内容赖着不走的概率高）。

**别把「它本来就红」当成「与我无关」。** 有一类测试是**集合型断言**——它列出全仓所有
违规项，本来就有 10 条红的，我新加的代码让它变成 12 条。`test_spawn_audit` 就是这个
现场：对照树（父提交）列 `deploy/devruns/publish/requirements/devserver` 共 10 处，
我这棵树多出的 2 处正是我的 `workspace.py::run_derive` 与 `run_push`。判据是**把两边
的清单取差集**，不是只比失败条数（条数都是「1 failed」，看不出我加了东西）。这种
「已红但被我加长」要在报告里明说，不能写成一句「存量红」糊过去。

### 附：传长用例清单给 pytest，用 `xargs -a` 不要用命令替换

`pytest -q $(tr '\n' ' ' < fails.txt)` 在这套工具链里会变成
`eval '...'` 再执行，我的命令里带的**单引号**把外层 eval 提前截断，结果 pytest 收到
0 个参数、报 `6 workers [0 items]`、退出码 5。**危险的是它长得像跑完了**——没有
FAILED 行，急着读日志会看成「对照全绿」。改成 `xargs -a fails.txt pytest -q …` 后
`34 tests collected`，才对得上。

同理：`@tree_scan_xxx`、`[param]` 这类带符号的 node id 直接传是安全的，不用洗。

## 怎么避免

- **别信「related」这个词的字面意思**。`local-gate` 的后端段实测会跑到近三万用例，
  红一两片是常态；判断归属只认「失败测试涉及的文件是否出现在本单 diff 里」
- **报错里有自己正在改的模块名 ≠ 自己弄坏的**：先看缺的是整块还是一处，再查引入提交
- 一个应用进了 `builtins/`，**同一笔提交**就要把 `apps.md` 的目录行和首段数量改掉，
  否则这笔债会由下一个碰该应用的人背（`test_apps_doc_catalogue` 是两个测试一起红的，
  一次修完）
- 顺带记一笔：`local-gate` 的完整输出会被自己的 `grep` 刷爆，导致外层看到奇怪的
  退出码。要么后台跑再读文件，要么把 grep 的匹配收紧（`grep -m N`）
