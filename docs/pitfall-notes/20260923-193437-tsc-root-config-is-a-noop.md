# `npx tsc --noEmit` 在 website/ 根目录是空跑

**日期**：2026-09-23（ACP-803 自测时踩到，owner 指出）

## 现象

在 `website/` 里按直觉跑 `npx tsc --noEmit` 做类型自检，命令**秒退、零输出、
exit 0**——看起来是"类型全过"。同一时刻 `npx tsc --noEmit -p tsconfig.app.json`
却报了 2 个真实错误。也就是说根目录那条命令报的"绿"是假的。

## 根因

`website/tsconfig.json` 是 **project-references 聚合配置**：`"files": []` +
`"references": [...]`（指向 app/node 等子配置）。`tsc --noEmit` 不带 `-p`/`--build`
时按**当前目录的 tsconfig** 解析文件集，`files: []` 意思是"这个工程一个文件都不
检查"，引用只在 `tsc --build` 时才跟进。所以它检查了空集，exit 0 与代码质量无关。
`tsconfig.app.json` 才是真正覆盖 `src/` 的那份。

## 修法

- 前端类型自检一律 `npx tsc --noEmit -p tsconfig.app.json`（`website/` 下）。
- 更彻底的替代：`npx tsc -b`（会跟进全部 references，等价于 CI 口径），但开发阶段
  只查自己改的子系统时用前者更聚焦。

## 怎么避免

- 任何"tsc 过了"的结论，要能说出它是**带着哪个 -p** 跑出来的；根目录裸跑不算数。
- 新会话/新 worktree 里第一次做前端自测，先跑一次带 `-p tsconfig.app.json` 的
  全量，把**存量错误**（本例是别的切片文件的 2 个：states-commit.ts 的 TS7053、
  states-design.ts 的 TS2353）记为基线，之后的"无新错"才有参照。
