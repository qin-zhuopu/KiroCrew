# 静态 testid 防退化测试看不见「数据里写的 id」，而它的报错只会冤枉组件

ACP-2222。派工单要我新建 `website/src/apps/ai-studio/journeyTestids.test.ts`：
读源码做字符串检查，断言全流程每个操作的 testid 还在。想法很朴素——以后谁删了
testid，这个测试就红。写完第一次跑，12 条红。报错长这样：

```
AssertionError: 右栏页签：图谱: 没有组件写 data-testid="ai-studio-tool-graph"
```

**三条红指向的组件都是对的，代码没错。** 挖下去是两个完全独立的原因，报错本身一条都
看不出来。

## 原因一：派工单给的表里，有一个 id 从来不存在

表里写 `需求：判定条 → req-verdict`。我照着断言精确匹配 `data-testid="req-verdict"`，
红。去源码看，判定条有两个，**没有一个是裸的 `req-verdict`**：

```
RequirementPage.tsx     data-testid="req-verdict-bar"           # 打开的页顶部那条
RequirementsTool.tsx    data-testid={`req-verdict-${p.page}`}   # 每行那个颜色块
```

也就是说「判定条」这个操作对应两个控件，脚本只能用前缀选择器
`[data-testid^="req-verdict"]` 找到它们。派工单在表里把它写成一个精确 id，是**派工单
写错了一个名字**（和「派工单不许写没测过的数」是同一类错：表里的名字没实测过）。

修法：给表加一个 `perItem: true`（前缀语义），并且**在前缀条目上把两个都算命中**。
不要为了让测试变绿就把 `req-verdict` 改成 `req-verdict-bar` 了事——那等于把
「每行那个色块」从走查表里悄悄删掉了。

## 原因二：属性正则扫不到「id 是数据，不是属性」的两种写法

我原本用属性级正则扫 `data-testid="…"` / `data-testid={\`…\`}`，故意不做裸子串搜索
（否则注释里提一句这个名字，就能替一个已经丢掉名字的控件把测试撑绿——这是这种
guard 最典型的假绿）。结果我自己的新设计正好撞上它的盲区：

1. **右栏 7 个页签的 id 写在一张表里**，JSX 里是 `data-tool={TOOL_TESTIDS[t]}`。
   七个字符串字面量躺在对象字面量里，属性正则一条都扫不到。
2. **〔信任会话〕的 id 是跨组件传的**：`<TrustDropdown testId="approval-trust" />`，
   真正 `data-testid={testId}` 的地方在 `TrustDropdown.tsx` 里，那里根本没有字面量。

最省事的修法是把检查改成「全文有这个子串就行」。**不能这么改**，理由见上面那段假绿。

正确的修法是把「id 怎么到达 DOM」这件事显式建模（`via` 字段）：

- `attr` —— 属性上直接写的字面量（绝大多数）
- `tab-map` —— id 是对象字面量的值，用花括号配对把 `{ … }` 抠出来再扫
  （不能用正则，嵌套对象会提前截断）
- `testId-prop` —— `testId="…"` 形式，由组件渲染成属性

每种非 `attr` 的形式，**必须再配一条「它真的接到了 DOM 上」的断言**，两条加起来才
等于 `attr` 单独证明的东西。所以我补了：

```ts
expect(src).toMatch(/data-tool=\{\s*TOOL_TESTIDS\[t\]\s*\}/)
expect(src).toMatch(/data-testid=\{\s*TOOL_LEGACY_TESTIDS\[t\]\s*\?\?\s*TOOL_TESTIDS\[t\]\s*\}/)
expect([...dropdown.matchAll(/data-testid=\{\s*testId\s*\}/g)].length).toBe(2)  // 两种形态都要
```

`toBe(2)` 不是随手写的数：`TrustDropdown` 有**两种形态**（只有一档时是普通按钮，
两档以上才是下拉触发器），只挂一处就等于「某些命令的〔信任会话〕点不到」。

## 顺带一个坑：一个 id 挂两个名字时，别把它挪到外层容器

派工单允许「新 id 加在外层，或用两个属性」。我选了**两个属性挂同一个按钮**：

```tsx
data-testid={TOOL_LEGACY_TESTIDS[t] ?? TOOL_TESTIDS[t]}   // 老名字：getByTestId 读它
data-tool={TOOL_TESTIDS[t]}                               // 统一名字：属性选择器读它
```

因为 `DevDagPanel.test.tsx` 在 `ai-studio-dev-entry` 上断言 `aria-selected`。把老名字
挪到外层 `<div>` 上，presence 检查照样绿，但脚本拿到的元素不再带选中态——**这是
guard 抓不到的那种坏**（静态检查只证明「名字写了」，不证明「名字长在正确的元素上」）。
所以外层容器方案要在测试里额外钉一条「老名字必须和 `aria-selected` 同元素」。

## 怎么避免

- **写完 guard 先污染一遍证明它有牙，也要反向证明它不冤枉好代码**：我做了三次变异
  （删 JSX 接线 / 改一个按钮名 / 从表里删一个 key），每次红 2 条，都符合预期；
  反向的证据是「12 条红里没有一条是我的组件真的缺 id」。只看「绿了」不够。
- **静态检查的 corpus 一定要自带一条「语料非空」断言**（`SOURCES.size > 20`、
  `ALL_IDS.length > 100`、点名 4 个必需文件）。我的路径就写错过一层
  （`src/apps/ai-studio` → `website` 要 `../../..`，我写了两层），
  幸好 `readdirSync` 直接 ENOENT 炸了才没变成「扫到 0 个文件，于是全部通过」。
  如果那次目录恰好存在（比如指到了 `src/`），整份 guard 就会安静地永远绿。
- **guard 的报错要写「改名字要三处一起改」**（组件 / 测试表 / RFC 那节）。这种测试
  红的时候，改的人第一反应是「谁动了我的名字」，不写清就有人直接把测试删了。
