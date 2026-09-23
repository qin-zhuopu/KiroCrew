# T7 前端验收门禁：存量漂移会伪装成你的锅

时间：2026-09-23 · 任务：ACP-772（DeployLog 接真实 SSE 日志流）· 提交：0da29da27

## 现象

验收要求 `npx vitest run src/apps/ai-studio` 全绿。跑完 59 条挂 2 条
（`AiStudioPage.test.tsx` 找不到 `[data-testid="ai-studio"]`，页面渲染成了
项目列表）；顺带跑 i18n 门禁又见 `catalogParity` 缺 73 键、`deadKeys` 58 vs
基线 27。三处红一起出现，第一眼都像本次改动引入的。

## 根因

1. **2 条测试失败是存量**：提交 8c8192ac0 把工作台路由从
   `/ai-studio/projects/<id>` 迁到 `/projects/<id>/ai-studio`，改了页面和
   其它测试文件，唯独漏改 `AiStudioPage.test.tsx` 里两处 `renderAt` 的旧
   路径。旧路径不再匹配 → 走「未知路由渲染项目列表」分支 → 找不到工作台
   testid。T7 之前它就挂着，只是没人跑过这个目录。
2. **i18n 两处失败也是存量**：main 上 ai-studio 早期提交往 en.json 加了键
   却没同步其余 locale（parity），另有 dev_* 一批键的调用点被删了键没删
   （deadKeys 涨到 58）。与本次新增的 2 个键无关。

## 修法

- 两处 `renderAt` 改成新路由路径（顺手修，回执里如实注明是替迁移补漏）。
- i18n 两处不修：不在 T7 范围，且修 deadKeys 要动 BASELINE 基线，属于别的
  会话的账。

## 怎么判断「是不是我的锅」（怎么避免）

- **不要凭感觉认领，也不要凭感觉甩锅——用基线证明**：
  `git stash push -u -m "<unique-tag>"` 把改动全部藏起 → 重跑失败测试 →
  输出与带着改动跑**逐字一致**（缺的键列表、失败条数都相同）→ 判定存量；
  然后 `git stash apply <SHA>` 恢复、按 tag 重新定位 `stash@{n}` 再 drop。
  本机 stash 是跨 worktree 共享的，**严禁裸 `git stash` / `git stash pop`**。
- 新 worktree 没有 `node_modules`：先 `npm install`，否则 `npx vitest` /
  `npx tsc` 报「not the tsc command you are looking for」，那是没装依赖，
  不是类型错误。
- happy-dom **没有 EventSource**：组件里一 `new EventSource` 就在测试里
  炸 ReferenceError。凡是接 SSE 的组件，测试文件必须
  `vi.stubGlobal('EventSource', Fake)`，参考
  `src/test/ResearchLabPageCoverage.test.tsx` 的 FakeEventSource 写法。
