# 基线取 origin/main 时，「你留了英文」可能是 main 在分叉后自己重译的

日期：2026-10-10 17:40（ACP-2213 收尾）

## 现象

补完 35 个键的译文后，按派工口径跑：

```
cd website && I18N_GATE=1 I18N_BASE_REF=origin/main nice node scripts/i18n-check.mjs
[i18n] 19 checks · FAIL 4
    FAIL    [changed-passthrough]  38 value(s) you added or changed still read as English
```

38 条报的是 `pages.chat.sideChat.refresh_blocked_busy`、
`pages.knowledge.settings.model_desc`、`pages.settings.remoteCrewPanel.sign_in_hint`
× 语种，值全是**英文原文**。看上去像是我这一批漏翻了 3 个键——而且 ticket 里正好写着
「验收判据：从 216 降到 16」，38 这个数怎么都不对，很容易一慌就去「顺手补这 3 个键」。

## 根因

`[changed-passthrough]` 是 **diff 范围**的判据：它取 `base..工作树` 的 catalog 差异行，
对**新增/改动的值**判「还像不像英文」。所以「谁的改动」完全由 **base 取在哪**决定。

三个键的真实历史（逐值核过，脚本 `attr38.py`）：

| | en | de |
|---|---|---|
| 合并点 `c9b060a3`（我分叉的地方） | `Wait for the current answer to finish — …` | 同上（英文，**当时全语种都是英文**） |
| `origin/main`（现在） | `Stop the running answer first — …`（**main 改了英文**） | `Beende zuerst die laufende Antwort — …`（**main 重译了**） |
| 我的 HEAD | `Wait for the current answer to finish — …`（**与合并点逐字节相同**） | 同左 |

也就是说：**main 在我们分叉之后改了英文原文并重新翻译了这些键**。我一行没碰它们。
`base=origin/main` 时，「main 的译文 → 我的（=合并点的）英文」被算成**我的 diff**，
于是 main 自己的重译变成了「你留了英文」。

用**合并点**当基线，同一套门禁：`[changed-passthrough] 0 PASS`。
用 `HEAD` 当基线（只量我自己这几刀）：19 项全 PASS。

同一条判据、同一个工作树，三个基线给出 0 / 0 / 38 三种答案。

## 修法

- 长分支上量「我这一刀有没有引入 X」，基线用 **`git merge-base HEAD origin/main`**，
  不是 `origin/main`。后者量的是「分支 ∪ main 的差」，会把 main 领先的部分算到你头上
- 只想量自己最近的提交，就直接用 `HEAD`（脏树 vs 索引）
- 归属没核清之前**不要动手补**：这 3 个键的正确处置是先合 main 再让 main 的译文进来，
  我手工「翻译」它们等于把 main 已重写的英文又改一遍，还会往这次 diff 里塞 30+ 个不相干键

## 怎么避免

- **任何 `[changed-*]` 判据报红，第一件事是问「base 取在哪」，第二件事才是「值对不对」**。
  判据本身没错，错的是把「与 main 不同」读成「我改的」
- 逐条归属要落到**三个 rev 对比**：合并点 / origin/main / HEAD 各取一次值，
  分类只有五种（main 无此键 / HEAD 缺键 / 值=英文且 main 有译文 / 值=main 值 / 其它）。
  只看 HEAD 一定会误判
- 顺带一条：`auth_login`（值是命令行字面量 `auth login`）合并点就在，ja 当年译成
  `認証ログイン`、其余语种保留原文——**命令名字面量保留原文是对的**，
  它照样会进 passthrough 报告，因为 `auth login` 是两个 ASCII 词，过不了
  `MIN_TOKENS=2` 的单词豁免。看到这种条目先确认它是不是命令，不要翻译它
