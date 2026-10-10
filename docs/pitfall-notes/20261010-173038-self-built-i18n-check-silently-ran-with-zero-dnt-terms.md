# 自己复刻 i18n 校验时，DNT 词表会静默加载 0 条，绿是假的

日期：2026-10-10 17:30:38（ACP-2113 补漏批次，ru 13 键）

## 现象

补漏批次的交付物只是一个扁平 json（`acp2113-gap/<语种>/shard-01.json`），**没有 `en/` 兄弟目录**，
所以仓里的 `node scripts/i18n-translate.mjs verify <baseDir> --locale=ru` 跑不了
（它硬要求 `<baseDir>/en/shard-NN.json` 存在，否则 `exit 2`）。「输入形态不匹配」这件事本身见
[20261010-171814-gap-shards-have-no-en-dir-so-verify-refuses.md](20261010-171814-gap-shards-have-no-en-dir-so-verify-refuses.md)，
本篇只讲照它给的 `import` 路线做下去之后踩到的更深一层的问题。

于是我 import 仓里的真判据 `checkValue()` 自己组一个校验。第一次直接炸：

```
TypeError: dntTerms is not a function
```

第二次把路径猜成 `website/src/glossary.json`，又炸：

```
ENOENT: no such file or directory, open '.../website/src/glossary.json'
```

坑在于**接下来最顺手的两步修法都会把这道门变成空门**：

- `dntTerms` 不是 export（`scripts/i18n-translate.mjs` 里它是模块内私有函数，
  文件头 `export` 的那批是 `checkValue` / `placeholders` / `mergeCatalog` 等，里面没有它），
  于是容易顺手写成 `dnt: []`
- 路径猜不到就顺手 `?? []`

而 `checkValue` 里 DNT 那条判据长这样：**先要求英文原文命中该术语，才去查译文里有没有**。
传 `dnt: []` 等于循环零次，任何把 `Kiro` / `Markdown` 音译掉的译文都能拿
`0 finding(s)` —— 和真正的通过长得一模一样，且**这条判据本来就是 `verify` 唯一的硬判据之一**。

## 根因

`verify` 的三样输入（`dnt`、`pluralCategories`、`pluralBases`）都在 `cmdVerify` 里现取，
其中两样取不到时是**静默降级**，不是报错：

- `dntTerms()`：`readOptional(GLOSSARY_FILE, …)` 拿不到文件时返回 `''`，函数返回 `[]`；
  真实路径是 `src/i18n/glossary.json`（`GLOSSARY_FILE = path.join(SRC,'glossary.json')`，
  而 `SRC = ROOT/src/i18n`）——**不是** `src/glossary.json`
- `pluralRegistry()`：`pluralKeys.json` 不在就返回 `[]`，而 `checkValue` 里那段
  `impossible-plural` 判据的条件是 `if (categories && pluralBases)`
  且 `pluralBases.includes(base)`，空表 = 永不触发

也就是说：**复刻出的校验和 CI 那道门共用同一段判据代码，但喂进去的数据可以是空的，
而输出文案一模一样**。

## 修法

复刻时必须自己把三样数据喂真，并把「加载到多少条」打印出来当自证：

```js
const W = '<repo>/website'
const { checkValue } = await import(`${W}/scripts/i18n-translate.mjs`)
const dnt = JSON.parse(fs.readFileSync(`${W}/src/i18n/glossary.json`, 'utf-8')).dnt ?? []
const pluralBases = JSON.parse(fs.readFileSync(`${W}/src/i18n/pluralKeys.json`, 'utf-8'))
const categories = new Intl.PluralRules('ru').resolvedOptions().pluralCategories
// …逐键 checkValue({ key, en, tr, dnt, categories, pluralBases, locale })
console.log(`dnt=${dnt.length} pluralBases=${pluralBases.length} cats=[${categories}]`)
```

`pluralBases` 也别传 `[]`——本篇一开头为了跑通就是这么写的，那等于把 `impossible-plural`
那条判据也一起空掉（本批 13 键一条都不是计数键，结果上没漏，但**是运气不是判据在工作**）。

实测跑通：`dnt terms loaded: 62; checkValue over 13 keys: 0 finding(s)`。
**`62` 那一行才是这道复刻校验有效的唯一证据**，`0 finding(s)` 单独出现不说明任何事。

## 怎么避免

- 复刻别人家的门，先把它的**输入**逐项打印（词表条数、类别列表、基线文件是否存在），
  再谈输出。输出为 0 而输入为空 = 空门，比没有门更糟（它给你绿）
- 键集另做一道纯字符串核对：`sorted(mine) == sorted(spec)`，以及
  `{{...}}` 占位符排序后逐键相等（本批 3 个键含 `{{n}}` / `{{time}}`）
- 顺带一条：补漏批次里 `pluralKeys.json` 一条都不命中是**正常**的
  （这批 13 个键的英文没有一条是计数键），别为了"让某条判据看起来有用"去给它凑复数形式——
  ru 有 4 类（one/few/many/other），给非复数键造 `_few` 反而会被 `catalogParity.test.ts` 拒
- 数格问题：`{{n}}` 后面的名词，仓里现成写法有两种——复数名词（`После {{n}} исправлений`，
  三格复数）和 `X: {{n}}` 计数形（`элементов: {{n}}`，仿 `designTweak.comments.element_count`）。
  本批 `advisory_count` 会被渲染成 ` (…) ` 内联在门名后面，取后者；
  两种都不需要 `_one/_few/_many` 拆键，因为 `n` 是运行时数字不是 i18next 复数键
