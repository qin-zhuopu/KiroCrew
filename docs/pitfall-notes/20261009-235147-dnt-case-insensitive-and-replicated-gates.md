# 自己复刻仓库闸门 = 假绿；自己扫英文残留 = 假红

时间：2026-10-09 23:51
任务：ACP-2113，给 10 个语向补齐 233 个 `apps.aiStudio.*` 缺失 key
相关：`docs/pitfall-notes/20261009-235900-i18n-check-prints-no-catalogparity-row.md`（同一批活的另一篇）

这一篇记两个**方向相反的错**：一个把绿的判成红，一个把红的判成绿。两个都不是译文的错，是**验证工具**的错，所以都值得单独记。

## 坑一：DNT 术语是大小写不敏感剥离的，按小写搜术语表会造出假红

### 现象

给 ja/ko/ru/bn 补译文时，我自己写的预扫脚本（`prescan-latin.py`，按「值里有连续 2 个以上拉丁词」粗筛）报出：

```
ja: 1 value(s) carry 2+ consecutive Latin words
    demo_product_dev   ['git tag'] | git tag
```

ko / ru 各 1 处同一条，bn 另有一条 `"Trust session"`。按 `untranslated-script` 的公开阈值手算：
`MIN_LETTERS = 4`（`git tag` 有 6 个字母）、`MIN_TOKENS = 2`（两个词）、目标文字 0 ——
**四条全满足，应该触发**。而 `untranslated-script` 喂给 CI 的 `[changed-passthrough]` 是
zero tolerance，也就是说这一条能把整个 PR 判死。

于是我准备给四个语向的翻译会话发指令，把 `git tag` 改成 `git タグ` 之类的混写。

### 根因

`website/scripts/lib/passthrough-checks.mjs` 判定前先剥 DNT 术语，而那个正则是：

```js
new RegExp(`(?<![\\p{L}\\p{N}])(?:${terms.join('|')})(?![\\p{L}\\p{N}])`, 'giu')
//                                                                 ↑ i 标志
```

**大小写不敏感。** `src/i18n/glossary.json` 的 61 个术语里写的是 `Git`（同表还有 `GitHub`、
`GitLab`），所以 `git` 会被剥掉。把中间量打出来就一清二楚：

```
"git tag" -> stripped "tag"  letters=3 (<4)  tokens=1 (<2)  FIRES false
"Demo"    -> stripped "Demo" letters=4        tokens=1      FIRES false   ← 单词条外
"Deploy log" -> stripped "Deploy log" letters=9 tokens=2    FIRES true    ← 真会触发
```

我先前判定「`git` 不在术语表里」用的是 `dnt.some(t => t === 'git')`，**大小写敏感**，
`Git` 当然不命中 —— 假红就是这么造出来的。

还有一条独立的证据，比正则推导更硬：**zh-CN 的已批准译文 `apps.aiStudio.demo_product_dev`
本身就是 `git tag`**。仓库早就收过这个值。

顺带：一个翻译会话自查时也报了 4 处同类残留，根因一模一样 —— 它的脚本没剥 DNT 术语。
我自己那条 `"Trust session"` 虚警同理（而且那串英文是源文案自己的毛病，
`src/ai-studio/components/ChatPanel.tsx` 里按钮名与两个候选 key 都不一致，不是译文问题）。

### 修法

不改译文。改用仓库自己的模块跑全量，而不是自己定阈值猜：

```js
import { passthroughChecks } from 'website/scripts/lib/passthrough-checks.mjs'
const checks = passthroughChecks(glossary.dnt)   // 参数是术语表，模块自己不做文件 IO
checks.filter(c => c.violates(value, lang, enValue)).map(c => c.id)
```

2097 条新值跑完，命中 **0**。

## 坑二：复刻仓库的判定逻辑 = 造一个自己看不见的假绿

### 现象

一个审计会话报告：`odd-quote-count` 在 ko 上 **41 → 70**、de 上 **35 → 61**，
而天花板是 **27**，也就是说我的改动会**破顶**，必须改 145 个 key 的引号。

我自己直接 import 仓库 `CHECKS` 跑出的却是另一套数：

```
ok   odd-quote-count        total=   0 /  27
ok   unbalanced-delimiter   total= 120 / 168   bn=10 de=10 en=10 ... 每语种整 10
ok   edge-whitespace        total=  15 /  15   ← 顶格
ok   doubled-space          total=  10 /  10   ← 顶格
```

**两个数不可能都对**，而且相差 41 倍。

### 根因

`odd-quote-count` 检测的是「成对引号数量不等」，见
`website/scripts/lib/qa-checks.mjs` 的 `odd-quote-count` 那条 check，它比较的是**该语向自己的**开/闭引号字符
（de 是 `„` / `“`）。若某会话在计数前做了 `norm()` —— 把弯引号替换成直引号、
把连续空白压成单空格 —— 开闭引号就被抹平成同一种字符，**永不相等失败**，
violation 计数直接归零（或反向虚增，取决于替换方向）。

`website/src/i18n/qa.test.ts` 的 `findViolations` **没有任何归一化步骤**：

```ts
for (const [key, value] of Object.entries(catalog)) {
  if (check.violates(value, lang)) out.push(site(lang, key))   // 原始值，直接进
}
```

所以任何「先规范一下再数」的复刻，量的都不是同一个东西。ko 那组 41/70 无法复核，
且逻辑上讲不通：若基线真有 41 条，仓库主干上就该是红的 —— 它不是。

### 修法

两条纪律，都要做，缺一不可：

1. **能 import 就绝不复刻。** 把仓库的模块直接 `import` 进来：
   `scripts/lib/qa-checks.mjs` 的 `CHECKS` / `flatten`、`scripts/lib/passthrough-checks.mjs`
   的 `passthroughChecks`、`scripts/lib/render-scan.mjs` 的 `dntViolations`。
   只有测试文件里内联的那些正则（各 `*Style.test.ts`）才不得不照抄。
2. **每次跑之前先做负控（自伤自检）。** 造几条**故意违规**的值喂进去，断言计数必须上涨：

```
NEG odd-quote de „abc    -> true   (expect true)
NEG odd-quote de „abc“   -> false  (expect false)
NEG odd-quote ko “abc    -> true   (expect true)
NEG edge     ' x '       -> true   (expect true)
NEG unbal    a[b         -> true   (expect true)
```

跑不出红的判定器，等于没有判定器。**「全绿」这个结论，在负控通过之前一律不作数。**

## 怎么避免

- **判「有没有英文残留」不要自定阈值。** 自定阈值必然和仓库的判定不一致，
  而仓库的判定带一个不显眼的预处理步骤（剥 DNT、剥 URL/路径/占位符/代码/数字），
  漏掉它就必然误判。用 `passthroughChecks(glossary.dnt)`。
- **在术语表里搜一个词，要用大小写不敏感搜。** DNT 表里的 `Git` / `GitHub` / `Asana`
  首字母大写，剥的是任意大小写。
- **单条值不构成 passthrough**：`MIN_TOKENS = 2` 是给 `Commit` / `Build` / `Demo`
  这类**单词标签**留的活路。别看到 `Commit` 没翻就判 untranslated —— 短标签要看
  它是不是 DNT，或是不是本来就只有一个词。
- **子会话报上来的数字，先问「你的判定器怎么来的」。** 复刻的一律要求：import 仓库模块
  + 附负控输出。这次两份互相矛盾的审计里，只有附了负控的那份结论能用。
- **顶格的两条要单独盯**：`edge-whitespace` 15/15、`doubled-space` 10/10，
  天花板已经吃满，我新增的任何一条值命中就是立刻破顶。批量补译之前必须专门验这两个。
- 顺带一条：`git tag` / `Commit` / `Design` / `Pause` 这类词**字面保留是本仓既有惯例**
  （de 的 `apps.specBuilder.components.specDetail.tab_design` = `Design`，
  it 的 `settings.tabs.releases.label` = `Release`，zh-CN 的 `demo_product_dev` = `git tag`）。
  别为了「看着像翻译过」去硬翻开发术语，那会造出一个和 zh-CN 都不一致的第三种写法。
