---
title: AI Studio 前端组件树
doc-id: component-tree
status: 定稿
snapshot-date: 2026-09-23
source: website/src/apps/ai-studio/
maintainer: sid-req-design
updated: 2026-09-23
note: 本树随组件结构漂移，改组件须同提交更新
---

# AI Studio 前端组件树（写验收文档前先查这里）

- 快照日期：2026-09-23，源码位置 `website/src/apps/ai-studio/`
- **用途**：写细节验收文档时，先来这里**选组件**——能复用现有组件+现有 testid 就不新建；确实缺，再在文档里声明新建组件与新 testid（如 `08-publish-app.md` §六的做法）。
- **命名规约**：静态 testid 用 `ai-studio-<名>` 或语义名（`release-btn`）；列表项用 `\<前缀>-\<记录id>` 模板（如 `commit-$id`）。
- 组件重构自由，但**已进入验收文档的 testid 不许丢**。
- 本树会漂移：**改了组件结构/增删组件时同一提交更新本文件**。

## 树

```
路由（两套 URL，互不掺和）：
  /workspaces                 → ProjectsListPage（项目列表+新建，独立路由页）
  /workspaces/<id>/ai-studio  → AiStudioPage（单个项目的工作台）
  /release-jobs/<发布号>           → ReleaseJobPage（发布详情页，08 细节文档新增；Jenkins 式
                                发布历史+流式日志，独立路由页，不经工作台）
  旧地址（静态重定向，query/hash 保留）：/ai-studio* → /workspaces；
  /projects/<id>/ai-studio → /workspaces/<id>/ai-studio（ProjectsPage 垫片）

ProjectsListPage.tsx                    项目列表页（独立路由 /workspaces）
└─  testid: ai-studio-projects

AiStudioPage.tsx                        工作台页壳（路由 /workspaces/<id>/ai-studio）
├─  testid: ai-studio · ai-studio-loading · ai-studio-load-error
├─ RecentActivityFeed.tsx               最近活动条（01 试点新建；顶栏下横条，
│                                       demo 由快照 recentActivity 喂、普通模式由草稿读喂）
│   └─  testid: recent-activity · recent-activity-item-<i> · recent-activity-empty
├─ demo/DemoWorkspace.tsx               ?demo= 演示模式壳（零 API）
│   └─ demo/overlay.tsx                 demo-hint · demo-stepper · demo-play
│                                       demo-next · demo-prev · demo-restart
│                                       demo-ring · demo-unknown-scenario
├─ ToolSidebar.tsx                      右侧边栏（各视图页签入口，含发布页签）
│   └─  testid: tool-sidebar · ai-studio-publish-entry（releases 页签本体，
│        其内容=发布版本列表 PublishVersionList）
├─ PublishVersionList.tsx               发布版本列表（releases 页签内容，08 细节文档 §六新建）
│   └─  testid: ai-studio-publish-version-list
│            ai-studio-publish-version-row-<版本号> · ai-studio-publish-version-state
│            ai-studio-publish-reason-<版本号> · ai-studio-publish-btn-<版本号>
│        行内按钮渲染=行 hash vs 最新成功发布 hash（相同不渲染、行标已发布）。
│   └─  行内发布结果条（T6，本组件内渲染）
│        testid: ai-studio-publish-status-<版本号> · ai-studio-publish-form-badge-<版本号>
│                 ai-studio-publish-url-<版本号>（<a href>=发布记录 url，新页签）
│                 ai-studio-publish-id-<版本号>（<a href>=/release-jobs/<发布号>，新页签）
│        点击即发（无弹层）；发布中轮询 GET /publish/records，成功记录落位即
│        终态（行标已发布、按钮消失）；失败原因只来自触发应答；409 保持单个发布中。
│        发布详情页由 T8 另行登记。
├─ ChatPane.tsx                         需求对话区
│   └─  testid: ai-studio-chat
├─ ProjectCommitBar.tsx                 项目提交条
│   └─  testid: drafts-pending · commit-all-btn
├─ ReleaseControl.tsx                   顶栏动作按钮（release/distill/dev 三态一表）
│   └─  testid: release-btn · distill-btn · dev-btn
├─ WorkArea.tsx                         工作区多 tab 容器（按 tab 挂载下列视图）
│   ├─ DocEditor.tsx                    需求文档编辑器
│   │    testid: doc-<文档名> · version-view-<文档名> · toolbar-trio
│   │            diff-btn · markdown-toggle · draft-history-btn · draft-history-list
│   │            version-history-btn · version-history-list · restore-version-btn
│   ├─ CommitView.tsx                   提交视图
│   │    └─  testid: commit-<提交id>
│   ├─ DiffView.tsx                     差异视图（导出 UnifiedDiffText/LineDiff 供复用）
│   │    └─  testid: diff-<文件>
│   ├─ CodeGenView.tsx                  代码生成视图
│   │    └─  testid: codegen-view · codegen-code · codegen-preview
│   │            codegen-file-<path> · codegen-source-node-<path>
│   ├─ DeployLog.tsx                    发布/部署日志
│   │    └─  testid: deploy-log-<部署id>
│   ├─ NodeDetail.tsx                   图谱节点详情
│   ├─ GraphView.tsx                    需求图谱视图
│   │    └─  testid: graph-view · graph-node · graph-removed-row
│   ├─ RegenDiffView.tsx                文档重生成差异（三段 diff 配对）
│   │    └─  testid: regen-doc-view · regen-diff-pair · regen-badge-<来源版本>
│   │            diff-group-row-<候选id> · diff-group-change-<变更id>
│   ├─ DistillPanel.tsx                 沉淀面板
│   │    └─  testid: distill-panel · distill-candidate-<id> · distill-status-<状态>
│   ├─ DevRunView.tsx                   开发执行视图
│   │    └─  testid: dev-run-panel · dev-design-version · dev-phases
│   │            dev-phase-<阶段名> · dev-artifact-<种类> · dev-runnable-version
│   │            run-open-btn · run-preview · run-preview-close · run-preview-lines
│   └─ ProjectHistoryView.tsx           全程历史时间线
│        └─  testid: history-timeline · history-event-<事件id> · history-jump-<事件id>
└─ 公共（app 外，`website/src/components/`）：Btn/ContentSkeleton/EmptyState/
   Input/PageHeader（ui.tsx）· Clickable · ErrorNotice
```

## 复用规则（写验收文档时照做）

1. **先查本树**：要断言的行为已有组件承载 → 直接引用该组件的 testid，禁止新建平行组件。
2. **壳复用、内容新建**：新视图挂进 `WorkArea`，新侧栏块挂进 `ToolSidebar`，日志类用 `DeployLog` 形态。
3. **确实缺**：在细节文档里单列「新建组件」表（组件名 + 承载 testid + 理由），并同提交把新组件登记进本树。
4. 列表项 testid 一律走 `\<前缀>-\<id>` 模板，不数序号。
