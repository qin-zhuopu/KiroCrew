# 在前端目录之外跑 vitest：测试全红，报错却指向 testing-library

时间：2026-10-08 21:17 · 会话：kc-ws · 相关：ACP-2085（新建工作区对话框）

## 现象

新写的 `website/src/apps/ai-studio/NewWorkspaceDialog.test.tsx`，17 个用例**全部**失败，
两种报错：

```
ReferenceError: document is not defined
TypeError: Cannot read properties of undefined (reading 'Symbol(Node prepared with document state workarounds)')
```

同一时间同一条命令在别的目录跑是绿的。第二次我按判据写了 `cd website && npx vitest run ...`
（**分两次工具调用**写的 `cd`），结果一模一样；把 `cd` 和命令合并成一条调用，立刻 17 passed。

## 根因

**vitest 的工作目录决定了它能不能读到 `vite.config.ts`，而 jsdom 环境就写在那个配置里。**

1. 工具每次调用结束就把工作目录重置回项目根（本机 Bash 的既成事实，全局约定里也记着）。
   于是 `cd website`（第 1 次调用）之后，`npx vitest run ...`（第 2 次调用）其实是在**仓库根**跑的。
2. 仓库根**没有** `vite.config.ts` / `vitest.config.ts`（`ls` 出来只有 `website/` 里有
   `vite.config.ts`、`vite.kirodev.config.ts`、`vite.shared.ts`）。没有配置就没有
   `test.environment: 'jsdom'`，也没有 setup 文件。
3. 没有 jsdom → 没有 `document`。`render()` 直接 `ReferenceError: document is not defined`。
4. 后面那串 `Symbol(Node prepared with document state workarounds)` 是**同一件事的第二次报错**：
   testing-library 在无 DOM 的环境里取内部 symbol 时踩到 undefined，报错信息完全没提
   「你在错误的目录、用错误的配置跑的」。

两个报错都指向 testing-library / 环境本身，没有任何一个字符提到 cwd 或配置文件，
所以第一反应是「我的测试写错了 / 这个组件不能这么测」。实际错的只是**从哪儿跑**。

顺带一个同源陷阱：从仓库根跑 `npx tsc --noEmit -p .` 会命中**根目录**那个只有一行
`{"references": [{"path": "./tsconfig.app.json"}]}` 的 solution 文件，
`files: []` 让它**一个文件都不检查**，输出为空、退出码 0 —— 假绿。
`website/tsc --noEmit -p .` 才是判据要的那次检查。

## 修法

把 `cd` 和命令写进**同一条**命令，并在同一输出里自证目录：

```bash
cd /home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-kc-ws/website && pwd && npx vitest run src/apps/ai-studio/
```

`pwd` 打印出 `.../website` 才算这一轮跑的是真目标。类型检查同理：
`cd website && pwd && npx tsc --noEmit -p .`。

## 怎么避免

- **任何前端命令都用 `cd <绝对路径> && pwd && <命令>` 一条写完**。`pwd` 是给自己的收据，
  不是装饰：没有它，「跑错了目录」和「跑对了但真失败」在输出上长得几乎一样
- 判据「`npx tsc --noEmit -p .` 无输出」必须**补一条正向证据**（比如故意留个类型错再看它报不报），
  否则 solution tsconfig 的空跑也算「无输出」
- 看到 `document is not defined` + `Symbol(Node prepared with document state workarounds)`
  这一对，**先查目录和配置文件，不要查测试代码**：组件测试写得再对，无 jsdom 也全红
- 顺手记一条归属分诊法（本轮 `[manifest-sync]` 7 条红就是靠它确认与本次改动无关的）：
  `git show HEAD:<file> | python3 -c "import json,sys; d=json.load(sys.stdin); ..."`
  看报缺的键在 HEAD 上存不存在——不存在就是存量债，不是我引入的

## 附：本轮另一个真坑（门禁要求，不是 bug）

往 `en.json` 加键之后 `[pseudolocale]`（hard zero）会红：`en-XA.json` 是
**生成物**，必须跟着提交。

```bash
cd website && node scripts/gen-pseudolocale.mjs         # 写
node scripts/gen-pseudolocale.mjs --check               # 验，输出 OK 才算过
```
