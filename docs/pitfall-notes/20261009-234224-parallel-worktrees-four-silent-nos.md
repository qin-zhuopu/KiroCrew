# 并行 worktree：四个「什么都不报」的坑（ACP-2207）

时间：2026-10-09 23:42:24（23:55 补充：第一条的真实根因是 locale，见下）
涉及：`src/kiro_crew/apps/builtins/ai_studio/backend/devdag.py`、`test/test_ai_studio_devdag.py`

并行改造（`AI_STUDIO_DEV_PARALLEL`）踩了四个坑，共同点是**都不报错**：要么节点安静地
留在 `queued`，要么一条好好的测试安静地判成「回复说完成了，但没有新提交」，要么断言里
只看到 `?? docs/`，要么整条续跑路径在中文机器上 100% 失败而 CI 全绿。

## 一、判断依据用了 git 的英文原文：中文机器上续跑必挂，而 CI 全绿

**现象**（写代码时想到、收尾时用变异测试复现的，不是先撞上的）：续跑同一轮时分支已经在，
`worktree add -b` 必然失败，代码靠 `if "already exists" in out` 退回「直接检出已有分支」。
本机 `LANG=zh_CN.utf8`，实测 git 回的是：

```
fatal: 一个名为 'dev/x' 的分支已经存在
```

英文子串永远匹配不上 → 退回那条命令根本不执行 → 节点报「建 worktree 失败」。
英文 CI、英文容器里这段话就是 `already exists`，测试全绿。

**根因**：git 按 `LC_MESSAGES` 决定它**说什么语言**，也决定 `status`/`diff` 里非 ASCII
路径**要不要转义**。把报错文案当判据 = 把功能绑在部署机的 locale 上。实测对照：

| 命令 | 默认（zh_CN.utf8） | `LC_ALL=C` |
| --- | --- | --- |
| `worktree add -b`（分支已存在） | `fatal: 一个名为 'dev/x' 的分支已经存在` | `fatal: a branch named 'dev/x' already exists` |
| `merge`（内容冲突） | `冲突（添加/添加）：合并冲突于 f.txt` | `CONFLICT (content): Merge conflict in f.txt` |
| `status --porcelain`（中文路径） | `?? ".\350\256\276\345\244\207..."` | `?? docs/需求图谱/设备点检记录.json`（配 `-c core.quotePath=false`） |

**修法**（三处，全部只认退出码 / 只认结构化子命令）：
- `worktree_add`：第一条 `-b` 没成就直接试第二条，**不看文案**。真失败时把两条原文都带上，
  原文只给人看，不参与判断。
- `worktree_merge` 的冲突名单：`diff --name-only --diff-filter=U`（本来就是，不 parse
  merge 输出），再加 `-c core.quotePath=false` —— 否则「设备台账.txt」出来是
  `"\350\256\276\345\244\207\345\217\260\350\264\246.txt"`，看板那句「合并冲突：<文件>」
  等于没写。
- `_git_run` 的 docstring 把这条写成硬规矩：**git 那句原文只能给人看，不能拿来做判断**。

**验证**（三条变异测试，逐条确认新用例真的会红）：去掉 `_merge_lock` →
`assert False`；换回 `"already exists" in out` → 中文 locale 下抛 `GitOpError`；
去掉 `core.quotePath=false` → `('"\\350\\256...4\\246.txt"',) == ('设备台账.txt',)`。

**怎么避免**：任何 `subprocess` 的**文案**都不许当判据 —— 要么用退出码，要么用
`--porcelain` / `--json` / `--name-only` 这类机器可读子命令。做不到就显式固定 locale
（`env={"LC_ALL": "C"}`），但那是对症的补丁，不如换命令。
本项目里要判断的 git 事实都有机器可读问法：分支/目录 → `worktree list --porcelain`；
冲突文件 → `diff --diff-filter=U`；有没有改动 → 退出码或 `--porcelain` 行数。

## 二、`git status --porcelain` 不展开目录、还把中文转成八进制

**现象**：一条测试断言「需求文档仍然出现在 `git status` 里」（只 Ignore worktree
那一格，不能顺手 Ignore 整个 `.ai-studio/` —— 同目录下面就是要进仓的需求事实源）。
真 git 回的是：

```
AssertionError: assert 'docs/需求图谱' in '?? docs/'
```

**根因**：两件独立的事叠在一起，**只修一件仍然是假**。
1. 默认把整个未跟踪目录**折成一行** `?? docs/`，里面的文件一条不列 → 要 `--untracked-files=all`。
2. 非 ASCII 路径默认转义成八进制 → 要 `-c core.quotePath=false`。

**修法**：`git -c core.quotePath=false status --porcelain -uall`。

**怎么避免**：拿 `git status` 输出匹配路径（测试、脚本、门禁都算）默认就是「目录折叠 +
非 ASCII 转义」两个默认值在跟你作对。要么两个参数都加，要么改用
`git ls-files -o --exclude-standard` 这类明确逐文件的命令。

## 三、注入假 HEAD 的测试，交付判定偷偷去跑了真 git

**现象**：`test_a_merge_conflict_fails_that_node_and_keeps_its_worktree` 报
`assert 'queued' == 'done'`，节点被判失败、后继永远排不进。工作区是 tmp 目录、不是 git 仓。

**根因**：并行节点在**自己的 worktree** 里提交，主目录 HEAD 在合并之前不动，所以「这个节点
到底有没有交付」必须读它自己那个目录的 HEAD，于是加了 `git_at` 接缝。第一版写成「没传
`git_at` 但传了 `git` 时，默认回落到真的 `git_head`」—— 串行那批老测试只注入了 `git`
（一个假提交号），改造后交付判定开始调 `git_at`，它们就**静默落到真实 git** 上，tmp 目录
里永远回空串，于是每条都判「回复说完成了，但没有新提交」。

**修法**：注入 `git` 而未注入 `git_at` 时，`_git_at` 跟着 `git` 走（忽略路径）；真正要按
目录区分 HEAD 的并行用例自己传 `git_at` —— 这同时是「这条断言看得见目录」的证据。

**怎么避免**：给一个已有替身接缝再加一个同方向的接缝时，**默认值必须沿用旧替身**，不许
悄悄回落到真实现。判据：任何一条测试都不该因为「新增了一个可选参数」而改变它跑替身还是
跑真环境。

## 四、并行节点的「同时」在测试里等不出来，`sleep(0)` 循环白转

**现象**：新并行用例报 `assert [] == ['ai-studio-dev-p-1', ...]`（派发列表还是空），
或 `timed out waiting for: ...`。

**根因**：派发一个节点之前有三趟线程池往返（写本地忽略、复用检查、`worktree add`），
是**真实毫秒级**延迟。老的等待写法 `for _ in range(20): await asyncio.sleep(0)` 让出控制权
但**不推进时钟**，二十次让出在微秒级就跑完，节点根本没走到派发。串行时一次派发不经过子
进程，所以老写法一直够用，问题只在并行这一批暴露。

**修法**：`_wait_until(detail, predicate)` —— 真实时间 5ms 一跳、最多 2s，超时 raise 并把
**在等什么**写进异常。等待必须有界（testing-conventions：能永久阻塞的测试是一次报废的
RUN，不是一条失败测试）。

同批修掉的假绿：`test_the_default_parallelism_is_two_...` 报 `assert 1 == 2` —— 本文件有个
autouse 夹具把 `AI_STUDIO_DEV_PARALLEL` 钉成 `1`（为保住改造前三十来条断言的形状），
测「模块默认值」时没摘掉它，测的其实是夹具设的值。

**怎么避免**：测「同时发生」用**事件**按住会话、用有界的真实时间轮询等状态，永远不要用
「让出 N 次 = 应该跑完了」。写默认值断言之前，先 grep 本文件有没有 autouse 夹具设了同一
个环境变量。

## 另外三条（不算坑，但下次一定会找这段）

- `worktree add` 的进度语、`merge` 的冲突提示都在 **stderr**：`_git_run` 合并两路输出，
  只看 stdout 会得到一个空报错。
- 一条分支**同时只能有一个检出**（`already used by worktree at ...`）。所以「续跑复用」的
  现场只能是「目录被清了、分支还在」，不是「同一分支开两个目录」—— 后者是 git 的规矩，
  不该绕。写第一条真 git 用例时我按后者写，直接被 git 教育了。
- 冲突后先 `merge --abort` 再抛（主目录不留半合并状态给下一个节点），但**不删 worktree**：
  现场比磁盘重要。合并动作套了一把 `asyncio.Lock`（git 的 index 只容一个写者），用「git
  被调用那一刻那把闸是不是锁着的」钉住，而不是去测两个线程有没有真的重叠 —— 后者在忙的
  机器上会碰巧通过。

## 附：一条被我自己的探针否掉的「根因」

排第四坑时我认定根因是「`while: await asyncio.sleep(0)` 饿死 selector，线程池的完成事件
（写 self-pipe）永远读不到，所以 `to_thread` 永不返回」，并按这个写了本笔记的第一版。
收尾时写了三十行探针实测：**`to_thread` 照常在 0.20s 返回**，期间空转 151462 次。
那套机制讲不通，真原因是第四坑（不推进时钟 + 三趟真实子进程延迟）。

规矩：**根因没做最小复现就不要写进笔记**，尤其不要写「我看了 `/proc/.../wchan`」这类
并没有真的做过的取证。写笔记不是写故事，一段自洽的因果比一次实测便宜太多了。
