# worktree 里用主检出 venv 跑代码，import 到的却是主检出的旧代码

## 现象

在 worktree `KiroCrew-wt-kirocrew-int` 里用主检出的 `../KiroCrew/.venv/bin/python`
起 aiohttp 真路由做验收轮，`GET /api/apps/ai-studio/graph` 返回 404，而同样的注册脚本
二十分钟前还跑通过（fixture 就是这么生成的）。中间只跑过一次 `black` 格式化，第一反应
是 black 把注册语句删了——diff 里明明只有一处等价折行。

## 根因

`.venv` 是把 `src/` **editable 安装**进 site-packages 的（`__editable__` pth 指向
`/home/jereh/repo/.../KiroCrew/src`，写死主检出绝对路径）。之前每次跑测试都带着
`PYTHONPATH=src`，cwd 的 `src/` 排在 sys.path 前面，遮蔽了 editable 路径，用的是
**worktree 自己的代码**；验收脚本那次忘了带，editable 路径胜出，`import kiro_crew`
落回**主检出的 main**——上面根本没有 graph 路由，404 完全「合理」。404 报文是
text/plain，连 JSON 都解不开，更看不出是代码版本错了。

同族前科：`website/node_modules` 同理——worktree 里没有，之前 vitest 直接
`ERR_MODULE_NOT_FOUND`；各 worktree 的惯例是指回主检出的软链，本 worktree 恰好没建。

## 修法

- 跑之前先自证来源：`python -c "import kiro_crew; print(kiro_crew.__file__)"`，
  路径必须落在当前 worktree 里；脚本里干脆 `assert kiro_crew.__file__.startswith(os.getcwd())`
- worktree 里 `ln -s <主检出>/website/node_modules website/node_modules`（仓里其他
  worktree 全这么干的，`ls -ld` 一看便知）
- 每次 `PYTHONPATH=src` 都带上，或干脆用 `pip install -e ./src`（在本 worktree 的
  venv 里）——但共用主检出 venv 时 editable 目标是全局唯一的，改它会影响其他 worktree

## 怎么避免

- **共用别的 worktree 的解释器 = 隐式共享它装的所有包**。跨 worktree 借 venv 时，
  「被测代码从哪来」必须每次打印自证，不能假设「在当前目录跑就是我的代码」
- 404/405 这类「路由不存在」的错，先怀疑代码版本（`print(mod.__file__)`），
  再怀疑代码内容——本次 black 背了锅，实际 diff 一行没删逻辑
