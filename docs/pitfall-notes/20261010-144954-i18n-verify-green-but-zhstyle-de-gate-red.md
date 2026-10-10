# `verify` OK 的 zh-CN 分片，合进目录后被 `zhStyle` 的「的」判据打回

日期：2026-10-10 14:49:54（ACP-2213 zh-CN manifest 7 键返修）

## 现象

`apps.aiStudio.manifest` 的 zh-CN 7 键，交付前自检全绿：

```
[zh-CN] 1 shard(s), 7 key(s), plurals [other], 0 finding(s), 28.6% identical to English
OK: zh-CN is ready to merge.
```

合并进 `website/src/i18n/locales/zh-CN.json` 后，仓里的风格门红了：

```
FAIL zh-CN tone (style/zh-CN.md §3) > does not stack more than two 的 in one value
apps.aiStudio.manifest.description
```

即 `zhStyle.test.ts` 的 `does not stack more than two 的 in one value`。同一条值我扫过引号、全角字母、首尾空格、
双空格、括号配对 —— 唯独 `的` 的个数不在任何一道我能跑的判据里。

## 根因

三件事叠在一起，每一件单独看都不致命：

1. **`i18n-translate.mjs verify` 的契约是「shard 的形式」，不是「中文读起来像中文」。**
   它查键集、占位符、DNT、空白括号、`passthroughRatio`；`*Style.test.ts` 那批
   （`的` 连用、`您`、`这将`、助词叠用、直角引号、混用括号）只在 vitest 里，
   `verify` 一条都不复算。所以「ready to merge」的字面意思是 *格式没毛病*，
   不是 *风格能过* —— 见 `20261009-235900-i18n-check-prints-no-catalogparity-row.md`
   里同样口径的缺口。
2. **分号救不了同一个小句内的堆叠。** 判据按 `[。；！？\n]` 切句，**逐句**数 `的`，
   `>=3` 即违规。我原句 `……就能新建项目；每个项目都有自己的页面，一侧是接……`
   看着像被 `；` 断开了，其实那 6 个 `的` 全落在 `；` **之后**的同一个逗号长句里
   （逗号不是切分符）。能救的只有让堆叠**跨过**切分符。
3. **验证改法时，跑门的那棵树里根本没有这条值。** HEAD 里没有这 7 个键（合并在
   master 的工作区里，未提交），直接 `npx vitest run src/i18n/style/zhStyle.test.ts`
   会 21 passed —— 那是**键不存在**的绿，不是**新值合格**的绿。
   在共享树里跑还会读到 master 会话刚写进去的旧值，报的又是旧的账。

## 修法

改值时按小句预算 `的`（每句 ≤2），手段是定语前置和直接省 `的`，不是加标点：

```
编码工作室工作台：项目列表里新建项目只需名称和描述。每个项目有自己的页面，
一侧是 AI 对话栏，直连你真实的 Kiro Crew 会话。旁边是按页签组织的工作区
（预置需求、工作流、UI 规格文档、待提交变更差异、提交历史），再加一个工具边栏负责打开这些内容。
```

小句 1/2/3/4 的 `的` = 0/2/1/0。括号里那串并列原本各带一个 `的`
（预置的、待提交的），去掉后既省额度也更像产品页。

要证明它真能过，得**造一棵注入过的树**，并且带对照组：

```bash
T=/tmp/zhfix-$(date +%Y%m%d-%H%M%S); mkdir -p $T
git -C <repo> archive HEAD website | tar -x -C $T          # 干净树，不碰共享工作区
ln -s <主仓>/website/node_modules $T/website/node_modules  # 仓里 node_modules 本来就是软链
# 用 python 把新值塞进 $T/website/src/i18n/locales/zh-CN.json，旧值另存一份
cd $T/website && I18N_GATE=1 npx vitest run src/i18n/style/zhStyle.test.ts
```

- **负对照**（旧值注入）→ `1 failed | 20 passed`，红的正是那条 `的` 判据：
  证明这颗门看得见这条键、判据真的在跑
- **正对照**（新值注入）→ `21 passed`

只有正对照没有负对照，等于拿「测试没看见这条键」当「测试通过」。

## 怎么避免

- zh 分片交付前，除了 `verify`，**自己复算 `zhStyle` 的 tone 四条**
  （`您` / `这将` / `的的|了了|可以能|将会将` / 逐小句 `的>=3`），一行 python 的事：

  ```bash
  python3 - <<'PY'
  import json, re
  d = json.load(open("/home/jereh/scratch/acp2213/zhmf/zh-CN/shard-01.json"), encoding="utf-8")
  for k, v in d.items():
      for c in re.split(r"[。；！？\n]", v):
          if len(re.findall("的", c)) >= 3:
              print("DE-STACK", k, c)
      for bad in ("您", "这将"):
          if bad in v: print(bad, k)
      if re.search(r"的的|了了|可以能|将会将", v): print("PARTICLE", k)
  PY
  ```
- 汇报「我跑过门了」时，必须能说出**在哪棵树、哪个提交、注入的是哪一版值**；
  树里没有这条键的 green 一律不算证据
- `cd` 之后下一条 Bash 调用目录会重置回项目根，`node scripts/…` 会解析成
  `<repo>/scripts/…` 直接 `MODULE_NOT_FOUND`。跨目录跑要么写进同一条命令，要么给绝对路径
