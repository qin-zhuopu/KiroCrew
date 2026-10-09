# 派工单 ACP-2226：验收门禁补强（**不许影响现有功能**）

> 开工在 ACP-2226 评论「开工」，完工评论结论并置完成。一步接一步做完，不停下等确认。
> 工作目录 `/home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-kc-gate`，分支 `feature/ACP-2226-gate`（从 feature/ACP-2015-v1 拉的）。不许 pip/npm install；推 fork 本分支，不合 v1（master 合）。
> **测试纪律**：只跑你新增/改的那一个测试文件（每次一个）。**不跑 e2e、不开浏览器、不起服务、不跑全量**。
> **不影响现有功能的硬规则**：
> 1. 所有新门禁默认**只报告不拦截**（结果里多出几条 `advisory`），只有设了 `AI_STUDIO_ACCEPT_STRICT=1` 才变成拦截。现有的 `pnpm typecheck` + `pnpm test:unit` 两条照旧，判定口径不变。
> 2. 现有接口的出参只许**加字段**，不许改名/删字段；现有 testid 不动。
> 3. 现有测试文件 `test/test_ai_studio_accept.py` 原有用例一条都不许改；新用例写在新文件 `test/test_ai_studio_accept_gates.py`。

## 背景
现在：需求不齐不能开发 ✅、没过验收不能部署 ✅。但验收只跑类型检查和单测（单测是开发助手自己写的）；不对照需求验收条；没有代码规范；修复时改松测试没人查；数据库表不对照需求；工作区的 `.ai-studio/workspace.json` 的 `acceptCmds` 能把验收命令换掉（能绕过）。

## 要做（`backend/accept.py` 为主，新函数各自可单测）

1. **平台底线不可减**：`accept_cmds(ws)` 改为「平台底线 `DEFAULT_CMDS` + 工作区额外命令」，工作区只能**加**不能**换**（`acceptCmds` 里的命令追加在后面；和底线重复的去重）。这是唯一一条改了现有行为的——原来 `acceptCmds` 是整体替换。现有用例若有断言「替换」，**不要改那条用例**，在报告里写清楚「行为从替换变追加」由 master 定（保留替换语义作为 `acceptCmdsReplace: true` 显式开关也可以）。
2. **需求验收条覆盖（AC 覆盖）**：`ac_coverage(ws, pages) -> list[dict]`：对本轮开发的每页，读 `docs/需求图谱/<页>.json` 的 `acceptance` 列表（每条有 id，如 `AC-12`），在工作区 `apps/**/test/**`、`apps/**/*.test.ts*`、`e2e/**` 里搜这个 id 字符串；没被任何测试引用的 AC 列出来。结果 `{"id":"ac-coverage","ok": 全覆盖, "missing":[...]}`。
3. **改松测试检测**：`weakened_tests(ws, base, head) -> list[dict]`：`git diff base..head` 里，测试文件被删、或 `assert`/`expect(` 行数减少的文件列出来。`base` = 本轮开发开始时的提交（dev-run.json 第一个节点的 `startCommit`）。修复节点（kind=fix）之后的验收一定要跑这条。
4. **代码规范**：工作区根 `package.json` 有 `lint` 脚本就跑 `pnpm lint`（只认退出码），没有就跳过并在结果里写「工作区没有 lint 脚本」。
5. **数据库对照需求**：`schema_vs_requirements(ws, pages)`：在 `apps/api/src/**` 里找 `CREATE TABLE`，取出表名和列名；对照需求图谱 `page.fields`（编辑/列表字段）的 `code`（转成下划线小写），列出需求里有、库里找不到对应列的字段。只报告，不拦（字段名映射有误差，先观察）。
6. **端到端验收（只做开关，不在你这里跑）**：`acceptCmds` 支持 `{"cmd": "pnpm test:e2e", "kind": "e2e"}` 这种带类型的写法；`kind=e2e` 的命令只在 `AI_STUDIO_ACCEPT_E2E=1` 时才跑（默认不跑——e2e 吃资源，由 master 控制）。
7. 验收记录里加 `advisory: [...]`（第 2~5 条的结果）和 `strict: bool`；`result` 在非 strict 时**只由原来两条命令决定**，strict 时 advisory 任一不 ok 也判 failed。
8. 前端 `DevDagPanel.tsx`：验收结果下面加一块「质量检查（仅提示）」列出 advisory 每条（testid `ai-studio-accept-advisory-<id>`），strict 时标题改「质量检查（拦截）」。中英 + en-XA 文案。只跑 `DevDagPanel.test.tsx`。

## 测试（新文件 `test/test_ai_studio_accept_gates.py`，tmp 工作区 + 替身 runner/git）
底线不可减；AC 覆盖找出缺的 id；删测试/断言变少被检出；无 lint 脚本跳过；库对照找出缺列；e2e 默认不跑、开关开了才跑；非 strict 时 advisory 失败不影响 result；strict 时影响。

## 收尾
提交 `feat(ai-studio): acceptance quality gates, advisory by default (ACP-2226)`，推 fork。报告：每条门禁的结果样例、哪条改了现有行为。只回复「2226 全部完成」。

---

## 施工记录（做完补的，给 master 看）

### 第 8 步前端

- `studioApi.ts`：`StudioAcceptRecord` 只加 3 个**可选**字段 `advisory?:
  StudioAcceptAdvisory[]` / `strict?: boolean` / `skippedCmds?: string[]`。
  刻意用可选：改造前落盘的验收记录没有这几个键，类型上必须容得下老记录
- `DevDagPanel.tsx`：在原有「最新结果列表」之后加一个区块，整块渲染条件是
  `latest && (latest.advisory?.length ?? 0) > 0` —— **老记录没有 advisory，整块不出现，
  现有看板一行都不变**。区块内每行 testid 是 `ai-studio-accept-advisory-<id>`
  （即 `...-ac-coverage` / `...-weakened-tests` / `...-lint` / `...-schema-requirements`），
  外层还有一个 `data-testid="ai-studio-accept-advisory"`（不是门禁行，只是给整块定位用）
- 标题：默认 `质量检查（仅提示）`，`strict=true` 才换成 `质量检查（拦截）`。
  门禁名走 i18n key（`gate_ac_coverage` 等 4 个），未知 id 兜底显示原始 id；
  `missing` 数量走 `advisory_count` 的 `{{n}}` 插值；`skipped`（工作区没有 lint 脚本）
  用「·」而不是「✓」，免得看起来像"检查通过了"
- 文案 7 个 key：`en.json` / `zh-CN.json` 手写，`en-XA.json` 跑 `npm run i18n:pseudo` 生成
- `DevDagPanel.test.tsx` 只加 1 个 describe / 4 条用例，**原有 33 条一条没改**：
  ① 4 行都在、标题是"仅提示"、能数出 2 项 ② strict 时标题变"拦截"
  ③ **advisory 全红，顶部状态仍是 Passed**（这张卡的核心契约）④ 老记录没 advisory → 区块不出现
- 实测：`cd website && npx vitest run src/apps/ai-studio/DevDagPanel.test.tsx` → 37 passed（原 33 + 新 4）

### 门禁样例（编排层 `build_advisory` 的形状）

```
{"id":"ac-coverage","ok":false,"missing":[{"page":"备件台账","id":"AC-99"}]}
{"id":"weakened-tests","ok":false,"base":"<startCommit>","head":"<HEAD>",
 "missing":[{"file":"apps/web/test/a.spec.ts","reason":"deleted","before":null,"after":0},
            {"file":"apps/web/test/b.spec.ts","reason":"fewer-assertions","before":3,"after":1}]}
{"id":"lint","ok":true,"skipped":true,"detail":"工作区没有 lint 脚本"}
{"id":"lint","ok":false,"detail":"exit=1\n...输出尾部..."}
{"id":"schema-requirements","ok":true,"advisoryOnly":true,
 "missing":[{"page":"备件台账","code":"supplier_name","column":"supplier"}]}
```

记录层新增：`"advisory": [上面这些]`、`"strict": false`、`"skippedCmds": ["playwright test"]`。
`AI_STUDIO_ACCEPT_STRICT=1` 时 `strict: true`，advisory 任一条 `ok=false` 才把 `result`
打成 `failed`；只认字符串 `"1"`，`"true"/"2"/"0"` 都不算开（写死在用例里）。
每条门禁都包在 `_safe(...)` 里：自己炸了变成 `ok=false + detail="门禁执行失败: ..."`，
不会把整次验收带崩。

### 哪条改了现有行为（要 master 拍板）

1. **`accept_cmds` 由「工作区覆盖默认」改成「平台底线 + 工作区额外」**（第 1 条）。
   影响面：`workspace.json` 里写了 `acceptCmds` 的工作区，验收时会**多跑**它没写的那两条
   底线命令（`pnpm typecheck` / `pnpm test:unit`）。顺序是底线在前、额外在后，按整条 argv
   文本去重。没配 `acceptCmds` 的工作区行为完全不变。
   逃生口：`workspace.json` 写 `"acceptCmdsReplace": true` 才是老的"整表替换"语义 ——
   "底线只能加不能换"只对默认路径成立，replace 是给"我确实不要平台底线"的显式越权。
2. **命令日志文件名按下标改稳定**：带 e2e 跳过时，被跳过的候选也会写自己的
   `<id>-<下标>.log`（一行"未执行"说明），跑的那条按**候选下标**编号而不是"第几个真跑的"。
   原因：按下标挤号会让一次 run 里多条命令写进同一个文件名，后写的盖掉前面的。
   `test/test_ai_studio_accept.py` **一行没动**（硬规则 3）。实测这条原文件
   `1 failed, 26 passed`：唯一红的是 `test_accept_cmds_reads_workspace_json`，
   它断言的就是老的"整体替换"语义，正好是第 1 条要改的那条 —— 按派工单要求
   **没有改它**，等 master 拍板。其余 26 条（含 e2e/日志/子进程环境那些）全绿，
   说明第 2 点这个改动没有碰坏别的

### 没做的 / 风险（如实）

- 5 条门禁只验证到「直接调函数 + 造真 git 仓库 + 造真图谱目录 + 造真 apps/」这一层。
  派工单禁止起服务、跑全量、跑 e2e，所以**没有端到端跑过一条真 devdag run**。
  `apps/api/src/**` 的建表语句解析（`CREATE TABLE` 正则 + 括号配对 + 顶层逗号切分 +
  约束词表）没有真实工作区样本验证过，只覆盖单测里造的样本（含 `DECIMAL(10,2)`、
  `CONSTRAINT ... FOREIGN KEY`、`KEY idx (a,b)`）。现场最容易错的是列名与
  `fields[].code` 对不上：匹配规则是 code 驼峰转下划线小写，并额外容许去掉下划线再比一次，
  仍对不上就只报告（这条永不拦截，`advisoryOnly: true`）
- 前端 `tsc -p tsconfig.json` 在本分支上**本来就红 2 处**（`App.tsx` TS6133、
  `settingsApi.ts` TS2322，来自 `39034a4377` / `0d87d040d8`，不是我引入的）；
  `npm run i18n:check` 另有 `[manifest-sync]` 7 处不一致（`apps.aiStudio.manifest`
  命名空间在 `origin/main` 和我的工作树里都不存在，属 main 侧与验收目录的既有欠账）。
  两者都写进填坑笔记了，我没有去修别人的东西
- `internal-content-scan` 只在 CI 跑（扫描器本体按设计不进本仓），本地没有等价物。
  人工核过：本次新增内容不含内部域名/主机/工单号/凭据路径；「Jira」「需求图谱」这两个词
  在已发布的 `src/kiro_crew/apps/builtins/ai_studio/backend/*.py` 里本来就有
