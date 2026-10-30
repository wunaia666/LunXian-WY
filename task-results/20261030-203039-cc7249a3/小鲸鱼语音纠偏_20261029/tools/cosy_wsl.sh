#!/bin/bash
# CosyVoice 服务启停（在 WSL 内运行，引擎由 voice_config 决定）
# 用法： bash cosy_wsl.sh start|stop|status|log
set -uo pipefail

export PATH="$HOME/miniconda3/bin:$PATH"
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate cosy 2>/dev/null

LOG=/mnt/e/sss_test/tmp/cosy_server.log
PIDF=/tmp/cosy_server.pid
PORT=9880

alive() {
  curl -s --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1
}

case "${1:-status}" in
  start)
    if alive; then echo "already running on :$PORT"; exit 0; fi
    cd "$HOME/CosyVoice" || exit 1
    : > "$LOG"
    # 用守护循环启动：推理硬超时自杀后会由 supervisor 重新拉起
    setsid bash /mnt/e/sss_test/tools/cosy_supervisor.sh >> "$LOG" 2>&1 < /dev/null &
    echo "starting (supervised)... pid $!"
    for i in $(seq 1 240); do
      sleep 2
      if alive; then echo "ready after $((i*2))s"; exit 0; fi
      if grep -qE "Traceback|Error" "$LOG" 2>/dev/null; then
        echo "FAILED - last log:"; tail -20 "$LOG"; exit 1
      fi
    done
    echo "TIMEOUT 480s - last log:"; tail -20 "$LOG"; exit 1
    ;;
  stop)
    # 先杀守护循环，否则它会立刻把服务重新拉起来
    pids=$(ps -eo pid,args | grep -E "cosy_supervisor\.sh" | grep -v grep | awk '{print $1}')
    [ -n "$pids" ] && echo "$pids" | xargs -r kill
    pids=$(ps -eo pid,args | grep -E "cosy_server[0-9]*\.py" | grep -v grep | awk '{print $1}')
    if [ -z "$pids" ]; then echo "not running"; exit 0; fi
    echo "$pids" | xargs -r kill
    sleep 2
    pids2=$(ps -eo pid,args | grep -E "cosy_server[0-9]*\.py" | grep -v grep | awk '{print $1}')
    [ -n "$pids2" ] && echo "$pids2" | xargs -r kill -9
    echo "stopped"
    ;;
  status)
    if alive; then
      echo "RUNNING"
      curl -s --max-time 3 "http://127.0.0.1:$PORT/health"; echo
    else
      echo "DOWN"
    fi
    ps -eo pid,rss,args | grep -E "cosy_server[0-9]*\.py" | grep -v grep | head -2
    ;;
  log)
    tail -${2:-30} "$LOG"
    ;;
  *)
    echo "usage: $0 start|stop|status|log [n]"
    ;;
esac