# AppArmor userns 档案：源码多实例启动沙箱的两个坑

日期：2026-09-23 13:52
场景：在一台 Ubuntu ≥23.10 主机上，用源码起了两个 Kiro Crew 实例
（kiro-dev 合并主干 :6777、kiro-upstream 原版 :6787），对话页一直报
「沙箱不可用 / Kiro CLI 已安装，但无法验证」。

## 现象

- 网关日志里 `SandboxUnavailableError`，栈顶是 `sandbox.wrap_argv →
  unshare(CLONE_NEWNS) failed with errno 1 (EPERM)`。
- 前端 `KiroPrerequisiteGate` 弹「沙箱不可用」，`/api/kiro-prerequisite`
  返回 `sandbox_unavailable: true`。
- 明明 `/etc/apparmor.d/` 下早就有 `kirocrew-launcher` 档案（9 月 21 号
  装过一次），`aa-status` 也能列出它——看起来"已经配好了"，却依然 EPERM。
- 报错本身完全不提示下面这两个真正的原因。

## 根因

### 坑 1：档案是"按路径附着"的，但网关不是用那条路径 exec 起来的

Ubuntu 23.10+ 开了 `kernel.apparmor_restrict_unprivileged_userns=1`，
非特权进程要建 user namespace 必须命中一个带 `userns,` 的 AppArmor 档案。
`kirocrew sandbox install-profile` 写的是**路径附着档案**：内核在
`execve` 那一刻，按"被 exec 的那个文件的路径"决定是否套档案。

而我把网关起成了：

```
.venv/bin/python3.12 .venv/bin/kirocrew gateway --no-open
```

`execve` 的目标是 **python 解释器**，`.venv/bin/kirocrew` 只是它的命令行参数、
根本没被 exec。路径附着认的是被 exec 的文件，不认 argv 里出现的路径——于是
档案永不命中，进程 `attr/current` 一直是 `unconfined`，unshare 吃 EPERM。

判据：`cat /proc/<网关pid>/attr/current`。
- `unconfined` = 没命中档案 = 一定 EPERM；
- `kirocrew-launcher (unconfined)` = **命中了**（`flags=(unconfined)` 只是
  说这档案除了 `userns,` 不额外限制任何东西，跟 chrome/brave 出厂形状一样，
  不是"没生效"）。

正确起法：直接 exec 带 shebang 的启动脚本本身，让 execve 目标 == 附着路径：

```
KIROCREW_PORT=6777 KIROCREW_HOME=<home> setsid .venv/bin/kirocrew gateway --no-open
```

### 坑 2：`install-profile` 永远写同一个文件，第二个实例会覆盖第一个

`kirocrew sandbox install-profile` 只认一个落盘路径：
`/etc/apparmor.d/kirocrew-launcher`，档案名也固定 `kirocrew-launcher`。
我给 upstream 实例跑了一次 `install-profile --path <upstream 的 kirocrew>`，
它把 devmain 那份的附着路径**改写成了 upstream 的**——devmain 就此失去档案。
`apparmor_parser` 还报 `Could not load profile .../kirocrew-launcher`。

多实例的正解是**每个实例一份独立命名的档案**（仓里 `kirocrew-launcher-wtui`
就是这么来的）。第二、三份手抄一个同形状文件，改两处即可：档案名 + 附着路径：

```
abi <abi/4.0>,
include <tunables/global>
profile kirocrew-launcher-upstream "/abs/path/.../kirocrew-upstream/.venv/bin/kirocrew" flags=(unconfined) {
  userns,
  include if exists <local/kirocrew-launcher-upstream>
}
```

装：`sudo install -m644 ...; sudo apparmor_parser -r -W <文件>`。
一个文件里塞两个 `abi`/`include` 头会被 parser 判语法错——要么一个档案一个文件。

## 附带坑：install-profile 会拒绝可被替换的路径

`validate_exec_path` 会因为附着路径的可写性拒绝安装：文件本身 mode 0775、
或任一祖先目录 group/world 可写，都拒。`workplace/` 一路往上好几层是 0775，
逐层 `chmod go-w` 才放行。这是防"别人能替换那个路径上的二进制"的加固，
但报错没说要 chmod 到哪个目录，得一层层试。

## 修法（本次实际执行）

1. 给 devmain 重跑 `kirocrew sandbox install-profile --path <devmain kirocrew>`，
   把被覆盖的 `kirocrew-launcher` 抢回成 devmain 的。
2. 手写 `/etc/apparmor.d/kirocrew-launcher-upstream`（独立档案名，附 upstream
   路径），`apparmor_parser -r -W` 载入。`aa-status` 见到三条
   （`-launcher` / `-launcher-upstream` / `-launcher-wtui`）。
3. 两个网关都 **kill 后按坑 1 的正确起法**（直接 exec 脚本）重启。
4. 验：`/proc/<pid>/attr/current` 出现各自档案名；`/api/kiro-prerequisite`
   经域名返回 `sandbox_unavailable:false`；两台日志再无 EPERM。

剩下的 `ready:false / authenticated:false` 是 kiro-cli 没登录，属另一件事，
需交互 `kiro-cli login`，不是沙箱。

## 怎么避免

- **源码跑网关一律 `setsid .venv/bin/kirocrew gateway ...`**，绝不用
  `python <script> gateway` 形式——否则路径附着档案白装。
- 排查沙箱先看 `cat /proc/<网关pid>/attr/current`，别看"档案文件存不存在"。
  文件在 ≠ 命中；命中后带 `(unconfined)` 字样是正常的。
- 多实例不要重复对同一个 `install-profile` 传不同 `--path`（互相覆盖）。
  第二个实例起，各自一份独立命名档案（照 wtui 先例）。
- 别去动 `kernel.apparmor_restrict_unprivileged_userns=0` 或
  `agent.sandbox_allow_unsandboxed_exec=true` 图快——那是把整机/整个 agent 的
  隔离拆掉，且按 AGENTS.md 属 owner 专属决定。沙箱 scope 的口子只能 owner 开。
