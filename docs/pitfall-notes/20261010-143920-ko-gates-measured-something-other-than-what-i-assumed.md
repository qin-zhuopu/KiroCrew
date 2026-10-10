# ko 的两道质检门测的不是我以为的对象

时间：2026-10-10 · 关联：ACP-2213 / ACP-2214 · 相关：
[非拉丁文种拼写门为何会错放](20261010-010657-non-latin-spelling-gate-false-acquittals.md)、
[质检门没有对照组](20261010-014540-uncalibrated-translation-gate.md)、
[交付回报只贴「门禁绿了」](20261010-141557-delivery-report-without-mtime-md5-read-as-fabrication.md)

给 ko（한국어）交付 42 键（`apps.aiStudio` 的 manifest + 界面短标签）时，两道我以为
「测什么」很清楚的门，实际测的都是别的东西。两处都不是报错能看出来的。

## 一、`check-vocab.py ko` 的 HARD FAIL 拦下了一个「真词」

我在 manifest 描述里写了 `코딩 스튜디오 작업대`（coding studio workbench，스튜디오 是
studio 的通用音译）。自检报：

```
[ko] 42 value(s) across 2 file(s)
  HARD FAIL — 1 char(s), 1 distinct, never approved in this repo:
    U+D29C '튜'  (shard-01.json apps.aiStudio.manifest.description)
```

### 我当时的预期（错的）

我默认「字符档防的是**码位不同的假谚文**——肉眼一样、字节不一样的那种。스튜디오 是
韩语里真实存在的通用词，一个真词怎么会撞上字符档」。

### 根因

`check-vocab.py` 对 ko **只跑字符档**（`WORD_LEVEL = {"hi","bn"}`，谚文不按空格分词，
词级判据对 ko 不成立，脚本自己在 `label_for` 里写明「Korean spacing is policed by
koStyle.test.ts, not by a word list」）。而字符档是**逐音节**比对的：把
`vocab-ko.txt`（37,629 个已批准音节）里没出现过的谚文字母当造假信号。

`튜` 这个音节在整个已批准 ko 语料里出现 **0 次**（`git show origin/main:ko.json` 里
`튜` 也是 0 次，`스튜디오` 0 次）。所以：

- 一个韩语母语者觉得天经地义的音译词，只要**这个产品从来没这么写过**，字符档就会红
- 对 ko 来说字符档不是「只防假字形」——**它是 ko 唯一的机械网**（词档根本不跑），
  所以它必须、也确实能把「合法但本仓没用过」的音节揪出来
- 报的是「字符没被批准过」，字面上完全看不出「你用了本仓没有的音译词」这层语义

### 修法

换成同一个应用里**已经批准过**的说法：`apps.aiStudio.run_preview_close` =
`작업대로 돌아가기`，即 workbench 在本仓定名为 `작업대`。于是
`A coding-studio workbench` → `코딩 작업대`，既不用音译，又和本应用已有术语一致。

**「合法词」和「本仓的词」是两件事**：外语音译能不能用，判据不是「母语者认不认」，
是「这个仓的批准语料里出现过没有」。没出现过，就去找已批准的对应词，别硬造音译。

## 二、`check-term-consistency.py ko` 的「no drift」是对着一块正在被别的会话重写的基线量的

同一轮里术语一致性门回过我：

```
[ko] 42 key(s); 1 match an approved wording byte-for-byte, 0 differ only in case/spacing
  no drift: nothing here contradicts an approved wording
```

我差点把这句当「术语全对」的定案。核对时才发现它读的基线是
`website/src/i18n/locales/ko.json`（**工作区文件**），而这个文件此刻被别的会话改着：

| 基线 | 键数 | 相对 main |
|---|---|---|
| `origin/main` 的 ko.json | 16,201 | — |
| 工作区 ko.json（14:25:08 那次快照） | 15,017 | **少 1,729 个键**，另有 545 个 main 里没有的键 |

`git status` 显示 12 个语种目录**全部是 `M`**（de/es/fr/hi/it/ja/ko/pt/ru/zh-CN…），
每个相对 main 都有 260+ 个共享键被改动——这一批翻译会话在**并发重写同一批 catalog**。
我量「no drift」的那一刻，基线里有哪些键、每个键是什么值，都不由我决定。

更直接的假绿信号：**我要交付的 42 个键，在工作区 ko.json 里一个都不存在**（后来
14:38 复核，`present now: 0`）。也就是说这门拿来做对照的「已批准语料」，
既缺了 main 的一大截，又不含本批待翻键——它报的「1 条命中批准措辞 / 无 drift」
里那个「1」是运气，不是覆盖。

### 根因

术语一致性门的判据是「同一条英文在**仓里别的键**上已有的批准译文」，
而它取「仓里」= 工作区文件，不是 HEAD。单会话时两者等价；多会话共用一棵工作树时，
基线是易变的，「drift = 0」既可能是「我全对」，也可能是「基线被削掉了、没有可对照的
peer」。**这两种情况在这道门的输出里长得一模一样**——和
[[silence-is-not-a-verdict]] 同型（脚本对「没数据」和「全通过」不设区分）。

### 修法

裁决基线一律回到 git 对象，别信工作区：

```bash
git -C <repo> show origin/main:website/src/i18n/locales/ko.json > /tmp/ko-approved-base.json
```

拿这个稳定基线重跑同一套对照，才量到**真正存在的**那 1 条 peer：

```
pages.devFleetPage.uncommitted_changes 已批准 '커밋되지 않은 변경'
```

我的 `pending_changes`（`Uncommitted changes`）写的正是 `커밋되지 않은 변경`，
逐字节相同——结论没变，但**这次是有依据的没变**，而不是「没量到」。

顺带确认两条 hint（`탭 닫기`、`자세히 보기`）与 main 里的批准值逐字节相同。

## 三、我的 shard 被别人合并的那一刻，我正好在改它

14:41:54 量到「42/42 已进 catalog，逐字节等于我的 shard」；我随即在 14:43:15 把
`chat_placeholder` 从 `설명해 보세요…` 改成 `설명하세요…`（对齐仓里两条已批准的
`Describe what you want…` = `… 설명하세요`，也符合 ko.md §4「指令用 `~하세요`」）。
14:44:02 再量，catalog 的 mtime 是 **14:42:59**，里面那一条还是我**改之前**的措辞：

```
present 42/42, byte-equal to my shards 41, English-valued 2
  DIFF apps.aiStudio.chat_placeholder
    catalog 원하는 변경 사항을 설명해 보세요…
    shard   원하는 변경 사항을 설명하세요…
```

不是谁写错了，是**合并发生在两次写之间**。那 2 个「English-valued」键是
`manifest.display_name` / `manifest.page_label` = `AI Studio`，品牌名，属决定不是漏翻。

**How:** 交付之后如果还要改措辞，改完必须**重新跑合并**或明确通知合并方「此键在我手里
又变了」；判断依据是 `catalog mtime` 对比 `shard mtime`（`stat -c '%n mtime=%y'` 一条就够），
别只看「键在不在」。合并后的终审要跑**仓里真实的 vitest**（`I18N_GATE=1 npx vitest run
src/i18n/style/koStyle.test.ts`，我这次 39 passed），因为 `verify` 只逐键核格式，
风格门的判据（의존명사 分写、拉丁/名词边界、被动态叠用）读的是**运行时全量目录**。

## 四、最贵的一条：我给「证明门有牙」造的假违规，自己就是假谚文

`verify` 只核格式，风格门读的是合并后的全量目录，所以我重放了仓里真实的
`koStyle.test.ts`（加载它的源码、只换掉两个 import），拿到 `39 assertion(s) … 0 failing`。
但**一个不可能变红的绿等于零信息量**，于是我做反向对照：往分片里注入三条已知违规
（의존명사 粘连、`MCP서버`、`되어집니다`），要求三条都变红。

结果只有两条红。我当场得出一个结论：**「被动态那条门是死的」**——并准备把它写进结论。

逐码位比对才发现：我手打的「被禁写法」落盘成了码位不同的另一串。

| 我想写 | 落盘成 | 码位 |
|---|---|---|
| `되어집…`（被动态，지） | `되어지…`（직） | U+C9C0 → U+D291 |
| `함께 …`（께） | `함뭘게 …` | U+BB54 → U+BDB8 |

门没报是**对的**——我造的根本不是被禁的那个词。**假词的方向和我原本要防的方向相反**：
平时假词让「错译文」蒙过门，这次假词让「有牙的门」蒙过我。同一个根因
（[非拉丁文种拼写门为何会错放](20261010-010657-non-latin-spelling-gate-false-acquittals.md)），
但这条更贵，因为它污染的是**我对工具本身的判断**，而且错的方向是「工具不可信」，
正好把人推向手写规则、加更多正则——那正是这仓明确反对的路
（见 AGENTS.md「A regex spelling-chase is a review smell」）。

### 修法：连 fixture 也不许手打，从谚文字母合成

```python
def syl(*jamo):            # 只在 11,172 个谚文音节里找 NFD 分解等于给定字母的那一个
    want = ''.join(jamo)
    return next(chr(c) for c in range(0xAC00, 0xD7A4)
                if unicodedata.normalize('NFD', chr(c)) == want)
RIL = syl('ᄅ', 'ᅵ', 'ᆯ')   # U+B9B4；这条路径不经过「照屏幕敲」
```

谚文字母（jamo，U+3131 段）是**不可分解的单码位**，手打不会重排；用它合成的音节
必然落在正确码位上。改完反向对照三条全红（另一条见下）。

## 五、顺手量到风格门的召回上限：绿 ≠ 分词正确

重放全绿之后我还是按 ko.md §2 的手工规则（不限词干）把 42 条自己扫了一遍，
判据比门宽：任何谚文音节直接贴着 `수/것/때/뿐/대로` → 嫌疑。结果 0 命中，
三个 `수` 全是 `… 수 있습니다 / … 수 있는` 分写形态。

之所以要自己再扫一遍：门的 `BOUND_NOUN_SPACING` 只覆盖
`(할|될|볼|줄|올|쓸|갈|열|있을|없을)수` 加 `수(있|없)` 尾巴——
它自己的 `.each` 表写着这个取舍（要放行 `작업할수록` 这类词尾，只能收窄集合）。
用码位造的对照证实了漏的一侧：

| 注入 | 门抓到？ |
|---|---|
| `기다릴수 없습니다`（词干不在表内，`수` 后仍有空格） | **否** |
| `기다릴수없습니다`（整段粘连，命中 `수(?:있\|없)` 分支） | 是 |
| `MCP서버`、`되어집니다` | 是 |

所以**「重放 0 failing」这句话只能读成「没踩到那 16 条机械判据」**，不能读成
「韩语分词正确」。同一类错误换个词干就漏。我把它写进了重放脚本的输出文案。

## 怎么避免

- **多会话共用工作树时，任何「与仓里已有 X 对照」的判据，基线一律用
  `git show <ref>:<path>` 取**，不用工作区文件。工作区文件是别人的草稿纸
- 用工作区基线跑出的**绿**要特别警惕：绿往往来自「没有可对照的样本」而不是「全对」。
  先量一下基线还剩多少键（我这次是 15,017 vs main 16,201），键数不对就别信它的话
- **交付回报自带四件套**（绝对路径 / mtime 带时区 / md5 / 回报当次 `date`），
  见 [交付回报只贴门禁绿了](20261010-141557-delivery-report-without-mtime-md5-read-as-fabrication.md)。
  本轮我特意每条结论都附了它是**对哪个文件、哪个时刻、哪个基线**量的
- ko 交付的落地习惯：**外语音译先问「本仓写过没有」**，没写过就找已批准对应词；
  以及 ko 只有字符档这一道机械网，别指望它放过「看着像真词」的东西
- **交付后被合并 ≠ 可以收尾**：合并之后若又改了措辞，用 `stat -c '%n mtime=%y'` 比
  catalog 与 shard 的先后，再看逐键是否相等（`present N/42、byte-equal M/42`），
  差的那几条要显式交给合并方，别默认「已经进去了」
