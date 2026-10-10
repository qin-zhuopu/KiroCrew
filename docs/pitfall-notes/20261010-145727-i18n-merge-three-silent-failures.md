# 翻译合并流水线的三个静默失败：假天城文绿灯入库、42 键改动变 9000 行 diff、合并值比交付值旧

时间：2026-10-10 14:57
任务：ACP-2213 / ACP-2214，给 aiStudio 补 11 语种共 42 键
相关：
[20261010-143849-i18n-verify-green-merge-skips-untranslated-keys.md](20261010-143849-i18n-verify-green-merge-skips-untranslated-keys.md)（同批，那条讲 insert-only 静默 skip）
[20261010-144954-i18n-verify-green-but-zhstyle-de-gate-red.md](20261010-144954-i18n-verify-green-but-zhstyle-de-gate-red.md)（同批，那条讲 verify 绿但 zhStyle 红）

三个坑共同点：**门禁全绿，东西是坏的**。报错一个都没有，所以只能靠事先知道要查什么。

---

## 坑一：假天城文能过官方 `verify`，0 finding 入库——而且仓里没有任何门查拼写

### 现象

hi 语向交付 7 键，跑官方判据：

```
[hi] 1 shard(s), 7 key(s), plurals [one other], 0 finding(s), 28.6% identical to English
OK: hi is ready to merge.
VERIFY_EXIT=0
```

我按这个绿合并进了 `website/src/i18n/locales/hi.json`。之后拿**上个会话我自己临时写的** scratch 脚本扫同一批文件：

```
[hi] 7 value(s) across 1 file(s)
  character coverage: OK (no native script invented)
  word list: 5/7 value(s) contain an out-of-vocab word (71.4%)
             | calibrated false-positive rate on correct shipped copy is 13.1% -> ABOVE expectations
  FAIL — far more unseen words than legitimate copy produces.
         Check that you copied approved wording instead of retyping.
    apps.aiStudio.manifest.description: ['दस्तवजें', 'इतहास', 'आवश्यकतआएँ', ...]
```

`दस्तवजें`（批准写法 `दस्तावेज़`）、`इतहास`（批准 `इतिहास`）都是**照屏幕重打字**产出的假词：
元音标记换了个码位，肉眼在终端里看着几乎一样，`character coverage` 也判 OK（因为它只查
「是不是天城文区段」，不查「是不是一个真实的印地语词」）。

### 根因（三层，每一层都各让一步）

1. `website/scripts/i18n-translate.mjs` 的 `checkValue` 有 14 条判据，全是**结构**判据：
   占位符集合、换行数、DNT 术语在不在、首尾空白、双空格、全角拉丁、括号配平、引号种类、
   复数类别、与英文相同比例。**没有一条查词形**。假词在结构上无可挑剔。
2. 仓里 `src/i18n/style/hiStyle.test.ts` 只有两个 `it`：句末用 `।` 不用 `.`、不用敬称 `आप`。
   **拼写不在其列。**
3. 真正拦得住的是 `check-vocab.py`（拿 37,000+ 已批准音节/词做词表，另配 13.1% 误报率对照），
   而它在 `/home/jereh/scratch/` 下，**不是仓里的门，不在 CI，不在 `npm run i18n:check` 的 19 项里**。

所以：**一个假天城文译文可以一路绿灯进 main，没有任何仓内检查会红。**
`check-vocab.py` 只覆盖 `bn|hi|km|ko|my|ru|th`，且是我个人 scratch 里的脚本。

### 修法

- 已经合并的坏值：`git checkout <基线> -- website/src/i18n/locales/hi.json`（那次合并只含这 7 个键，整文件回退最干净）
- 把「非拉丁语向必须跑 `check-vocab.py` 并且 FAIL 不放行」写进 worker 任务书和**我自己的合并前清单**——
  worker 自报 verify 绿不构成放行条件
- 长期：词表门应该进仓、进 `i18n:check`。它需要一份「已批准词表」做基准，
  可以直接从各语种 catalog 现有值生成（`check-vocab.py` 就是这么来的），没有理由只活在 scratch 里

### 怎么避免

非拉丁语向（hi/bn/ja/ko/ru/th/km/my）合并前，**除了** `verify` 之外必须过：

```bash
python3 <scratch>/check-vocab.py <locale> <shard 文件或目录>   # 词形
```

`verify` 打印 `0 finding(s)` 只说明结构没坏。**判「能不能合」要两道都绿。**
拉丁语向（de/es/fr/it/pt）没有这个问题——重打拉丁字母产出的还是真词。

---

## 坑二：`merge` 会把整个 catalog 的键排序，42 键改动炸成 9000 行 diff

### 现象

只改 42 个键的值，`git diff --stat` 却是：

```
website/src/i18n/locales/ru.json | 18639 +++++++++++++++-------------
 1 file changed, 9324 insertions(+), 9315 deletions(-)
```

11 个语种每个文件都有 8400–9000 行「改动」，`git diff --ignore-all-space` **反而更多**
（15745 行）——所以不是行尾/空白问题，是**键的顺序变了**。

### 根因

`cmdMerge` 落盘那一行：

```js
fs.writeFileSync(target, `${JSON.stringify(sortDeep(catalog), null, 2)}\n`)
//                                  ^^^^^^^ 递归排序全部键
```

而仓里的 catalog 是**自定义顺序**：每个 app 的 `manifest` 排在该 app 段最前
（`apps.awsControl` 就是 `manifest, console, page, rail, overview`），其余按功能分组。
排序把这些惯例全打乱。

对照实验（同一个文件，只做重排、不改任何值）：

```bash
diff <(git show <基线>:website/src/i18n/locales/ru.json) \
     <(git show <基线>:website/src/i18n/locales/ru.json | python3 -c \
        "import sys,json;print(json.dumps(json.load(sys.stdin),ensure_ascii=False,indent=2,sort_keys=True))") \
  | grep -c "^[<>]"      # → 9048
```

也就是说 9048 / 9324 行纯粹是排序造成的，真实改动只有 42 个键。
这种 diff 人评审不了，也违反「一个逻辑改动一个提交」。

### 修法

不要手工去改 `sortDeep`（那是门禁脚本，工单明令禁碰）。做法是**用基线的键序重建**：
把合并产出的值另存一份，然后递归按基线的键序走一遍、同名取合并后的值、
基线里没有的新键按各 app 已有惯例插回原位（`manifest` 插到 `apps.<app>` 段最前），
落盘用 `json.dumps(..., ensure_ascii=False, indent=2)`（仓里就是这个格式，`indent=2`、键不排序）。

**必须自证只换了顺序没换内容**：逐键比对「重建后 vs 合并后」，要求 0 差异：

```python
d = [k for k in set(a) | set(b) if a.get(k) != b.get(k)]   # a=合并后, b=重建后 → 必须为空
```

效果：`--stat` 从 ~9000 行/文件 降到 79 行/文件，全批 402 增 285 删。

### 怎么避免

`merge` 之后第一件事跑 `git diff --stat`。**行数远超改动键数 × 2 就说明它动了顺序**，
当场重建，别留着到评审阶段才发现。

---

## 坑三：我合并的值比 worker 最终交付的值旧，且无人报错

### 现象

我 14:38 合并了 ko 的 42 键。worker 14:44 回报时指出：

> 有会话在 14:42:59 把我的 42 键合进了 `ko.json`，**41/42 与我最终值逐字节相同**，
> 差一条是我 14:43:15 的最后一改——catalog 里 `chat_placeholder` 仍是
> `원하는 변경 사항을 설명해 보세요…`，我 shard 里是 `원하는 변경 사항을 설명하세요…`

`verify` 两边都绿（两个写法都合风格指南），所以**没有任何东西会红**。
差别只有一个：一个照仓里两条已批准 `Describe what you want…` 的批准措辞，一个没有。

### 根因

并行流水线里 **交付目录是活的**。我读 shard 的时候 worker 还在改它。
`verify` 查的是「这批值合不合格」，不查「仓里的值是不是这批值的最新副本」，
所以过期合并完全静默。

同一个原因还造成过一次反向误会：我探盘探在 worker 写入**之前**，
于是「文件不存在」和「文件一直在」两边都真（见坑一引用的那两篇）。

### 修法

合并后**逐键回读**，把仓里 catalog 和交付 shard 对比，要求 0 不一致：

```python
bad = [k for k in shard if catalog.get(k) != shard[k]]   # 必须为空
```

不一致就先问 worker 是否还在改，确认后重新落那几个键，再跑一遍风格门。

### 怎么避免

合并不是「跑一次 `merge`」，是一个闭环：
**worker 声明完工 → 合并 → 逐键回读比对 → 有差异就问 → 重落 → 重跑门**。
worker 那句「我交付完了」之后的任何一次 `mtime` 变化都要重新走一遍。
收 worker 交付时固定要 `绝对路径 + mtime + md5 + 当次 date`，
就是为了让我能发现「我合的那一版不是它最新那一版」。
