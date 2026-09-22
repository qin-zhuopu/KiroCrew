# AI Studio 智能演示 · 剧本说明书（人读版）

方法论全文见
[docs/guides/ai-studio-demo-methodology.md](../../../../../docs/guides/ai-studio-demo-methodology.md)。
本目录是它的落地：`steps/*.json` 剧本、`fixtures/state-*.json` 每步状态快照、
`overlay.tsx` 视觉引导层、`demoScript.test.tsx` 剧本四项断言。快照与剧本由
`generate_fixtures.py` 统一生成（版本 diff 与后端 difflib 逐字节一致），**不要手改 JSON**。

## 怎么打开

用独立 home 起网关（不碰真实数据）：

```bash
KIROCREW_HOME=/tmp/kiro-demo-home python3 -m kiro_crew gateway
```

浏览器打开（路径里的项目 id 会被忽略，剧本自带演示项目）：

```
/ai-studio/projects/any?demo=main-membership-points   # 主线
/ai-studio/projects/any?demo=alt-1-draft-restore      # 分支 A
/ai-studio/projects/any?demo=alt-2-empty-gray         # 分支 B
```

右下角出现步进器（上一步 / 下一步 / 自动播放 / 重开）。演示模式下数据层由快照
fake 接管：不发任何 fetch，任何写只动内存，换步即整体丢弃。

## 三条线

### 主线 `main-membership-points`「会员积分系统」（17 步）

需求文档已提交两版（v2 对 v1 只加一行兑换规则；v1 无前驱、整篇按新增）。
剧本走完整业务闭环：

1. main-1 进入项目，文档干净（diff/修改历史灰、版本历史亮）
2. main-2 版本历史看 v2 的增量 diff
3. main-3 版本历史看 v1 —— 最早版本整篇为新增
4. main-4 追加两行验收标准 → 缓冲脏了，diff 图标灰转亮，**首次变更立即落第一条记录**
   （缓冲经真实 Markdown 源视图敲入；规则「diff 亮必有记录」，不存在亮着但 0 条的窗口）
5. main-5 停手 2s 防抖到期 → 内容与最新记录相同，**不落第二条**（去重）
6. main-6 点亮 diff，看红删绿增
7. main-7 顶栏待提交汇总（ACP-727：提交是项目级操作，徽章列出含草稿的文档）
8. main-8 点顶栏「提交全部」——真实点击、真实提交逻辑（数据来自快照 fake）：
   版本 +1、修改历史清空、编辑器重挂到已提交基线、图标回灰
9. main-9 提交喂图谱（ACP-729）：页底需求图谱面板（快照携带）亮起两个绿框
   新节点——正是 v3 新加的两行需求；「新增」由前后快照的图谱集合差生成器
   交叉校验，不是剧本口头声明 —— 闭环在提交的目的处合上
10. main-10 点顶栏「发版」（ACP-730，第二个真实点击步）：按钮走三步过程感
    （解析图谱 → 生成文件清单 → 完成，标签由剧本声明、演示层计时），落位到
    after_fix 快照 main-010：页底换成「已发版 v3」+ 生成代码面板（左文件树、
    右预览，每个文件标注源自图谱哪个节点）。生成文件的 `derivedFrom` 全部
    落在本次提交带来的图谱增量里（生成器按 main-009 的 graphDelta 校验），
    需求→图谱→代码的追溯链在这里合龙
11. main-11 点顶栏「开始沉淀」（ACP-733，第三个真实点击步）：落位到
    after_fix 快照 main-011——沉淀任务「进行中」。验收口径：图谱的这轮更新
    不是提交直接出的，是**发版后 AI 把冻结文档沉淀为结构化设计事实**
12. main-12 看沉淀过程：3 条候选结构化变化按新增/修改/删除分组，每条注明
    提炼自哪段文档（`evidenceDoc`）；图谱仍是旧的——应用是下一拍的事
13. main-13 看最新结构化设计：图谱吸收候选（GRAPH_DISTILLED）——新增节点
    实线亮框、被细化的节点虚线亮框、孤儿节点划删除线列出。新增/修改/移除
    三个数由前后快照图谱差机器校验，且与候选清单一一对应
    （`check_distillation`：候选 target 必须等于图谱波动的 add/modify/remove
    集合）——发版→沉淀→结构化设计的因果链完整
14. main-14 看重生成的文档（ACP-734，验收文档步骤 10）：沉淀应用后，AI
    **从结构化设计事实反向重生成文档**——版本历史出现 v4（真实版本行，diff
    由 difflib 生成），演示层面板标注它由哪次沉淀生成（`regeneration`
    快照字段）。重生成内容是派生不是手写：细化行带着被修改节点的新标签，
    「设计事实」段落逐字复用新增候选的 summary（`check_regen` 校验）
15. main-15 核对三段成组 Diff 之「用户改动」（验收文档步骤 11，同点三连拍
    第一拍）：打开成组 Diff——按业务点分组（一组一候选），环住闭环最完整的
    「兑换券 7 天有效」行的**左段**：你在 v3 亲手写下的有效期那一行。行是从
    版本行的 unified diff 里按业务点关键词切出来的，`check_regen` 对回快照
    逐字节校验——这一段显示什么，快照里就得有什么
16. main-16 同点第二拍：环住**中段**「结构化变化」——沉淀对这个业务点产出
    的细化候选（带来源段落），左右是文档的行、中间是图谱的事实
17. main-17 同点第三拍：环住**右段**「重生成差异」——v4 为这一点带出的行，
    与左段你的原话对照：系统理解得对不对，一眼核对。左右为空的组同样诚实
    （`diff_group_empty`）：纯沉淀新增的组你没写过它，图谱移除组在 diff 里
    没有行（移除的是图谱挂靠不是文档内容）——`check_regen` 甚至禁止 remove
    组携带任何文档行，空也是数据

### 分支 A `alt-1-draft-restore`「App 官网改版」（7 步，`branch: alt-1`）

未提交草稿的恢复分支：写候选 A → 首次变更立即落第一条记录 → 改成候选 B →
与最新记录不同，落为第二条 → 打开修改历史挑**较早**那条 → 在红绿弹窗里真实
点击「恢复到该版」→ 恢复后的文本与最新一条（候选 B）不同，再被记为第三条。
「撤销的撤销」找得回。

### 分支 B `alt-2-empty-gray`「空项目示例」（3 步，`branch: alt-2`）

灰态解释：diff 灰 = 当前内容==最近提交；修改历史灰 = 0 条自动保存；
版本历史灰 = 从未提交。灰态即数据态，不是坏了。

## 状态机（所有剧本共用）

```
干净 --编辑(首次变更立即落记录)--> 草稿(+1条记录；内容与上条相同不落新条)
草稿 --提交--> 已提交(vN+1；快照进 versions/，草稿记录清空；图谱 +Δ)
已提交 --发版--> 已发版(代码自图谱生成；每个文件标注来源图谱节点)
已发版 --沉淀--> 已沉淀(结构化事实候选→采纳→图谱吸收：新增/修改/移除)
已沉淀 --重生成--> 已重生成(结构化事实反向产出文档 vN+1；成组 Diff 三段核对)
草稿 --恢复某条自动保存--> 草稿(当前内容=该条)
已提交 --编辑--> 草稿
```

图谱、发版、沉淀与重生成只在携带它们的世界里参与状态机（主线快照全部带
`graph`，主线末尾几步带 `release`/`generatedFiles`/`distillation`/
`regeneration`/`diffGroups`，分支线都没有）：
节点数与「本次新增/修改/移除数」是 before/after 的可选字段，`graphDelta`
（含 `modified`/`removed`）必须等于前后快照图谱差（生成器拒绝不一致）；生成
文件的 `derivedFrom` 必须是图谱增量的子集（`generatedFrom` 锚定）；沉淀候选
清单（`distillation`）在采纳落位那帧必须**等于**图谱波动（`check_distillation`：
add/modify/remove 三组 target 分别对上 delta 的三个集合），所以候选面板和
图谱高亮不可能互相撒谎。图谱视图、代码预览、沉淀面板都是业务侧纯 props
组件（`GraphView.tsx` / `CodeGenView.tsx` / `DistillPanel.tsx`），发版/沉淀
按钮（`ReleaseControl.tsx`）真实路径不渲染——后端还没有图谱/发版/生成/沉淀
端点，不放假功能。

每步 JSON 的 `before/after` 是上表状态的逐项声明，由生成器从快照推导
（before(k) ≡ after(k-1)，剧本无法对页面撒谎）；测试逐条在业务 DOM 上兑现。

## 回放约定（改动前必读）

- 下一步/上一步 = 载入该步快照，**禁止反向计算**；进入同一步永远得到同一画面
- 引导层高亮 selector、开面板都归 `overlay.tsx`；业务组件里不许出现任何演示代码
- 剧本里的定位器是命名定位（`draft_history_btn`、`draft_row:older`…），
  见 `locators.ts`；业务组件改 testid 会让剧本响亮地失败而不是悄悄指错
- 改文档内容/时间线：改 `generate_fixtures.py` 重跑，然后
  `npx vitest run src/apps/ai-studio/demo/demoScript.test.tsx`（在 website/ 下）
