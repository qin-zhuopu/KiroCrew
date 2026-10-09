# 分支上本来就红的两道门禁，和「这红是不是我的」的判定办法

时间：2026-10-10 04:53（ACP-2226，feature/ACP-2226-gate，从 feature/ACP-2015-v1 拉的）

## 现象

改完 `accept.py` + `DevDagPanel.tsx`，收尾跑门禁，两处红：

```
$ cd website && npm run typecheck          # exit 2
src/apps/ai-studio/AiStudioPage.tsx(719,24): error TS2873: This kind of expression is always falsy.
src/apps/ai-studio/DevServerControl.tsx(22,21): error TS6133: 'StudioApiError' is declared but its value is never read.

$ cd website && I18N_BASE_REF=HEAD npm run i18n:check   # exit 1，19 checks · FAIL 1
    FAIL    [manifest-sync]   7 manifest/catalog mismatch(es)   hard zero
[app-manifest-sync] FAIL — 7 problem(s)
    ai-studio: key 'apps.aiStudio.manifest.display_name' is not in locales/en.json
    ... description / page_label / highlight_1..4
```

两个报错点都在**我没碰过的文件**（`AiStudioPage.tsx`、`DevServerControl.tsx`），而
`apps.aiStudio.manifest.*` 这 7 个键更是我根本没写过的命名空间。但「看着不像我的」
不是证据——我的记忆规则里就有一条：派工单里写没测过的数字，worker 白对一轮。

## 根因

两条都是分支自带的，和这一刀无关：

1. **`AiStudioPage.tsx` 第 719 行是 `devLoop={undefined && (…)}`**，那行是我上游的提交
   `39034a4377`（把开发板挂进真实「开发」页签）留下的：`<DevLoopPanel>` 不挂了，但
   JSX 用 `undefined &&` 短路留在那里，`tsc` 报「恒假」。`DevServerControl.tsx`
   的未用 import 来自 `0d87d040d8`（ACP-2060）。`git log -L 719,719:<file>` 直接
   指到提交，两行都不是我写的。
2. **`[manifest-sync]` 要比的是 `app.json` 的 7 个字符串和 `locales/en.json` 里的
   `apps.aiStudio.manifest.*`**，而 en.json 里**从来没有过**这个命名空间。判定不用
   重跑脚本，一条 JSON 探测就够：

   ```bash
   for ref in HEAD WORK; do python3 - "$ref" <<'PY'
   import json,subprocess,sys
   ref=sys.argv[1]
   raw=(subprocess.run(['git','show','HEAD:website/src/i18n/locales/en.json'],
                       capture_output=True,text=True).stdout
        if ref=='HEAD' else open('website/src/i18n/locales/en.json').read())
   print(ref,'aiStudio.manifest in en.json:', 'manifest' in json.loads(raw)['apps']['aiStudio'])
   PY
   done
   # HEAD aiStudio.manifest in en.json: False
   # WORK aiStudio.manifest in en.json: False
   ```

   HEAD 和工作树一样缺 → 那 7 条在 HEAD 上同样会打出来。我这一刀给 en.json 只加了
   7 个 `devDag.*` 键（`git diff | grep "^+"` 逐行核过，`manifest` 0 处）。

顺带确认**不是**我的锅的方法还有两个，比读脚本报错可靠：

- **`[source-strings] 7 new English key(s) · 0 badly shaped`**：这行数的是「我这条
  diff 新加的英文键」，7 个正好是我加的 7 个 `devDag` 键，且判 0 缺陷。
- **`[pseudolocale] en-XA matches en · 15241 keys · hard zero` PASS**：加英文键之后
  必须 `npm run i18n:pseudo` 重生成 `en-XA.json`，否则 hard-zero 直接红。我先跑了
  它，所以这一行是绿的（这一步很容易漏，漏了 CI 才报，且报的是「keys 不匹配」不告诉你为什么）。

## 修法

不动别人的红。归属写进完工报告，让 master 决定谁来收：

- `typecheck` 的两条：造一个干净基线自证，**别用「我本地也是红的」当证据**（脏树
  会骗人）。基线要真·HEAD，而且要**同一个 node_modules**，否则测的是另一棵树：

  ```bash
  git worktree add /tmp/base-$$ HEAD --detach
  ln -sfn <本 worktree>/website/node_modules /tmp/base-$$/website/node_modules
  cd /tmp/base-$$/website && pwd && npx tsc -p tsconfig.app.json   # 先 pwd 自证在基线里
  ```
  实测基线回**同样两条**，退出码 2。用完 `rm` 掉软链再 `git worktree remove --force`
  （软链留在里面，`worktree remove` 会连着 target 一起抱怨）。
- `[manifest-sync]` 同理，只是它的证据是 JSON 探测而不是重跑脚本。
- 我自己那一刀的账是干净的：`mypy --platform linux`、`flake8`、`black --check`、
  新测试 59 条、`DevDagPanel.test.tsx` 37 条、i18n 其余 18 行全 PASS。

## 怎么避免

- **长分支上 `npm run typecheck` 与 `npm run i18n:check` 默认是红的**（至本笔记时：
  feature/ACP-2015-v1 上 `tsc` 2 条 + `[manifest-sync]` 7 条）。别一上来就以为是自己
  弄坏的，也别顺手去修别人的（会吞掉别人的 diff）；先归属，再决定。
- `i18n:check` 的 diff 范围**默认 base 是 `origin/main`**，长分支上会把整条分支的账
  算到你头上。要只看自己这一刀：`I18N_BASE_REF=HEAD npm run i18n:check`。whole-repo
  那几行（`key-refs`/`plurals`/`pseudolocale`/`dnt`/`manifest-sync`）不受这个变量影响，
  它们量的是整仓，出现 FAIL 要先问「HEAD 上是不是也这样」，不要直接改。
- **加了 `en.json` 的键就立刻 `npm run i18n:pseudo`**（改一个键 → `en-XA.json` 多
  对应那一条，diff 干净可 review）。漏了它，`[pseudolocale]` hard-zero 红，而它报的
  是「key 数不匹配」，看不出你缺的是这一步。

## 附带一条：`-p no:xdist` 会把 pytest 直接打死

想「只跑一个文件、别开 20 个 worker」而加 `-p no:xdist`：

```
$ .venv/bin/pytest test/x.py -p no:xdist
pytest: error: unrecognized arguments: -n --dist loadgroup --max-worker-restart=2
```

退出码 4，**一条测试都没跑**，`grep FAILED` 什么都没有，容易误读成「文件没找到」。
根因：仓的 `addopts` 里就写着 `-n auto --dist loadgroup --max-worker-restart=2`，
插件被禁了这些参数就成了未知参数——报错只说参数不认识，不说谁传的。
要控制并发就**保留那三个参数**改数值（AGENTS.md 的门禁段也是这条），别禁插件。
