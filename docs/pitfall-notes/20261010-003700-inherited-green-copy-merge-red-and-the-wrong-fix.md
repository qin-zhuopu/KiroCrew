# 20261010-003700 · 「i18n 门禁 main 上本来就红」是假的，而开出的修法是反的

## 现象

审计长报告写着：`destructiveConfirm` 在 `origin/main` 上本来就红，本分支相对 main
「丢了 9 个 confirm 键的豁免」，后果是**合主干时会复活成红**，修法是「合并时把那 22 行
豁免一起带回来」。听起来严谨（连行号、键名都有），照做就要动
`destructiveConfirm.test.ts`。

## 根因

三点全错，而且错在同一处：**把「本分支的 en.json 没有这些键」当成了「测试丢了这些键的豁免」**。

1. **main 是绿的**：在**干净的 `origin/main` worktree** 里跑 `npx vitest run src/i18n`，
   45 个文件 733 个测试**一个不红**。那 9 个键的豁免与键本体都由 main 带着，本分支一次
   都没碰过这个测试文件 —— `git diff $(git merge-base HEAD origin/main) HEAD --
   website/src/i18n/destructiveConfirm.test.ts website/src/i18n/style/` 输出**空**。
   没改过的文件在合并时直接取 main 那份，**豁免不可能丢**
2. **本分支根本没有 `apps.aiStudio.*` 这个命名空间**（`git show origin/main:…en.json`
   里 `apps.aiStudio` 命中 0）。main 的测试看不见它，所以 main 绿与本分支红**同时成立**，
   一点不矛盾 —— 不需要「丢了豁免」来解释
3. **照那个修法做会当场把绿的测试改红**。main 新增的那 9 个豁免/钉住的键名，在 main 的
   `en.json ∪ en.manual.json` 里 9/9 都在（4 个只在 `en.manual.json` 里 —— 只查
   `en.json` 会数漏），而**本分支 0/9 有**。同文件自己有一条
   `every listed pin and exemption still exists in English`，把 main 的清单搬进本分支，
   它立刻报「清单点了不存在的键」，一次 9 个。**这个修法造新红，不修老红**

老红是本分支自己的：`apps.aiStudio.req_start_confirm` 插值 `{{n}}`，既没进
`QUOTED_OPERAND_CONFIRM_KEYS` 也没进 `CONFIRM_OPERAND_KEY_EXEMPTIONS`，而 `n` 不在
`EXEMPT_CONFIRM_PLACEHOLDER_NAMES`（那个白名单收的是 `count`/`number`/`lines` 这类
**语义名**，不收单字母）。它由 `485b83842`（ACP-2104）引入，**不是** merge-base 带的。

## 修法

- 判「main 红不红」：用 **main 的测试 + main 的目录**跑，别用本分支的目录（本分支目录
  里多出来的键，main 的测试压根不看）
- 判「是不是我改的」：`git diff <merge-base> HEAD -- <测试文件>`，空就是没改；
  归属看 **merge-base**，不看 HEAD（HEAD 上红 ≠ 这条分支弄红）
- 真修：`{{n}}` 改名 `{{count}}`（进白名单，零豁免成本），或加键豁免并写理由。
  **别**把 `n` 塞进 `EXEMPT_CONFIRM_PLACEHOLDER_NAMES` —— 白名单的意义是「语义名不可能
  被当成句子的一部分」，收一个单字母就把这道闸废了

## 怎么避免

1. **「合并会不会红」这种问题，别推理 —— 拿一次性 worktree 真跑一遍**（这次真正省时间的
   一条）。两个必须守住的条件，我第一遍都没守住，于是报了个假数：
   ```bash
   git worktree add --detach /tmp/x HEAD && cd /tmp/x
   git merge --no-commit --no-ff origin/main     # 冲突留着不解决也行
   ln -s <主仓>/website/node_modules website/node_modules   # 免装依赖
   npx vitest run src/i18n                       # 整目录，不是你觉得相关的那几个文件
   ```
   - **只跑「相关的那几个文件」= 数不到别的文件里的合并后果**。我第一遍只跑了
     `style/` + `destructiveConfirm`，报「只剩 3 条红」，纯属自欺
   - **千万别把本分支的目录文件盖到合并结果上**。我图省事把修好的 `zh-CN.json` 拷过去，
     等于把 main 的 zh 译文全丢了 —— 污染是**双向**的：既造出 5 条假红
     （`catalogParity` 的 zh 4 条 + `…zh-CN wraps every non-exempt operand`，报的 4 个键
     **在 merge-base 里根本不存在**，是 main 新增的键，main 自己带的是弯引号版本，
     我拷过去的那份「缺」它们是正常的，不是我译漏了），**又藏掉 1 条真红**
     （`zhStyle`：拷的那份已经改成弯引号了，于是它绿了）

   四笔都是 `npx vitest run src/i18n` 跑出来的（分母 43/703 与 45/733 的差是 main 多了
   2 个 i18n 测试文件，不是我没跑全）：

   | 跑的是哪棵树 | 结果 |
   |---|---|
   | 干净的 `origin/main` | 45 文件 / 733 测试**全绿** → 报告那句「main 本来就红」是假的 |
   | 本分支（zh 直角引号**没**修） | 43 文件里 7 红 / 703 测试里 17 红 |
   | 本分支（修完之后） | 6 红 / 16 红（只动了 `zhStyle` 那一格） |
   | 合并树（不污染，从 `HEAD` 合） | 45 文件里 8 红 / 733 测试里 18 红 |

   18 − 16 的差额两条，性质完全不同，别一起报成「合并会红」：
   - **`localeFormatting`：唯一真正「只在合并里红」的一条**。main 把 `BASELINE`
     从 25 收到 16，而本分支新增的 4 个裸 `new Date(…).toLocaleString()`
     （`FreezeControl` / `ProjectHistoryView` / `RecentActivityFeed` /
     `demo/DemoWorkspace`）都是 main 上没有的文件，合并树里数到 18 > 16。
     本分支单独跑它**是绿的**，因为分支上那份测试还写着 25 ——
     **门槛被 main 收紧，本地绿不代表合并绿**，这类只能靠合并树跑出来
   - **`zhStyle`：不是合并发作，是我自己的债还在 `HEAD` 上**。那 4 个带「」的键
     （`demo_unknown` / `devDag.*`）main 和 merge-base 里根本不存在，合并取的就是我这份；
     修它的那次改动**还没提交**，所以按 `HEAD` 合出来的树当然还是红的

   而 `आप` 上限从 118 降到 117 没红：合并取的是 main 迁移后的那份目录（113 命中），
   本分支只多 106 个值、一个 `आप` 都没有
2. **别人交来的「合并会红 + 修法」，先跑 `git diff <merge-base> HEAD -- <那个文件>`**。
   一秒证伪「测试文件被改丢了」：没改过的测试文件合并时直接取 main 那份，丢不了
3. 审计给的**修法要反向验一次**：照做之后哪条断言会红？答不上来就别照做（这次是 9 个新红）
4. 邻近事实一条：`ru` 敬称断言用 `/\bВы\b/`，JS 的 `\b` 只认 ASCII 边界，西里尔字母前后
   没有边界 → **永不匹配**。现 ru 目录 348 个值含 `Вы`，命中 0，所以「我的译文没触发它」
   这句话没有信息量。要修得改测试，那是另一个决定
5. 数「动态键覆盖多少键」时正则**别贪吃**，也别把前缀当可达集。我先前报 343，两处虚高：
   正则跨过多个调用点；`apps.aiStudio.${conf.key}` 这种「整段是变量」的模板按前缀展开，
   会把整个命名空间 254 个键全算成「可达」。老实数（`ReleaseControl` 的 `ACTS` 表是
   `as const`，真值就 11 个）：**全仓 10 个动态调用点、能落到的键 39 个，占 8694 个的
   0.45%**。顺带两条：扫源码里的 `` t(`…${…}`) `` 会把**注释里解释「为什么不要这么写」**
   的例句也扫进来（本次 14 个命中里 4 个是注释），别直接当门禁数报；而「动态键都翻齐了」
   这句话覆盖面不到半成，不能当进度用
6. 写这篇笔记时自己又踩一个：正文里带行号的文件引用（形如「某测试文件 冒号 346」）会被
   `scripts/docs-lint.sh` 判 FAIL —— 「cite a symbol name instead」，连「我在转述别人的
   错误引用」都不豁免，转述时把行号去掉。而且它是 **CI 的一个 job**（`fast-gate.yml`），
   却**不在** `local-gate.py` 的门禁行里：本地跑完门禁全绿、推上去 CI 红。
   改动 docs 记得自己跑 `bash scripts/docs-lint.sh`（`python3` 直接跑会报错）
