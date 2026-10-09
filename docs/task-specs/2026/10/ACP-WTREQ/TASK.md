# 派工单：并行开发的副本里看不到需求文件（实战二号卡点，急）

> 先 `git merge feature/ACP-2015-v1`。Jira：ACP-2085 下「[并行副本缺需求]」开头的子单，开工评论、完工置完成。
> **测试纪律**：只跑 `test/test_ai_studio_devdag.py`。不停下等确认。

## 现象（/workspaces/sbjh，2026-10-10 04:31~04:53）
写需求助手把 `docs/需求图谱/施工设备借用单.json/.md` 写在工作区主目录里但**没提交**。ACP-2207 的并行调度从 `HEAD` 拉副本（`.ai-studio/wt/1`），副本里**没有这两个文件**——开发助手只能自己再造一份；做完合回主目录时，git 报「未跟踪的工作区文件将被合并覆盖」，节点 failed「合并冲突」，重试一次照样失败。

## 修法（`backend/devdag.py`）
1. 每轮开发**开始前**（start / 从失败处继续 / 修复节点开始前）在主目录做一次「需求快照提交」：`git add docs/需求图谱` 下所有改动和新文件 → 有改动才 `git commit -m "docs(需求图谱): 开发前快照"`（走正常提交检查，不许 --no-verify）；提交失败 → 这一轮直接 failed，message「需求快照提交失败：<原文>」，不起任何副本。
2. 副本一律从这个快照之后的 HEAD 拉。
3. 合并前若主目录还有会挡路的未跟踪文件（`git merge` 报 would be overwritten），message 写清是哪些文件、建议先提交，而不是只写「合并冲突」。
4. 测试（替身 git）：有未提交需求文件时 start 先提交再建副本；提交失败不建副本；无改动不提交。

提交 `fix(ai-studio): snapshot requirement files before spawning dev worktrees`，推 fork。只回复「快照 全部完成」。
