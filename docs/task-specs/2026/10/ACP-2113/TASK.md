# 派工单 ACP-2113：AI Studio 新增文案补齐其它语种

> 先 `git merge --ff-only feature/ACP-2015-v1`。开工在 ACP-2113 评论「开工」，完工评论结论并置完成。不停下等确认。
> **测试纪律**：不跑全量测试 / e2e / 浏览器；只跑 `npm run i18n:check`（在 website 目录）这一条。

1. `cd website && npm run i18n:check > /tmp/acp2113-before.txt 2>&1`，记下 catalogParity 每个语种缺几个键。
2. 找出 `apps.aiStudio.*` 下在 `zh-CN.json` 有、其它语种（`website/src/i18n/locales/*.json`，除 en、zh-CN、en-XA）没有的键。
3. 照仓库已有做法补进去：先看 `website/scripts/` 下有没有生成/同步翻译的脚本（搜 `i18n`、`translate`、`sync`），有就用它；没有就按英文原文填（键名、层级与 en.json 完全一致），并在 PR 说明里写「机器未翻，英文占位」。
4. 再跑一次 `npm run i18n:check`，判据：catalogParity 里 `apps.aiStudio.*` 相关缺失为 0，其它项不比第 1 步多红。
5. 只 stage `website/src/i18n/locales/*.json`；提交 `i18n(ai-studio): fill new AI Studio strings in every locale (ACP-2113)`；推 fork。最后只回复「2113 全部完成」。
