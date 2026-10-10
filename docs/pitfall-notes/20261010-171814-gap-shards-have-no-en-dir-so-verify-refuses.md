# 补漏批次没有 `en/`，`verify` 就地跑不了 → 用一次性 baseDir 照样吃到仓里真判据

ACP-2113 收尾：es 缺 13 键，需求给的是 `/home/jereh/scratch/acp2113-gap/es/spec.json`
（每条 `{en, zh, ctx, dnt}`），交付物是 `es/shard-01.json`。

翻完想跑仓里真判据自证，直接撞墙：

```
$ node scripts/i18n-translate.mjs verify /home/jereh/scratch/acp2113-gap --locale=es
/home/jereh/scratch/acp2113-gap/en does not exist — run `i18n-shard.mjs split` first.
```

## 根因

`cmdVerify(baseDir, code)` 的目录约定是**写死的两个兄弟目录**：
它只扫 `<baseDir>/en/shard-\d+.json` 当**期望键集**，再去 `<baseDir>/<code>/` 取译文
（`cmdVerify` 里那个只匹配分片名的正则，加上它配套的分片读取函数）。补漏批次的目录里**只有 `es/spec.json`，根本没有 `en/`**——
它的英文原文藏在 `spec.json` 每条的 `en` 字段里，不是一个 shard 文件。

所以「跑不了 verify」不是参数写错（那是另一个坑，baseDir 不能写成语种目录），
而是**这批的输入形态和判据的输入形态不一致**：spec 是「一条记录带原文+参考译文」，
判据要的是「两个平行目录的同名 shard」。

## 修法（三行，别自己复刻判据）

把 spec 拆成判据要的形态，写进 `/tmp`（**绝不写进批次目录，那是交付面**）：

```bash
python3 - <<'PY'
import json
spec=json.load(open('/home/jereh/scratch/acp2113-gap/es/spec.json'))
tr=json.load(open('/home/jereh/scratch/acp2113-gap/es/shard-01.json'))
import os; os.makedirs('/tmp/es-gap-verify/en',exist_ok=True); os.makedirs('/tmp/es-gap-verify/es',exist_ok=True)
json.dump({k:d['en'] for k,d in spec.items()}, open('/tmp/es-gap-verify/en/shard-01.json','w'), ensure_ascii=False, indent=2)
json.dump(tr, open('/tmp/es-gap-verify/es/shard-01.json','w'), ensure_ascii=False, indent=2)
PY
cd …/KiroCrew-wt-kc-dag/website && node scripts/i18n-translate.mjs verify /tmp/es-gap-verify --locale=es
# [es] 1 shard(s), 13 key(s), plurals [one many other], 0 finding(s), 0.0% identical to English
# OK: es is ready to merge.
```

实测（2026-10-10 17:16）13 键 0 finding。**注意 `0.0% identical to English` 这个数在
这种临时 baseDir 下天然为 0**：en 侧是我从 spec 拷的，只要我写的一个字没和英文相同就是 0，
它只证明「我没抄英文」，不证明别的。

## 为什么非要绕这一下，而不是自己写个 python 断言

`checkValue` 里有几件事**肉眼和手写断言都会漏**：DNT 词表是从
`src/i18n/glossary.json` 加载的 62 条、按**词边界 + Unicode `\p{L}`** 匹配；
括号平衡是**对英文取增量**（不是判自身平衡，D1 碎片键源码里本来就不平衡）；
全角只查字母数字不查标点。我第一轮手写 python 只覆盖了占位符/空白/`usted`/引号，
覆盖面明显窄于真判据——**自造门给自己开绿灯**是这类活最常见的假绿。

## 怎么避免

- 拿到「补漏 spec.json」这种**非 shard 形态**的批次，**第一件事**是先确认
  判据能不能就地跑；不能就先造一次性 baseDir，再动手翻（翻完再搭桥容易变成「先交卷后补考」）
- 临时 baseDir 一律放 `/tmp`，**交付目录里只留规定的那一个文件**
  （多出来的文件主会话不收，还会让「键集逐键相同」的核对产生歧义）
- 想复用判据里的单个函数也可以：`checkValue` / `flatten` / `placeholders` 都是 `export`，
  `node` 里 `import` 进来直接对我的 13 条跑（我这次两条路都走了，结论一致）
