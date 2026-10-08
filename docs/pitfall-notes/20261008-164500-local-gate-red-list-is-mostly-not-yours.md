# `local-gate.py` 报 6 红：先证明哪些不是我改的，再动手

## 现象

ACP-2015 第 2 步收尾跑提交前门禁：

```
python3 scripts/local-gate.py
→ /usr/bin/python3: No module named pytest      # 第一次连门都没进
.venv/bin/python scripts/local-gate.py
→ 6 failed, 30253 passed, 155 skipped in 310.02s
```

六条红的里没有一条来自我改的文件（`ai_studio/backend/requirements.py`、
`routes.py`、`test/test_ai_studio_requirements.py`、`website/src/apps/ai-studio/*`）。
但 30253 绿 6 红摆在面前，很容易上手去"修"别人的失败。

## 根因（三件事叠在一起）

### 1. `local-gate.py` 用的是 `python3`，本机系统 python 没有测试依赖

脚本内部直接调 `python3 -m pytest`。系统 python3 没装 pytest / flake8 / mypy /
black（全在仓的 `.venv` 里），所以第一个 chunk 直接 `No module named pytest` 退出。
**必须 `.venv/bin/python scripts/local-gate.py`**（同理 `check_black_formatting.py`
之类也一律用 venv 的 python 跑）。

### 2. worktree 的 `.venv`、`website/node_modules` 都是**软链到主仓**

`KiroCrew-wt-kc-v1/.venv -> KiroCrew/.venv`。好处是不用重装，坏处是：

- 这份 venv 是**共享**的，别的 worktree 装了什么它都有、缺了什么一起缺
- `pytest_split` 这个插件**没装**（CI 才用），于是
  `test_ci_file_shards.py`、`test_ci_pytest_progress.py` 里凡是自己
  `pytest -p pytest_split.plugin` 起子进程的**必红**：
  `ModuleNotFoundError: No module named 'pytest_split'`
  → **本机永远红，跟任何人任何改动无关**

### 3. 剩下三条红是别的 workstream 的存量债 + 一条并行 flake

| 红的那条 | 真相 |
|---|---|
| `test_apps_doc_catalogue.py` 两条 | `src/kiro_crew/docs/apps.md` 里既没有 `ai-studio` 这一行，首段还写「Twenty-four apps ship」，而实际 25 个 —— ai-studio 这个内置 app **落进主干时就没登记文档目录**，早于本步 |
| `test_builtin_skill_sync_safety.py::test_child_dir_mode_change_diverges_fingerprint` | 子目录 chmod 700 再 755，指纹仍变。本机文件系统行为相关，本机必红 |
| `test_cli_doctor.py::TestDoctorKas::test_crew_sign_in_prints_the_crew_owned_argv` | 单跑绿、干净 worktree 绿，只在 `-n auto` 大并发里红 → 并行污染型 flake |

## 怎么证明「不是我改的」——一次性干净 worktree（可复用打法）

脏树上跑门禁，红的永远说不清归属。30 秒造一个干净对照：

```bash
# 在同一个提交上开一个 detached worktree（不带我的未提交改动）
git worktree add ../KiroCrew-wt-gate-baseline HEAD --detach
cd ../KiroCrew-wt-gate-baseline
PYTHONPATH=$PWD/src <主仓>/.venv/bin/python -m pytest -q -p no:randomly \
  test/test_apps_doc_catalogue.py test/test_builtin_skill_sync_safety.py \
  test/test_ci_file_shards.py test/test_ci_pytest_progress.py test/test_cli_doctor.py
# → 5 failed, 346 passed  —— 同样的 5 条，与我的改动无关
```

要点：

- `HEAD --detach`：对照点必须是**我提交前的那个提交**，不能是 main
- `PYTHONPATH=$PWD/src`：venv 是主仓的 editable 安装，不加这一行
  `import kiro_crew` 会指到**主仓的源码树**（实测如此），那就不是对照了
- `test/conftest.py` 走的是对照 worktree 自己的（输出里 rootdir 可自证）
- 用完 `git worktree remove` 掉，别留（本仓 `.worktrees/` 之外的 worktree
  也会进全仓扫描，见 AGENTS.md 的测试约定）

## 前端那 9 个红同理：`src/test/` 是全局目录，改动会扫到它

`local-gate.py` 的前端半边按 diff 扩范围，会连带跑 `website/src/test/`。我这次
`npx vitest run src/apps/ai-studio/` 是 223 全绿，而半边跑出来是
**56 failed | 14676 passed**，红的 9 个文件一个都不在 `src/apps/ai-studio/` 下。
同样造一个前端对照（worktree 里 `website/node_modules` 是指向主仓的软链，直接复用，
**不要 npm install**）：

```bash
git worktree add ../wt-ctl-kc2 HEAD~1 --detach
ln -s <主仓>/website/node_modules ../wt-ctl-kc2/website/node_modules
cd ../wt-ctl-kc2/website && npx vitest run <那 9 个文件>
# 控制组 8 failed | 41 failed tests —— 与我这边同命令同输出，逐条同名
```

`approvalOneShotDecisionRule.test.ts` 是第 9 个，单独跑（第一次写成 `.tsx` 没匹配到，
所以两边都只跑了 8 个文件，别把这个当成差异）：控制组同样红，
`Cannot find package '@shadcn/lint'` —— 它在 `website/package.json` 的 devDependencies
里声明了但本机 `node_modules` 没装（约定禁装）。41 + 15 = 56，正好等于半边跑的全部红数。

三类根因，都跟改动无关：

| 红的文件 | 根因 |
|---|---|
| `DiffBlock.streaming` / `MarkdownRendererCoverage` / `normalizePatchHunks` / `PierreImpl.workerPool` / `ArtifactDetailPage` | `Denied ID .../KiroCrew/website/node_modules/@pierre/diffs/...` —— vite 的 `server.fs.allow` 只放行本仓 `__dirname`（见 `vite.config.ts` 里那段 allow 白名单），而 worktree 的 `node_modules` **软链**解析到主仓真实路径，落在白名单外 |
| `approvalOneShotDecisionRule` | 缺 `@shadcn/lint`（`website/eslint.config.js` 顶层 import，测试装配时会走到） |
| `appManifest` / `safeArea.guard` / `SchedulePage.secrets` | 存量断言债：`APP_MANIFEST_KEY` 里没有 `ai-studio`（和上面 `apps.md` 缺登记是同一笔账的前端半边）；safe-area 守卫有人新贴了贴边 fixed 元素；`closest` 那个是 mock 缺节点 |

## 怎么避免

- **本机跑门禁一律用 `.venv/bin/python`**，不是 `python3`；`No module named pytest`
  不是环境问题，是用错了 python
- **红先分诊再修**：干净 worktree 上同一条也红 = 存量债，写进报告交给 owner，
  不要在别人的红上顺手改（改了就污染本次 diff，评审看不出边界）
- **自己新增的 subprocess 调用一律 `encoding="utf-8"`**：
  `check_subprocess_encoding.py` 会按 `origin/main...HEAD` 的范围报「新增违规」，
  而它同样会报出这条范围里**别人**留下的旧账（这次报的是
  `ai_studio/backend/devruns.py` 里那个没给 encoding 的 `Popen`，9-27 的提交，
  与本步无关）—— 看到 rc=1 先看文件是不是自己碰过的
- **并行 flake 的特征**是「单跑绿、`-n auto` 红」：别去改被测代码，记下用例名
