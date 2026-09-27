# 门禁红条数：唯一诚实的尺子是「同命令在基线上再跑一遍」

时间：2026-09-27 · 任务：ACP-851（T7 KiroCrew 集成，工作台接真链）

## 现象

给 ai-studio 加了 1 个 i18n 键（`apps.aiStudio.regen`，只加 en+zh）后跑
`npx vitest run src/apps/ai-studio src/i18n`，出现 **17 红**。上一轮记录里
i18n 基线欠账是 **11 红**（catalogParity 11 条）。17 > 11，第一反应是「我这轮
引入了 6 条新回归」——其中包括 `contextSidecar` 点名 5 个「无译注短键」
（`Add`/`Run`/`Now`/`Dev`），没有一个是我加的键。

## 根因

**「11 红」是上一轮只跑 `src/i18n` 时按 catalogParity 单文件记的数**，本轮跑法
多了 deadKeys / dynamicKeys / moduleLevel / contextSidecar / zhStyle 五个测试
文件（都在 `src/i18n` 目录下，上一轮根本没跑全目录）。基线本来就是 17 红，
本轮 0 新增。记忆里的「基线数」不是测量值而是当时的抽样值，拿它当尺子必然
误判。

## 修法

不修（都是存量），但**用证据判定而不是凭键名猜**：

1. 找到 HEAD 所在的干净 worktree（`KiroCrew-wt-bgdd-poc` 恰好 detach 在本分支
   HEAD `277b2a2a3`，我的改动全部未提交，它天然是基线）；
2. 同一命令在基线目录再跑一遍：**17 红，失败清单 `diff` 逐字节一致** → 存量
   坐实，写进汇报。

## 怎么避免

- 判断「红是不是我的」：**同命令、同目录、基线再跑一遍，diff 失败清单**。
  不要用上一次的条数记忆，不要用「这些键名不是我加的」这种推理代替测量。
- 基线 worktree 的现成来源：`git worktree list` 看有没有谁恰好停在目标提交；
  没有就 `git worktree add --detach /tmp/x <sha>`（比 stash 安全，本机 stash
  跨 worktree 共享，别的会话会 concurrently 动它）。
- 顺带的两个真发现（与 i18n 无关但同一轮踩到）：
  - 本机 website 的 `npx eslint` **在基线上就崩**（eslint.config.js 引用
    `@shadcn/lint`，node_modules 里没有）——lint 门禁在本机跑不了，如实说明，
    不要把自己吓到以为弄坏了配置。
  - 进程内 aiohttp `TestClient` 验收脚本里，**别拿渲染文档的标题做改写锚点时
    凭记忆猜字面**（`render_acceptance_doc` 写的是 `## 3. 验收场景` 带序号）；
    先 grep 生成器再写断言，否则 AssertionError 的是脚本不是产品。同理别猜
    状态码：regen/distill/freeze 都是 201 不是 200。
