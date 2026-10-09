# `i18n:check` 里没有 `catalogParity` 这一行，且「英文占位」的退路会被自己的门禁判红

补 ACP-2113（AI Studio 新增文案只有中英，其它语种缺 233 键 × 10 语种）时踩的两个坑，
外加两条「不报错但一改就炸」的隐性约束。前两个坑都不是从报错看出来的：一个是
「找不到报错」，一个是「按文档做反而更糟」。

## 现象一：照指令去找 `catalogParity` 的缺失数，输出里根本没有这个词

任务书让「跑 `npm run i18n:check`，记下 catalogParity 每个语种缺几个键」。跑完 826 行输出里
`grep catalogParity` 命中 0 次。差点对整条判据无从下手。

## 根因

`catalogParity` 不是 `i18n:check` 的检查项，它是**前端测试文件**
`website/src/i18n/catalogParity.test.ts`（vitest）。`i18n:check` 是
`scripts/i18n-check.mjs` 串的 11 个脚本（key-refs / source-strings / pseudolocale /
dnt / unit-literals / …），**不含键覆盖度**。两处都有人叫它 catalogParity：
`check-i18n-keys.mjs` 的注释里提到 `catalogParity` 只比对**合并后**的目录，
但它自己一行 parity 输出都不打。

于是出现了这个形状：判据写在测试里，工具链里没有对应数字，而任务书又禁止跑测试。

## 修法

按 `catalogParity.test.ts` 的算法**照抄一份只读度量**（flatten → 用 `pluralKeys.json`
剥掉注册过的复数形式 → 比对键集 → 另外量 stray / 复数缺形 / 空值 / 占位符），
几百行脚本，跑 1 秒，输出每个语种缺几个键。数字与测试完全同构，改前 233、改后 0，
和测试的断言方向一致。

要点：**判据找不到对应输出时，先确认它在哪一层**（`scripts/` 的门禁 vs `src/**.test.ts`
的测试 vs CI 的 yml），不要拿一个语义相近的检查项顶替——这次最容易被顶替成
`[key-refs]`（18026 references resolve · 0 dangling），但那查的是「代码里引用的键存不存在」，
方向相反，语种缺键它永远绿。

## 现象二：按「没有翻译脚本就按英文原文填」做，反而新增 1041 条零容忍 finding

任务书第 3 步给的退路是：`scripts/` 下没有同步翻译的脚本就按英文原文填，PR 里写
「机器未翻，英文占位」。

`scripts/i18n-translate.mjs` 确实存在（`plan` / `emit` / `verify` / `merge` 四个子命令），
但它**不调模型**，只是渲染 prompt + 校验答案——发送是人/agent 的活。所以「有没有脚本」
这个问题本身就是二义的：脚本在，翻译能力不在。

真要按英文填会怎样？用仓库自己的 `scripts/lib/passthrough-checks.mjs` 实测：

| 语种 | 用英文占位会被判红的键 |
|---|---|
| bn / hi / ja / ko / ru / zh-CN | 各 146 |
| de / es / fr / it / pt | 各 33 |

合计 **1041**。而 `changed-passthrough` 这一项是 **diff 范围内零容忍**（改前已经红
216 条），英文占位等于把缺口从 216 顶到 1257，PR 直接不可合并。

判红机制（值得记）：
- 非拉丁文种（bn/hi/ja/ko/ru/zh-CN）走 `untranslated-script`：去噪后 **≥4 个字母 且
  ≥2 个词 且 目标文字 0 个**就判红。所以 `"App URL"` 这种 6 字母 2 词的短值，照抄一次
  就红一条（ja 实战中真踩到，`demo_product_deploy`）。
- 拉丁文种走 `untranslated-english`：与英文去噪后逐字相同，或英文虚词 ≥ 本族虚词 3 倍。

## 现象三：`i18n:check` 全绿，`frontend-test` 仍可能因新值变红

`i18n:check` 的 11 个脚本里没有**每语种风格规则**。风格规则在
`website/src/i18n/style/*Style.test.ts`（vitest，11 个文件共 1474 行：ko 382、ja 212、
zh-CN 193、fr 163、bn 128、ru 81、es 70、hi 64、de 61、it 61、pt 59），CI 由
`frontend-test` job 跑（见 `docs/ci/i18n-gates.md` 的 job 表）。

这些是对**整份目录**的断言，例如 ru：带西里尔文的值不得用直引号包（上限 20）、
出现 `Вы`（大写尊称）即 `toEqual([])` 零容忍。也就是说：**新加 2330 个值可能踩到它们，
而本地 `i18n:check` 一声不响**。同理 `qa.test.ts` 的上限（`edge-whitespace` 15/15、
`doubled-space` 10/10 已顶格，`fullwidth-alphanumeric` 上限 0）也是测试侧的，
门禁脚本不看。

实测的等价做法（不跑 vitest）：把测试里的机械判据抽出来单独跑一遍候选值。
`qa.test.ts` 的六个上限可直接复用 `scripts/lib/qa-checks.mjs` 的 `CHECKS`（上限数字需手抄，
所以仓里的测试仍是权威）；`catalogParity.test.ts` 的键集判据同理可复刻。

## 顺带挖到的两条隐性约束（不报错，但一改就炸）

1. **语种目录的键序必须是 en 的子序列**。`i18n-translate.mjs merge` 走
   `sortDeep`（全量深排序），而仓里现存的目录**并不是**排好序的（en 自己就有
   3224 个键不在排序位）。照 merge 的写法落盘，一个 233 键的补丁会变成
   7800 行的重排大 diff。正确做法：只在 `apps.aiStudio` 子树内按 en 的键序插入，
   子树外**一个字节都不动**。实测 diff = 242 行 / 语种（233 新键 + 括号闭合行）。
2. **序列化必须 `indent=2` + `ensure_ascii=False` + 结尾换行**。所有目录在
   `json.dumps(..., indent=2, ensure_ascii=False)` 下是**逐字节**可回写的；
   用默认 `ensure_ascii=True` 会把整份非拉丁目录写成 `\uXXXX`。落盘前先断言
   回写 == 原文件，再动手。

## 怎么避免

- 别人给你的判据（尤其点名一个测试文件名的），先在**测试目录**里 grep 那个名字，
  别在 `scripts/` 里找；确认它属于哪一层，再决定是跑测试还是复刻度量。
- 涉及 i18n 目录的写入：**先跑一次「回写 == 原文件」的字节断言**，再做插入；
  不要用 `i18n-translate.mjs merge` 往非排序的目录上写（它会把整份文件重排）。
- 任何「先填英文占位，以后再翻」的想法，在**这个仓**里等于加债：
  `changed-passthrough` 是零容忍的 diff 门禁。真没翻译能力时，正确做法是
  **让 agent 按 `emit` 渲染出来的 prompt 翻**（`emit` 已经把该语种的风格指南、
  DNT 表、12 条已批准示例都拼进去了），而不是退回英文。
