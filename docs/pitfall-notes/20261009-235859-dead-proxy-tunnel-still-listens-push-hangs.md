# 代理端口还在听，但隧道上游已经死了：`git push` 只会静默挂住

时间：2026-10-09 23:58:59
涉及：推 fork（`git push fork feature/ACP-2085-dag`），本机 `socks5://localhost:7777` 代理链路

## 现象

`git push fork ...` 一直没有输出、也不报错，一挂就是几分钟，只能手工 kill。
中间试过的每一条都「看起来是通的」：

- `ss -tln | grep 7777` → **在听**（代理端口活着）
- `getent hosts github.com` → 解析得到 `20.205.243.166`
- `ping 144.34.190.136` → 通，180ms，0% 丢包
- `curl --max-time 8 https://github.com` → **超过自己的 max-time 还在挂着**（最反常的一条）
- `git ls-remote fork` → 同样静默挂住

`kill` 掉 push 之后再查 `git ls-remote`，远端 ref 没变 —— 也就是说那次 push 根本没写到
远端，静默不等于成功。

## 根因

`7777` 不是本机服务，是一条 `ssh -D` 的本地动态转发，靠 screen 里的
`while true; do ssh -p 29472 -D 0.0.0.0:7777 ... ; done` 循环维持。那条 ssh 的
**上游已经断了**（远端 `144.34.190.136:29472` 反复 `Connection timed out`），但：

1. **ssh 的本地监听端口与上游健康是两件事**。上游死了，本地 `127.0.0.1:7777` 照常在听 ——
   `ss` 因此永远显示「代理活着」。任何连上它的客户端都会被 ssh 接下这条连接，然后
   等一个永远不会建立的远端拨号，**表现就是「连上了但一个字都不回」**。
2. `curl` 的 `--max-time` 只约束它自己的传输，TCP 已连上、SOCKS 握手后的等待不算数，
   于是出现「max-time 8 却挂 20 秒」这种反常。
3. `git push` 全程静默：它只在**拿到 http 响应**之后才打印东西，卡在连接阶段就是零输出。
4. 那个 while 循环也不是保险：`Warning: remote port forwarding failed for listen port 22139`
   说明 ssh 有时是**带着失败的 -R 起来、看起来活着**的（screen 里既有 `timed out` 也有
   `Last login ...` 的交互提示），循环活着 ≠ 隧道能用。

真正的证据只有一个：`screen -X -S <名> hardcopy /tmp/x.txt` 把那个会话的画面抠出来看，
里面一片 `Connection to 144.34.190.136 port 29472 timed out`。

## 修法

不动用户那条 7777（它归那个 screen 循环管，也可能正被人用），**另开一条一次性的隧道**，
只给这一次 push 用：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=10 \
    -o ExitOnForwardFailure=yes -p 29472 -D 127.0.0.1:7790 -N qin@144.34.190.136 &
# 等端口起来（几秒到十几秒，别假设立刻可用）
while ! timeout 1 bash -c 'exec 3<>/dev/tcp/127.0.0.1/7790'; do :; done
git -c http.proxy="socks5h://127.0.0.1:7790" push fork <分支>
```

实测：`curl -x socks5h://127.0.0.1:7790 https://github.com` 回 200，push 秒过
（`4c61bac8e..2fcd6fd05`），`git ls-remote` 回来的 hash 与本地 HEAD 一致才算推上去。

两个小坑顺手记一下：
- **`-D` 的转发不是立刻可用**：我按 12 次空转判「起来了」，结果 curl 抢在端口 listen 之前跑，
  报 `Failed to connect ... after 0 ms`，白判一次隧道坏了。要么轮询端口，要么给足重试。
- **一次性的 ssh 会被 Bash 工具的进程组带走**：把隧道写在脚本里、脚本退出时就没了。
  要跨调用复用就得 `setsid nohup ... < /dev/null &` 脱离进程组。

## 怎么避免

- **「`ss` 显示代理在听」不能证明代理可用。** 判代理只有一条硬指标：拿它打一个真请求看
  状态码 —— `curl -sS --max-time 12 -x socks5h://127.0.0.1:7777 -o /dev/null -w '%{http_code}\n'
  https://github.com`。超时/000 就是死了，别再查 DNS、别怀疑 git。
- **一条命令静默挂住时，先分清「连不上」和「连上了不说话」**：`timeout 6 bash -c
  'exec 3<>/dev/tcp/<ip>/<port>'` 探裸 TCP。GitHub 443/22 直连都 BLOCKED 而隧道主机 ping 得通
  —— 这组合已经把答案说完了：出口只有那条隧道，隧道上游坏了。
- **别把 ping 当可达性证据**：icmp 通着而 29472 上的 ssh 起不来，是两件独立的事。
- `git push` 之后一律 `git ls-remote <remote> <分支>` 对一次 hash，别用「命令没报错」当推成功。
- 排查远端机器上的会话现场，`screen -X -S <名> hardcopy <文件>` 比猜有用 —— 本次唯一的
  决定性证据就在那张画面里（一片 `port 29472 timed out`）。
