# 01 · 项目进入与当前状态（open-project）— 细节验收文档（试点）

对应顶层：`00-e2e-top-level.md` 步骤 **open-project**（入口步骤，后序 edit-requirement）。
本文档是 01~09 的**试点**：既验 open-project，也验「细节文档统一格式」本身——
每条断言给出 ①`data-testid` 定位 ②可判定谓词（元素/文本/状态/快照字段）③可重复执行的证据命令。

## 颗粒度约定（继承 08，本文档补两条）

- **前台断言只认 `data-testid`**，不认组件名、不认文案、不认 CSS；文案断言认「语义正则」（UI 跟随浏览器语言，zh/en 都要过）。
- **快照字段断言认 fixture JSON**：demo 模式的通过条件一律是「DOM 观测 == `website/src/apps/ai-studio/demo/fixtures/state-<步骤id>.json` 的字段」，不认截图。
- **取证只走 DOM/CDP/JSON，禁止截图**（全项目铁律）。
- **证据命令自足**：demo 断言零 API、纯 DOM；普通模式断言需要 dashboard 鉴权时用 `kirocrew token` 现签，不依赖任何人的浏览器登录态。

## 〇、两条访问路线与路由契约（实测钉死，2026-09-23）

open-project 有两种「进入项目工作台」的方式，断言分两组，各自独立可跑：

| 路线 | URL | 数据源 | 用途 |
|---|---|---|---|
| **演示路线（demo）** | `/ai-studio?demo=<场景id>` | 快照 fixture（零 API、零写请求） | 断言「当前状态」的**内容级**一致性——fixture 是唯一权威数据源 |
| **普通路线（ordinary）** | `/ai-studio` → 点选/新建 → `/ai-studio/projects/<id>` | 真实后端 `/api/apps/ai-studio/*` | 断言进入流程、加载态、空项目初始态 |

路由契约（踩过坑，写死）：

- 内置应用路由是 `/:builtinApp/*`：**`/ai-studio` 与 `/ai-studio/…` 都命中**；
  **`/apps/ai-studio` 不命中**（落回聊天页），**根路径 `/?demo=…` 不命中**（`?demo=` 只在 `/ai-studio` 前缀下被解析）。
- 场景 id = `website/src/apps/ai-studio/demo/steps/*.json` 的文件名。主单里写的 `?demo=main`
  **不是合法场景 id**（主场景为 `main-membership-points`，另有 `alt-1-draft-restore`、`alt-2-empty-gray`）；
  未知场景必须落 `demo-unknown-scenario`，不得渲染真实工作台、不得回落到真实数据（本文档 N2 断言）。
- dashboard 鉴权 cookie 名为 `mc_token_<网关端口>` 且 **HttpOnly**（`document.cookie` 看不见，取证要读浏览器上下文的 cookie jar）。
- token 默认约 5 分钟~20h（`--ttl` 可控），**证据命令必须现签**，不可保存旧 URL。

## 一、演示路线：断言集 D（快照内容级）

**场景数据**：`?demo=main-membership-points` 第 1 步 = `state-main-001.json`
（项目「会员积分系统」；焦点文档 `requirements.md`，buffer 174 字符；已提交版本 2、草稿 0；
`recentActivity` 共 2 条：`提交 1758513600.md`、`提交 1758427200.md`）。
空态对照用 `alt-2-empty-gray` 第 1 步（`recentActivity` 为空数组）。

| # | 操作 | 定位 | 断言（可判定谓词） |
|---|---|---|---|
| D1 | 打开演示工作台 | `ai-studio-demo` | 存在，且 `data-demo-scenario` == `main-membership-points` |
| D2 | 看最近活动条 | `recent-activity`（容器）/ `recent-activity-item-<i>` | 容器存在且 `data-activity-count` == fixture `recentActivity.length`；**每条 item 文本逐字包含快照对应 `label`**（内容级，非计数级） |
| D3 | 看需求文档 tab | `[role="tablist"] [role="tab"]` | 首个 tab 文本含 `requirements.md` 且 `aria-selected="true"`；编辑器根 `doc-requirements.md` 存在 |
| D4 | 切 Raw 视图读 buffer | `markdown-toggle` → `textarea[aria-label="requirements.md"]` | textarea 值与 fixture `buffer` **内容级一致**。已知固有改写恰好一处：富文本序列化器把任务清单项 `- [ ] ` 写回为 `- `（2026-09-23 实测为唯一 delta）；判定谓词 = 对双方做 `^- \[[ x]\] ` → `- ` 归一 + 去尾部空白后**逐字符相等** |
| D5 | 看版本历史入口 | `version-history-btn` | 存在且 `disabled == false`（快照版本数=2）；点开 `version-history-list` 归文档 02 展开 |
| D6 | （反向）打开未知场景 | `demo-unknown-scenario` | `?demo=main`（主单字面量）落此画面；`ai-studio-demo` **不在 DOM** |
| D7 | 打开空态世界 | `recent-activity` + `recent-activity-empty` | alt-2 第 1 步：`data-activity-count` == 0 且空态节点存在 |
| D8 | （隔离）演示全程网络审计 | 请求监听 | demo 期间对 `/api/apps/ai-studio/*` 的**非 GET 请求数 == 0**（演示不碰真实数据） |

**证据命令**（自足：现签 token → 起 CDP 无头浏览器 → 全组断言，逐行 PASS/FAIL）：

```bash
# 依赖：隔离栈（scripts-tmp/up-stack.sh：网关 6788 + vite 3050，
# 独立 KIROCREW_HOME=/tmp/acp754-home，已 app enable ai-studio）；
# CDP Chrome 已在 9222。脚本内自动 `kiro_crew token --port 6788` 现签。
cd website && node scripts-tmp/acp754-probe.mjs   # 退出码 0 = D 组+P 组全绿
# 只看快照对照：
python3 - <<'EOF'
import json
fx=json.load(open('website/src/apps/ai-studio/demo/fixtures/state-main-001.json'))
print(len(fx['recentActivity']), fx['recentActivity'][0]['label'], len(fx['buffer']))
EOF
```

vitest 佐证（同一契约的进程内断言）：
`src/apps/ai-studio/demo/demoScript.test.tsx`（`recentActivityItems` 在声明/观测词表内，全 30 步逐帧对齐）。

## 二、普通路线：断言集 P（真实后端）

前提：隔离栈上 `kirocrew app enable ai-studio` 已完成（fresh home 默认 **disabled**，
所有端点回 403 `app_disabled`——2026-09-23 实测坑）；首启引导（导入→隐私弹窗链）已在该
home 落定（`PUT /api/config/theme {onboarded,import_onboarded,privacy_acked:true}`），
否则模态层会拦截一切点击。

| # | 操作 | 定位 | 断言 |
|---|---|---|---|
| P1 | 打开 `/ai-studio` | `ai-studio-projects` | 项目列表页渲染 |
| P2 | 点「新建项目」，填名称/描述，提交 | `form input` / `form textarea` / `form button[type=submit]` | 跳转到 `/ai-studio/projects/<新 id>`（URL 可判定） |
| P3 | 进入新项目工作台（project GET 人为延迟 1.2s） | `ai-studio-loading` → `ai-studio` | **出现→消失**：延迟期间 skeleton `attached`；工作台 `attached` 后 skeleton **不在 DOM** |
| P4 | 看工作台壳 | `ai-studio` / `tool-sidebar` / `recent-activity` / `drafts-pending` / `commit-all-btn` | 壳与侧栏存在；recent-activity `count=0` 且空态节点存在；**「草稿初始为 0」的谓词 = `drafts-pending` 徽标不在 DOM 且 `commit-all-btn.disabled == true`**（徽标组件只在 >0 时渲染，这对组合就是「0」的可判定读法） |
| P5 | （反向）打开不存在的项目 id | `ai-studio-load-error` | 出现，且文本语义命中 `不存在|no longer exists`（不锁单一语言文案） |

P1/P4/P5 的 vitest 佐证：`AiStudioPage.test.tsx` 中
`route dispatch` / `workbench shell` / `recent activity (ACP-754)` / `project-level commit` 各用例。

**证据命令**：同上 `node scripts-tmp/acp754-probe.mjs`（P 组与 D 组同一次跑完）。

## 三、自检清单（本文档验收 = 以下全勾）

- [x] D1~D8、P1~P5 全部有实测 PASS 记录（2026-09-23，探针 21/21，`/tmp/acp754-home/probe-result.txt`）
- [x] 每条断言只有三种锚点：testid / 快照 JSON 字段 / URL；零截图
- [x] buffer 断言是内容级（含已声明的唯一序列化 delta），不是长度级
- [x] demo 路线零写请求有审计断言（D8）
- [x] 反向断言在场：未知场景（D6）、未知项目（P5）
- [x] 证据命令自足（现签 token、自建 home、不依赖登录态）

## 四、新建组件登记（本试点已落码，同提交登记进组件树）

| 新组件 | 承载 testid | 理由 |
|---|---|---|
| `RecentActivityFeed.tsx`（挂 AiStudioPage 与 DemoWorkspace 顶栏下，同一组件两处复用） | `recent-activity`（容器，`data-activity-count`）· `recent-activity-item-<i>` · `recent-activity-empty` | 「当前状态」的可见承载：demo 路线由快照 `recentActivity` 喂，普通路线由既有草稿读（ProjectCommitBar 上报，零新增请求）喂；壳复用顶栏结构，内容新建 |

后序承接：02（edit-requirement）承接 `version-history-btn`/`version-history-list` 与
`recent-activity` 里新增的「未提交草稿」条目；03/04 承接快照 `parity/source` 时同样经
`recent-activity` 呈现活动事实。

## 五、已知坑登记（填坑笔记同步）

- `?demo=` 只在 `/ai-studio` 前缀下生效；`/apps/ai-studio?demo=` 与 `/?demo=` 都静默渲染别的页面。
- 首启引导模态链拦截点击且**异步弹出**（theme-boot 返回后才出现），goto 后立即 dismiss 会漏。
- 富文本编辑器 Raw 视图是模型的**再序列化**，非源文逐字（任务清单勾选项被规范化）。
- vite 的 `/?token=` 握手页禁止 `waitUntil:'networkidle'`（dashboard 长连接永不 idle）。
