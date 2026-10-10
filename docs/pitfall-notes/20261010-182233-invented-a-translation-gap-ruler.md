# 我自己造的「没翻译」尺子，把 575 个术语判成缺陷，仓里的裁判报 0

## 现象

补 ACP-2113 的语种缺口时，我需要一个数来回答「还差多少没翻」。我用了最直觉的尺子：

> 一个键的值若**与英文源字符串逐字相同**，就算没翻。

跑出来：**3724 个分支新增键里 575 个「没翻」**（hi 52 / de 63 / fr 63 / pt 62 / it 61 /
es 59 / bn 53 / ja 53 / ko 53 / ru 53 / zh-CN 3）。我据此准备派三个翻译会话去做这 575 个键，
并在给别的会话的说明里引用了这个数。

同一次运行里，**仓自己的裁判 `passthroughFindings()` 对这 3724 个键报 0**。
两个数相差 575，而**门禁用的是后者**。

## 根因

`website/scripts/lib/passthrough-checks.mjs` 判定「没翻」的方式不是「值等于英文」，
而是两条**带豁免阈值**的启发式：

1. `untranslated-script`：`strippedProse()` 先剥掉 `{{占位符}}`、URL、
   `*.json`/`*.tsx` 这类路径、代码片段、数字、以及 dnt 词表（`src/i18n/glossary.json` 62 条），
   然后要求**剩余字母数 ≥ `MIN_LETTERS=4`** 且 **token 数 ≥ `MIN_TOKENS=2`**，
   才要求「至少含一个本地文字字符」。
2. `untranslated-english`：要求 **≥ `MIN_WORDS=6` 个词**才开始判「读起来像英文」，
   且需要「仅英文虚词」命中 ≥ `MIN_EN_HITS=2` 并且 ≥ `EN_MARGIN=3` × 「仅目标语虚词」。

短标签根本走不到判据里。被判的 575 个值长这样：

```
apps.aiStudio.project_label = "Project"     apps.aiStudio.diff_title   = "Diff"
apps.aiStudio.design_version = "Design"     apps.aiStudio.commit       = "Commit"
apps.aiStudio.tools_title    = "Tools"      apps.aiStudio.tool_docs    = "Docs"
apps.aiStudio.run_version    = "Run"        apps.aiStudio.node_edges   = "Edges"
```

这些是**本目录刻意保留拉丁的技术术语**（hi 的 174 条 aiStudio 值里有 52 条如此，
`Diff` / `Commit` / `Version` / `Releases` 等）。我造的尺子把「约定不翻」全判成「漏翻」。

`strippedProse` 那一层剥离是决定性的：我自己写复刻版时只剥了 `{{}}`、URL、路径，
于是把 151 个必翻键**全部**误判成「无天城文」——因为 `Step {{n}} / {{total}}`
剥完只剩 4 个字母，我的版本没剥够就到阈值下了。**判据不在我手里，复刻判据就是复刻缺陷。**

## 更坏的一层：我当时引用的数本身也是坏工具算的

我一度对外说的是「543」，不是 575。差 32 的原因见
[[nested-flat-object-entries-collapsed-keys]]——我那两个脚本的 `flat()` 写错了，
`Object.entries()` 套在已经返回键值对数组的递归调用上，枚举的是**数组下标**，
15061 个叶子塌成 6659 个键。**同一批数据，同一个我，两个都错的数，成因还不一样。**

## 修法

1. **判「翻没翻」只用仓里那一个裁判**：
   `import { passthroughChecks, passthroughFindings } from 'website/scripts/lib/passthrough-checks.mjs'`，
   dnt 从 `website/src/i18n/glossary.json` 的 `dnt` 数组取（62 条）。
   要离线跑就 `I18N_GATE=1 I18N_BASE_REF=HEAD node scripts/i18n-check.mjs`，
   看 `[changed-passthrough]` / `[changed-values]` 两行（diff 上零容忍）。
2. 不要用「值 == 英文」当缺陷判据，也不写进派工说明。
3. 复刻判据前先读实现，别照常识写。`MIN_*` 那几个常量就是判据本身。

## 怎么避免

- **要用一个数做决定（尤其是拿去派活），先问「仓里有没有这个域的权威判据」**。
  i18n 有，而且是硬门禁 + 单测，就在 `scripts/lib/`。我绕开它自造了一个，
  还以为自己在「交叉验证」。
- **自造门的通过率本身零信息量**（见 [[quality-gate-needs-calibration-baseline]]）。
  这里反过来同样成立：自造门的**失败率**也零信息量，575 这个数字看着像工作量，
  实际是「我的尺子和仓的尺子有多少个阈值不一致」。
- 派工说明里的数字**必须附来源命令**（见 [[no-unmeasured-numbers-in-dispatch]]）。
  写「裁判报 0，我的土尺子报 575，采信裁判」和写「还差 575」，
  后者会让三个会话白干一轮。
- 如果真要判「这个术语该不该保留拉丁」，那是**owner 的裁决**，不是门的输出。
  hi 有 46 个术语从来没翻过，我没有权限替它发明拼法，只能列清单上报。
