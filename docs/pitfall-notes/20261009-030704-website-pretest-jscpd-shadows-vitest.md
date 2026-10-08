# `npm run test` 红在 jscpd 阈值：vitest 根本没跑，报错内容还与你的改动无关

## 现象

worktree 里改完前端，按 AGENTS.md 跑 `cd website && npm run build && npm run test`：

- `npm run build` 红：`src/apps/ai-studio/DevServerControl.tsx error TS6133:
  'StudioApiError' is declared but its value is never read` —— 这文件我根本没碰
- `npm run test` 红：满屏 `Clone found (json)`，最后一行
  `ERROR: jscpd found too many duplicates (0.78%) over threshold (0%)`，
  报的全是 `demo/fixtures/state-main-*.json`，也与我加的组件无关

两条红都指向「别人的代码」，但谁也不敢直接下这个结论。

## 根因

1. **`npm run test` 的 `pretest` 钩子是 `jscpd .`（全仓查重），阈值 0%。**
   而 main 自己就红：在主检出（干净的 main）单跑 `npx jscpd .` 得
   **1197 个 clone / 0.82% 重复行**（大头是 ai-studio demo fixtures 那批
   状态 json，本来就是复制出来的演示数据）。pretest 非零退出，npm 直接终止，
   **vitest 一条用例都不会跑**——它不是「你的测试挂了」，是「你的测试没跑」。
   `website/docs/testing.md` 只说了 pretest 会先跑 jscpd，没说它在 main 上就是红的。
2. **`npm run build` 的 tsc 是全量的**，存量未使用 import（`DevServerControl` 里
   `StudioApiError`，HEAD 里就躺着）会挡住整条构建，与你的 diff 无关。
3. 顺带一条同族的：**error-code 契约门禁报的是「文件 + bucket + 行号」**，你在同文件
   里加了代码会把**存量违规**的行号推后（`routes.py: dynamic_status 0 -> 1`，main 上
   在 274 行、我改完变 284 行）。只看行号会误判成新引入的。判归属要**在主检出跑同一条
   命令**，比对「文件名 + bucket」而不是行号。

## 修法

- 前端验自己的改动，直接 **`npx vitest run src/apps/ai-studio/Xxx.test.tsx ...`**
  （绕过 pretest），全量口径交给 CI 的 `frontend-lint`/`test:website`
- 判 build/tsc 红的归属：`git status --porcelain <被报文件>` 空 + `git show HEAD:<文件>`
  里问题原样存在 = 存量，写进报告，别顺手修（修了会把别人的问题混进你的 diff）
- 判 jscpd / 契约门禁红的归属：去主检出（干净的 main）跑同一条命令，输出一样就是存量。
  实测本次 5 条红全部如此：契约 `dynamic_status`（publish 的 200/201 三元）、
  `check_subprocess_encoding.py`（`devruns._run_gate` 缺 `encoding=`）、
  tsc 未使用 import、jscpd 阈值、i18n `manifest-sync`（ai-studio manifest 的 7 个键）

## 怎么避免

- 前端改动的**本地判据**从第一天就用 `npx vitest run <你的 spec>`；
  `npm run test` 只在看得到 CI 的时候用
- 任何全仓型门禁（jscpd、契约 ratchet、manifest-sync）报红，**第一动作是去干净基线复现**，
  不是读报错内容——报错内容说的是全仓现状，不是你的 diff
- 报告里把「哪几条红、在哪个提交上复现过」逐条列死，合并的人不用再查一遍
