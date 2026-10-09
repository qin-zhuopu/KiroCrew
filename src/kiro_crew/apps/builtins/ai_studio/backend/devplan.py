"""从需求图谱生成开发任务计划（ACP-2085-S4 第 1 步）。

纯函数模块：给定工作区和页名列表，算出「这一轮要派哪些活」以及「每个活的提示
词」，不碰会话、不起子进程、不写文件 —— 调度在 ``devdag.py``，判定在
``requirements.py``。分成三个模块是为了让提示词这一份文本只有一个出处：看板、
调度、日志都从这里取，写代码的助手看到的和看板上显示的是同一句话。

每页固定两个任务：``<page>:api``（后端接口）和 ``<page>:web``（前端页面），
web 依赖 api（同一个工作区串行跑，接口先落前端才有得调）。**本步是最小可用版**：
只有一个阶段 ``full``，不拆演示版/完整版（``07-dev-dag-two-phase.md`` §〇 的两
阶段、tag、回退、Jira 都不做）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kiro_crew.apps.builtins.ai_studio.backend import requirements

#: 一个页面派生出的两种活，顺序即任务顺序（先接口后页面）。
KINDS = ("api", "web")

#: 两种活的中文名，进任务标题和提交说明。
KIND_LABELS = {"api": "后端接口", "web": "前端页面"}

#: 提示词里「这一段要求」的两半：api 讲后端怎么落，web 讲前端怎么落。
#:
#: 两半都是给写代码的助手看的**散文要求**，不是模板占位：它的措辞就是验收对象
#: （RFC §10 验收 14「生成的东西里搜不到『原页面』『旧页面』『.vue』『原接口』」
#: 的同一条纪律落到提示词上）。所以这里不接任何外部输入插值，页名之外一个字都不
#: 变 —— 变一个字，两个任务看到的规格就不是同一份了。
_KIND_REQUIREMENT = {
    "api": (
        "api：在 apps/api/src/ 下照现有台账模块（如 review-flow-store）的写法新建本页的模块"
        "并在 app.module.ts 注册；接口地址、入参出参照需求文档「接口」一节。写单测。"
    ),
    "web": (
        "web：在 apps/web/src/features/ 下照现有台账页（如 review-flow-store）的写法做本页，"
        "路由加进 main.tsx，菜单加进 app/domains.ts 的「业务示例」域；字段、按钮、提示文案照"
        "需求文档原文。写单测。"
    ),
}


def task_prompt(page: str, kind: str) -> str:
    """一个任务交给助手的那段话（一字不差，页名以外不变）。

    ``kind`` 只许是 ``KINDS`` 里的两种：第三种组合没有对应的落点目录描述，拼出
    去就是一句助手照做不了的话，宁可当场报错也不要发出去。
    """
    if kind not in _KIND_REQUIREMENT:
        raise ValueError(f"unknown kind: {kind}")
    label = KIND_LABELS[kind]
    lines = [
        f"你在这个工作区里开发「{page}」页面的{label}。",
        f"只看 {requirements.REQ_DIR}/{page}.md（需求文档）和 {requirements.REQ_DIR}/{page}.json"
        "（需求图谱），不要参考任何旧系统。",
        "先读工作区根目录的 CLAUDE.md 和 docs/需求标准/使用说明.md（有就读）。",
        _KIND_REQUIREMENT[kind],
        # 用户定案（2026-10-09）：开发会话**不跑任何测试/类型检查/e2e**——几个会话同时跑会把机器
        # 资源耗尽（当晚实测 load 到 880）。测试统一由平台〔跑验收〕一次跑。
        f"不要运行任何测试、类型检查、e2e 或开发服务器（验收由平台统一跑）。写完直接 git commit，提交说明「feat: {page} {label}」。",
        "最后一句只回复：完成 或 失败：<原因>。",
    ]
    return "\n".join(lines)


def task_id(page: str, kind: str) -> str:
    return f"{page}:{kind}"


def task_title(page: str, kind: str) -> str:
    return f"{page}：{KIND_LABELS[kind]}"


def build_plan(ws: Path, pages: list[str]) -> dict[str, Any]:
    """每页两个任务，按页的传入顺序铺开：第1页 api、第1页 web、第2页 api …

    ``dependsOn`` 只有一条边（``<page>:web`` 等 ``<page>:api``）：页内串行是真
    依赖，页之间在这一版靠调度循环的串行顺序保证，不假装成依赖图。

    ``graphHashes`` 带每页图谱的 hash，验收记录要拿它当 ``requirementVersion``
    （07 §三 B4「验收记录可追溯到 requirementVersion」）：计划算一次，后面每个
    环节都读同一份，不要在验收时重算一遍再指望图谱没动。
    """
    tasks: list[dict[str, Any]] = []
    graph_hashes: dict[str, str] = {}
    for page in pages:
        graph_hashes[page] = requirements.graph_hash(ws / requirements.REQ_DIR / f"{page}.json")
        for kind in KINDS:
            depends = [task_id(page, "api")] if kind == "web" else []
            tasks.append(
                {
                    "id": task_id(page, kind),
                    "page": page,
                    "kind": kind,
                    "title": task_title(page, kind),
                    "prompt": task_prompt(page, kind),
                    "dependsOn": depends,
                }
            )
    return {"tasks": tasks, "graphHashes": graph_hashes}
