#!/bin/bash
# ACP-2060 第 6 步：用接口（不是浏览器）启停演示项目的开发服务器。
# 鉴权照 .kirocrew-dev/probe-api.sh 的路子：链接 token 换 mc_token_6790 cookie，再拿 cookie 打接口。
set -u
ROOT=/home/jereh/repo/github.com/kirodotdev/KiroCrew-wt-kc-v1
HOME_DIR=$ROOT/.kirocrew-dev
JAR=$HOME_DIR/cookies-dev.txt
PID=p261008-151745
# 必须用 localhost 而不是 127.0.0.1：握手链接是 http://localhost:6790?token=…，
# cookie 是按 Set-Cookie 的 Domain 记的，curl 里 127.0.0.1 与 localhost 是两个 host，
# 换过去就不带 cookie，接口回 403 "Token required"（不是没登录，是 cookie 没送）。
API=http://localhost:6790/api/apps/ai-studio/projects/$PID/dev-server

need_login=1
if [ -f "$JAR" ]; then
  code=$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' -b "$JAR" "$API")
  { [ "$code" = "200" ] || [ "$code" = "404" ]; } && need_login=0
fi

if [ "$need_login" = "1" ]; then
  cd "$ROOT" || exit 1
  KIROCREW_HOME=$HOME_DIR PYTHONPATH=$ROOT/src \
    .venv/bin/python -m kiro_crew token --port 6790 > "$HOME_DIR/token-dev.txt" 2>/dev/null
  LINK=$(python3 -c "
import re
print(re.search(r'(http://localhost:6790\?token=[A-Za-z0-9._-]+)', open('$HOME_DIR/token-dev.txt').read()).group(1))")
  curl -s --noproxy '*' -c "$JAR" -o /dev/null -w 'handshake=%{http_code}\n' "$LINK"
fi

case "${1:-get}" in
  get)   curl -s --noproxy '*' -b "$JAR" "$API" ;;
  start) curl -s --noproxy '*' -b "$JAR" -X POST -H 'Content-Type: application/json' -d '{}' -w '\nHTTP=%{http_code}\n' "$API/start" ;;
  stop)  curl -s --noproxy '*' -b "$JAR" -X POST -H 'Content-Type: application/json' -d '{}' -w '\nHTTP=%{http_code}\n' "$API/stop" ;;
  log)   curl -s --noproxy '*' -b "$JAR" "$API/log?lines=40" ;;
  *) echo "用法: $0 [get|start|stop|log]"; exit 2 ;;
esac
