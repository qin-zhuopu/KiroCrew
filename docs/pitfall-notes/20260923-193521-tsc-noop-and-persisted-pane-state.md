# website 的两个假绿：根目录 tsc 空跑、测试间残留 localStorage

日期：2026-09-23 · 相关：ACP-801（把「提交全部」从 header 挪进工具边栏「提交」页签）

## 坑一：在 `website/` 跑 `npx tsc --noEmit` 是空跑，永远 exit 0

### 现象

改完 `ToolSidebar.tsx` / `AiStudioPage.tsx`，按常规自测：

```bash
cd website && npx tsc --noEmit
# 没有任何输出，exit 0 ——「类型干净」
```

但随后用 `npx tsc --noEmit -p tsconfig.app.json` 一跑，报了 2 个错（在别的
分支合进来的 demo 文件里）。也就是说根目录那次「绿」什么都没检查过。

### 根因

`website/tsconfig.json` 是 **solution 风格的引用文件**：它 `files: []`，只靠
`references` 指向 `tsconfig.app.json` / `tsconfig.node.json`。而 **`tsc --noEmit`
不做 project references 解析**（那是 `tsc -b` 的活），空 `files` 就等于零输入 ——
于是它秒退、零诊断、exit 0。从命令行看不出任何异常，比报错更危险，因为一个
「通过」被记成了「验过了」。

### 修法

前端类型检查一律指定工程：

```bash
cd website && npx tsc --noEmit -p tsconfig.app.json
```

（要连测试一起查就再跑一次 `-p tsconfig.vitest.json`；或 `npx tsc -b` 走引用，
但 `-b` 会做 emit 计划、比单工程慢。）

### 怎么避免

- 任何「我跑过 tsc 了」的结论，要能在输出里指出它加载的是**哪个 tsconfig**。
  只有 exit code 没有诊断文件列表的 tsc 运行，按未验处理。
- 同理怀疑其它「零输出即通过」的检查：先看它实际拿到了什么输入。

## 坑二：同一个测试文件里，前一个用例改的面板隐藏态会毒死后一个用例

### 现象

`AiStudioPage.test.tsx` 里新加的用例要点开边栏的 Commits 页签，报：

```
TestingLibraryElementError: Unable to find role="tab" and name "Commits"
```

且 dump 出来的 DOM 里**整个 `data-testid="tool-sidebar"` 都不存在** —— 不是找不到
按钮，是侧栏根本没挂载。单跑这一个用例（`-t "keeps the header free"`）却**通过**。

### 根因

`AiStudioPage` 把三栏的显隐**持久化到 localStorage**（`ai-studio.hidden`，见
`loadHidden` / `togglePane`）。文件里更早的 pane-toggle 用例把三栏挨个点隐藏，
写了 `{right:true,…}`；happy-dom 的 `window` 在**同一测试文件内共享**，`beforeEach`
只做了 `vi.clearAllMocks()`，没清 storage。于是后面的每个用例挂载时都从 localStorage
读出「工具边栏隐藏」，`!hidden.right` 为假，侧栏整棵子树不进 DOM。

单跑通过是因为跳过了投毒的那个用例 —— 典型的**测试顺序耦合**，报错信息（找不到
tab）与原因（前一个用例的持久化状态）隔着十万八千里。

### 修法

在该文件的 `beforeEach` 里加 `window.localStorage.clear()`，让每个用例都从
「三栏全显」的干净初始态开始。

### 怎么避免

- 组件一有 localStorage / sessionStorage 持久化，它的测试文件就**必须**自己清：
  别指望隔离运行，同一文件内共享 window 是默认行为。
- 看到「某节点在 DOM 里完全不存在」+「单独跑就过」，先怀疑**共享的初始状态被
  前序用例改写**（storage、`document.body` 残留、模块级单例），而不是怀疑选择器写错。
