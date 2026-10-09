# 推了 v1/v2 标签，个人仓 develop 却还是模板那一版（ACP-2218）

## 现象

「设备管理」实战：4 个开发任务 + 2 次验收修复都跑完了，看板全绿，〔部署正式〕也成功，
日志里 `推 tag` 一步没报错。回个人仓一看，`develop` 还停在模板初始提交，别人 clone
下来一行代码都看不到。

从任何一处的输出都看不出来有问题：

- 开发轮次 `runState=done`，每个节点都带 `endCommit`；
- 部署 `state=running`，`version=v2`，发布台账两条；
- 日志里 `[prod] 部署成功`，没有 `打 tag 失败` 也没有 `推 tag 失败`。

## 根因

`git push origin v1` 推的是**那一个标签引用**，不是分支。它会把标签指到的提交及其祖先
送进远端对象库（这是 git 的规矩，否则标签指向的提交不存在），但**不会创建或移动
`refs/heads/<分支>`**。远端于是得到「有对象、有标签、零分支」。

实测（本地 bare 仓，两个提交 + 一个 v1 标签，只 `push origin v1`）：

```console
$ git ls-remote origin
e1e251a…  refs/tags/v1
8020894…  refs/tags/v1^{}          ← 只有标签，没有 refs/heads/develop

$ git clone <那个 bare 仓> clone
warning: remote HEAD refers to nonexistent ref, unable to checkout
$ cd clone && git branch -a         # 空
$ ls                                # 空目录
```

clone 出来是一个**空的、HEAD 指向不存在引用**的仓库 —— 对象在库里，但没有分支引用把它
交给人。所以「远端明明推成功过东西」和「远端有人能看见的代码」是两件事，而我们的部署
流程只做了前者。

第二个坑在补这一步时才撞上：`git rev-parse --abbrev-ref HEAD` 在 detached HEAD 下
原样回 `HEAD`（退出码 0，不是失败）。如果照字面把分支名拼进 refspec，`git push origin
HEAD:HEAD` 会去远端建一个叫 `HEAD` 的分支 —— 一次「成功」的推送，写坏的是远端的引用
命名空间。

## 修法

新增 `backend/gitpush.py`：`push_branch(ws, log, run=None)`，先 `rev-parse
--abbrev-ref HEAD` 拿当前分支，再 `push origin HEAD:<分支>`；`HEAD`（detached）直接
不推并写清原因。调用点两处：

- `devdag._loop` 整轮收口成 `done` 之后推一次；带修复节点的一轮在自动再验收**之前**
  再推一次（验收要几分钟，期间网关重启会把整轮判中断，那时修复必须已经在远端）；
- `prodserver._succeed` 在打标签**之前**推。

`env` 用 `devserver.child_env({})` 加 `GIT_TERMINAL_PROMPT=0`（不挂代理；缺凭据时让
git 直接报错，而不是开一个 tty 问用户名 —— 这里没人回答，只会把 120 秒等满，从外面看
就是「部署卡住了」）。失败只写日志、返回 `False`：推不出去不该把已经跑着的服务报成
部署失败。

## 怎么避免

- **凡是「代码要给别人看」的流程，收尾必须验一次远端的分支引用**，不是验标签、不是验
  命令退出码。一条 `git ls-remote origin refs/heads/<分支>` 就能判；实测那一条已经写进
  `test_push_branch_really_lands_on_a_remote`（本地 bare 仓，不需要网络也不需要凭据）。
- 「推」这个动词在 git 里是**按引用**的，不是按提交。任何 `push origin <X>` 都只保证
  `<X>` 这一个引用，别的引用一个都不动。
- 替身 git 只能验判断和措辞，验不了命令对不对。这类「远端到底长什么样」的结论要用真
  git + 临时 bare 仓，替身永远复现不了现象本身。
