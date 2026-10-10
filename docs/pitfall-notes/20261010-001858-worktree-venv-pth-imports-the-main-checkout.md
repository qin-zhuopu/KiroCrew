# worktree 的 `.venv` 是符号链接：不经过 pytest 的 import 会验到**主仓**

时间：2026-10-10 00:18（ACP-2210，feature/ACP-2085-prod worktree）

## 现象

在 worktree `KiroCrew-wt-kc-prod` 里新写了 `backend/devdag.py` 的 `DevRun.fix()`，想先跑一行
自检确认可导入：

```bash
$ .venv/bin/python -c "from ...backend import devdag, routes"
ImportError: cannot import name 'devdag' from 'kiro_crew.apps.builtins.ai_studio.backend'
             (/home/jereh/repo/github.com/kirodotdev/KiroCrew/src/.../__init__.py)
$ .venv/bin/python -c "import kiro_crew; print(kiro_crew.__file__)"
/home/jereh/repo/github.com/kirodotdev/KiroCrew/src/kiro_crew/__init__.py   ← 不是本 worktree
```

报错说的是「这个包里**没有** devdag 这个模块」。我据此怀疑自己 import 名写错、
`__init__.py` 少导出、甚至怀疑上一轮改动没落盘 —— 然后 `ls` 了一下就发现本 worktree
里 `devdag.py` 明明在，774 行。

同一时间 `pytest test/test_ai_studio_devdag.py` 是**全绿**的（78 passed，含我刚加的
12 条）。也就是同一份代码，「自检」说没有，「测试」说对。

## 根因

`KiroCrew-wt-kc-prod/.venv` 不是真目录，是**符号链接**：

```
.venv -> /home/jereh/repo/github.com/kirodotdev/KiroCrew/.venv
```

里面躺着一个 editable 安装的路径文件，内容是一行**绝对路径**：

```
.venv/lib/python3.12/site-packages/__editable__*.pth
  → /home/jereh/repo/github.com/kirodotdev/KiroCrew/src      ← 主 worktree
```

所以任何**直接起 python** 的用法（`python -c`、`python -m mypy`、脚本里 require）拿到的
`kiro_crew` 都是**主 worktree 那一份**，跟当前 worktree 的改动无关。

pytest 为什么是对的：`rootdir` 解析到本 worktree，`conftest.py` 把**本仓的 `src/`** 插到
`sys.path` 最前，抢在 `.pth` 前面。所以「测试绿、手敲自检红」这个组合本身就是线索：
**两条路的 `sys.path` 不是同一条**。

顺带：主 worktree 的 `ai_studio/backend/` 只有 7 个文件（`deploy devruns graph projects
publish routes`），没有 `devdag.py`/`accept.py` —— 它比这条分支落后一大截。这也解释了为
什么报的是「没有这个模块」而不是「模块里没有这个名字」。

## 修法

自检一律带上「我在验谁」的自证：

```bash
.venv/bin/python -c "import kiro_crew…devdag as d; print(d.__file__)"
# 或者显式压住 .pth：
PYTHONPATH=<本 worktree>/src .venv/bin/python -c "…"
```

**更稳的判据是反向的**：想知道 pytest 到底测的是哪棵树，就找一个**只有这棵树才有**的东西
让它炸。这次我加的新测试引用了 `devdag.FIX_LIMIT`、`DevRun.fix` —— 主 worktree 里
`devdag.py` 连文件都不存在，若真测主仓必然 `ImportError` 而非 78 passed。这条推理比读
`sys.path` 可靠，因为它证明的是**结论**而不是配置。

## 怎么避免

- worktree 里 `.venv` 出现「软链 + editable `.pth` 指向别处」时，**不要用裸 python 自检
  导入**；要用就先 print `module.__file__`，或直接 `PYTHONPATH=<wt>/src`
- 看到 `cannot import name X`，先跑一次 `python -c "import <包>; print(<包>.__file__)"`
  确认树的归属，再怀疑代码 —— 这一行 5 秒，我按代码错去查用了十几分钟
- 「我的测试全绿，但手动 import 说模块不存在」= 两条 `sys.path` 不一致，不是代码坏

## 附带一条：`err_fix_limit` 的占位符差点原样印到界面上

`err_fix_limit` 我一开始写成 `{{n}}`，但那条文案走的是 `NOTICE_KEY` → `i18nT(key)`
**不带参数**，占位符会原样印在界面上。带插值的文案要确认调用侧传了参。
（同单另一坑「目录 parity 本来就红」另开一篇：
[20261010-002120](20261010-002120-i18n-parity-debt-masquerades-as-your-diff.md)。）

## 反向对照（这次做了，值得记一下做法）

新写的 6 条断言全部做了反向对照，因为「测试通过」在改错文件时也会通过：

| 破坏点 | 结果 |
|---|---|
| 记录里删掉 `logPath` 字段 | 2 条红（`KeyError: 'logPath'`） |
| `_prompt_for` 不再认 `kind=="fix"` | 2 条红（提示词退回通用那句，断言里找不到 log 路径） |
| 前端 `recordsQuery` 去掉 `refetchInterval` | 恰好 1 条红（自动验收回来的新结果上不了屏） |

第三条是这轮唯一「不测就发现不了」的空洞：`runAccept` 手工往 query 缓存里塞了一条记录，
所以**手工**点〔跑验收〕的用例就算没有轮询也是绿的；只有「助手修完自己再验收」这条
本 tab 没点过任何按钮的路径，才会暴露记录从来不轮询。
