# 四条「看着像结果、其实不是结果」的判据陷阱（ACP-2085 S6）

时间：2026-10-09 06:49 · 会话：kc-dag · 相关：ACP-2085 S6（`npx vitest run src/apps/ai-studio/` 判据）

从仓库根跑 vitest 会满屏 `window is not defined` 这件事已经记在
[20261008-211710-vitest-from-repo-root-runs-without-a-dom.md](20261008-211710-vitest-from-repo-root-runs-without-a-dom.md)，
本轮又踩到三个同族的坑，共同点是：**输出看着像一个结论，其实那个结论根本没发生过。**

## 1. 仓库根跑 vitest 的第二层伤害：过滤条件匹配不到任何文件

同一条 `npx vitest run src/apps/ai-studio/`，在仓库根跑出 `139 failed`，在 `website/` 里全过。
除了已记的「没有 jsdom」，还有一层更阴的：**路径过滤 `src/apps/ai-studio` 相对仓库根匹配不到任何文件**，
所以我这次改的 `DevDagPanel.test.tsx` **根本不在那一次的统计里** —— 139 条红全是别人的，
而我的判据一条都没跑到。只看「Tests 139 failed」会以为是自己把别人的套件搞坏了。

**怎么避免**：判据命令的输出里必须能指出 `Test Files N passed` **且**列出的文件里有你改的那些。
只看数字增减不足以判归属。

## 2. 后台任务的日志是空的 ≠ 命令跑过了

**现象**：`cd website && npx vitest run … > /tmp/x.log 2>&1; grep -E "Test Files|Tests " /tmp/x.log`
后台跑完，`grep` 一个字符都没输出。我差点读成「没有失败行 = 通过」。

**根因**：上一个会话进程退出时，正在跑的后台任务被标 stopped，`/tmp/x.log` 只剩 vitest 启动前的
592 字节（vite 配置警告 + ` RUN v4.1.11 …`），汇总行压根没写出来。
「grep 没命中」和「grep 命中了 0 个失败」在终端上长得一模一样。

**修法**：判据命令把退出码自己写进日志，读结论前先确认那行在：

```bash
cd /abs/…/website && pwd && npx vitest run src/apps/ai-studio > /tmp/x.log 2>&1
echo "VITEST_EXIT=$?" >> /tmp/x.log
```

**怎么避免**：空输出一律当「没跑完」。一条判据结论要能同时指出 `pwd` 那行、
`Tests  N passed` 那行、`*_EXIT=0` 那行，三样缺一样就是没结论。

## 3. `toHaveBeenCalledWith('p1')` 对 `('p1', undefined)` 是失败的

**现象**：明明调了、参数也对，却报

```
expected "vi.fn()" to be called with arguments: [ 'p1' ]
Received: 1st vi.fn() call: [ "p1", + undefined ]
Number of calls: 1
```

**根因**：`toHaveBeenCalledWith` 比较**完整实参列表**，不做「尾部 undefined 忽略」。
`planDev(id, pages?)` 里写 `api.planDev(projectId, pages)`，`pages` 为 undefined 时就是两参数调用。

**修法**：断成实际 arity —— `toHaveBeenCalledWith('p1', undefined)`。
不要为了让断言少写一个 `undefined`，把生产代码改成「有 pages 才传第二个参数」两种调用形状。

## 4. 断「按钮不存在」时，等的是首帧

**现象**：`running` 状态下断 `expect(queryByTestId('ai-studio-dev-plan-btn')).not.toBeInTheDocument()`
必红，找到的正是那个按钮。

**根因**：测试 `await screen.findByTestId('ai-studio-dev-status')` 就往下断 —— 而状态块
**首帧就渲染**，内容是 `idle`。第一次 `getDevDag` 还没落地，此刻渲染的正是「idle ⇒ 提供拆分按钮」那一支。
等错对象 = 拿首帧去断终态。

**修法**：等**要断的那个状态词**（本文件测试里的 `RUN_WORDS[runState]`），不要等容器存在。

**归纳成一句**：凡是「某状态下不该出现 X」的断言，都必须先等到那个状态**真的渲染出来**；
凡是「没有失败输出」的判据，都必须先证明**跑过、跑对目录、退出码在**。

## 顺带（不是我的改动，但会误伤判据）

- `website` 的 `npm run test` 的 `pretest` 是 `jscpd .`，main 上就红（见
  [20261009-030704-website-pretest-jscpd-shadows-vitest.md](20261009-030704-website-pretest-jscpd-shadows-vitest.md)）
- 本机 `npx eslint` 起不来：`Cannot find package '@shadcn/lint'`（`website/eslint.config.js` 引用它，
  `node_modules` 里没装）。工单不许 `npm install`，所以前端 lint 只能交给 CI —— 别把它当自己的红灯去修
