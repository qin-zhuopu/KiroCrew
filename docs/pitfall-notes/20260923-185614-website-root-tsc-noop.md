# 前端根目录 `npx tsc --noEmit` 是空跑，报假绿

## 现象

在 `website/` 里跑 `npx tsc --noEmit`，**exit 0、一行输出都没有**——哪怕代码里有
真错。实锤：`PublishVersionList.tsx` 里把 `releaseAction` 写进了 props 的类型注解，
却漏了解构（`function C({ projectId, api, releaseFiles }: {...}`），运行时
`ReferenceError: releaseAction is not defined` 炸掉整个组件、18 条用例里 10 条红；
而同一时刻 `npx tsc --noEmit` 报的是「全绿」，连主干上已知的
`demo/states-commit.ts(288,98) TS7053` 都没报出来。

## 根因

`website/tsconfig.json` 是**方案（solution）配置**：

```json
{ "files": [], "references": [{ "path": "./tsconfig.app.json" }] }
```

`files: []` 表示这个配置自己**不含任何源文件**，`references` 只是给
`tsc -b`（build 模式）用的项目引用。而 `npx tsc --noEmit` 走的是**非 build 模式**，
它不会顺着 references 去编子项目——于是它一个文件都不检查，秒退 0。

真门禁是 `package.json` 里那条：`"typecheck": "tsc -p tsconfig.app.json"`（`build`
脚本的第一步也是它）。

## 修法

自测/门禁用显式指项目的写法：

```bash
cd website && npx tsc -p tsconfig.app.json --noEmit
```

注意 `tsconfig.app.json` **排除了 `src/**/*.test.tsx`**，所以它不检查测试文件；
测试文件的类型错只有 vitest 跑起来才会暴露。

## 怎么避免

- 看到「tsc 全绿」先确认它**真的编了文件**：故意在某个 `.tsx` 里写一行
  `const x: number = "s"`，报错才是活的门禁；或者看输出里有没有你已知的既有错误
  （本仓 `demo/states-commit.ts(288,98)` 那条可以当「探针」）。
- 别人给的命令（ticket 里写的 `cd website && npx tsc --noEmit`）也要先验一遍再当门禁用；
  这条命令在本仓**从来就是空跑**，不是谁改坏的。
- 方案配置（`files: []` + `references`）的仓，一律用 `-p <子配置>` 或 `tsc -b`。