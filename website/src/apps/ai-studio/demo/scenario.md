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

### 主线 `main-membership-points`「会员积分系统」（8 步）

需求文档已提交两版（v2 对 v1 只加一行兑换规则；v1 无前驱、整篇按新增）。
剧本走完整业务闭环：

1. main-1 进入项目，文档干净（diff/修改历史灰、版本历史亮）
2. main-2 版本历史看 v2 的增量 diff
3. main-3 版本历史看 v1 —— 最早版本整篇为新增
4. main-4 追加两行验收标准 → 缓冲脏了，diff 图标灰转亮（缓冲经真实 Markdown 源视图敲入）
5. main-5 防抖 2s 到期 → 修改历史落下第一条记录（演示让编辑器自己的 2s 定时器真实走完）
6. main-6 点亮 diff，看红删绿增
7. main-7 点「提交版本」（提示提交触发的三件事）
8. main-8 载入提交后的快照：版本 +1、修改历史清空、图标回灰 —— 闭环

### 分支 A `alt-1-draft-restore`「App 官网改版」（7 步，`branch: alt-1`）

未提交草稿的恢复分支：写候选 A → 自动保存 → 改成候选 B → 自动保存 →
打开修改历史挑**较早**那条 → 在红绿弹窗里真实点击「恢复到该版」→ 恢复后的
文本再被防抖记为第三条（去重只比最新一条，所以放行）。「撤销的撤销」找得回。

### 分支 B `alt-2-empty-gray`「空项目示例」（3 步，`branch: alt-2`）

灰态解释：diff 灰 = 当前内容==最近提交；修改历史灰 = 0 条自动保存；
版本历史灰 = 从未提交。灰态即数据态，不是坏了。

## 状态机（所有剧本共用）

```
干净 --编辑+防抖--> 草稿(+1条记录；内容与上条相同不落新条)
草稿 --提交--> 已提交(vN+1；快照进 versions/，草稿记录清空)
草稿 --恢复某条自动保存--> 草稿(当前内容=该条)
已提交 --编辑--> 草稿
```

每步 JSON 的 `before/after` 是上表状态的逐项声明，由生成器从快照推导
（before(k) ≡ after(k-1)，剧本无法对页面撒谎）；测试逐条在业务 DOM 上兑现。

## 回放约定（改动前必读）

- 下一步/上一步 = 载入该步快照，**禁止反向计算**；进入同一步永远得到同一画面
- 引导层高亮 selector、开面板都归 `overlay.tsx`；业务组件里不许出现任何演示代码
- 剧本里的定位器是命名定位（`draft_history_btn`、`draft_row:older`…），
  见 `locators.ts`；业务组件改 testid 会让剧本响亮地失败而不是悄悄指错
- 改文档内容/时间线：改 `generate_fixtures.py` 重跑，然后
  `npx vitest run src/apps/ai-studio/demo/demoScript.test.tsx`（在 website/ 下）
