# `verify` 报 ready to merge，`merge` 却会把 42 条里 35 条静默丢掉

日期：2026-10-10 14:38:49（ACP-2213 ru 语种交付）

## 现象

给 `apps.aiStudio` 补 ru 翻译，42 键两个 shard，自检输出全绿：

```
[ru] 2 shard(s), 42 key(s), plurals [one few many other], 0 finding(s), 4.8% identical to English
OK: ru is ready to merge.
```

`check-vocab.py ru` 字符档 OK，`check-term-consistency.py ru` 只剩一条首字母大写的差异。
按这个回报就可以合流了。

收尾时顺手核了一件事，结果对不上：**这 42 个键里有 35 个在
`website/src/i18n/locales/ru.json` 里已经存在**，而且现值就是英文原文 —— 新加的键带着
没翻的英文进了目录，例如 `"apps.aiStudio.toggle_panes": "Toggle panes"`。
真正是「新键」的只有 manifest 那 7 条。

## 根因

`scripts/i18n-translate.mjs` 的两半判据**不在同一个轴上**：

- `cmdVerify` / `checkValue` 判的是**我交出去的 shard**：键集一致、占位符奇偶、DNT 在不在、
  空白与括号、`passthroughRatio > 0.5` 才算「没人翻」。目录里该键现值是什么，它一眼都不看。
- `mergeCatalog`（`scripts/i18n-translate.mjs`）默认 insert-only，跳过条件是一句话：

  ```js
  if (!overwrite && Object.prototype.hasOwnProperty.call(node, leaf)) { skipped.push(key); continue }
  ```

  **只看叶子键存不存在，不看值是不是英文。**

于是「目录里已有一个值等于英文的键」正好落在两道判据的缝里：verify 认为这是全新待翻的键，
merge 认为这个键已经有了别动。42 条里 35 条会进 `skipped`，界面照旧显示英文，
而 `skipped` 只在 `cmdMerge` 的返回值里，verify 阶段完全看不见 —— 典型的沉默型判据缺失。

顺带两条同批挖到的、报错里也看不出来的：

1. `ruStyle.test.ts` 那条「禁 `Вы`」的门**恒不触发**：JS 的 `\b` 不把西里尔字母当词字符，
   `/\bВы\b/.test('Вы уверены?')` 在 Node 里是 `false`。表上标 VACUOUS 不是修辞，是真没保护力。
   （Python 的 `re` 却会命中 —— 用别的语言复刻判据会得出相反的结论。）
2. 判据是**读运行时全量目录**的（`bundle('ru')` 读 `../catalogs`），所以拿 shard 文件单独跑
   复算是另一套口径。我只读地复算了三条判据的合并态，又跑了一次真门 `ruStyle.test.ts`
   （3 passed，那是**并入前**的额度状态，交付后必须重跑，别拿这次当证据）。

## 修法

- 合流 ru 之前二选一：
  - `node scripts/i18n-translate.mjs merge <baseDir> --locales=ru --overwrite`，或
  - 先把目录里**值等于 `en.json` 同键**的条目删掉，再走默认 insert-only
- 别指望 `--overwrite` 只作用于我的 42 键：它会对该语种所有已存在键生效，
  所以带它之前先确认这批 shard 的键集就是我要覆盖的范围（本次是 42 键，且 35 条现值就是英文）。

## 怎么避免

交付翻译后**不要停在 `verify` OK**，多跑一步对照，数量不为 0 就在回报里明写「需要 --overwrite」：

```bash
python3 - <<'PY'
import json, glob
def flat(o, p=""):
    d = {}
    for k, v in o.items():
        q = f"{p}.{k}" if p else k
        (d.update(flat(v, q)) if isinstance(v, dict) else d.__setitem__(q, str(v)))
    return d
W = "src/i18n/locales/"
ru, en = flat(json.load(open(W + "ru.json"))), flat(json.load(open(W + "en.json")))
mine = {}
for f in sorted(glob.glob("/home/jereh/scratch/acp2213/ru/shard-*.json")):
    mine.update(json.load(open(f, encoding="utf-8")))
stale = [k for k in mine if k in ru and ru[k] == en.get(k)]
print(f"{len(stale)}/{len(mine)} keys already in the catalog carrying English -> merge needs --overwrite")
PY
```

判据本身若要补，该补的是 `cmdVerify`：对**目录里现值等于英文**的键给一条
`existing-value-is-english-will-be-skipped` 提示，而不是让译者自己发现。
（本次没动脚本 —— 交付纪律禁止改仓里文件，且改判据得走自己的 PR。）
