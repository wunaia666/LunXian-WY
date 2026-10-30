#!/bin/bash
# 本地语音服务异常退出后恢复，参考音与引擎使用持久化配置。
export PATH="$HOME/miniconda3/envs/cosy/bin:$PATH"
# 75 秒会误杀"慢但能完成"的句子，一律杀进程又让服务白等 67 秒重载，放宽到 90
export COSY_HARD_TIMEOUT="${COSY_HARD_TIMEOUT:-90}"
export COSY_POISON_EXIT="${COSY_POISON_EXIT:-0}"
LOG=/mnt/e/sss_test/tmp/cosy_server.log
cd "$HOME/CosyVoice" || exit 1
export PYTHONPATH="$HOME/CosyVoice:$HOME/CosyVoice/third_party/Matcha-TTS"
CONFIG=/mnt/e/sss_test/dafeiyu_assets/voice_config.json

while true; do
  export COSY_PROMPT="$(python -c 'import json; print(json.load(open("/mnt/e/sss_test/dafeiyu_assets/voice_config.json", encoding="utf-8"))["_模型"]["ref_wav_wsl"])')"
  ENGINE="$(python -c 'import json; print(json.load(open("/mnt/e/sss_test/dafeiyu_assets/voice_config.json", encoding="utf-8"))["_模型"].get("engine", "cosyvoice2"))')"
  if [ "$ENGINE" = "cosyvoice3" ]; then
    export COSY_MODEL="$(python -c 'import json; print(json.load(open("/mnt/e/sss_test/dafeiyu_assets/voice_config.json", encoding="utf-8"))["_模型"]["model_dir_wsl"])')"
    echo "[sup] $(date +%H:%M:%S) 启动三代服务 $COSY_MODEL" >> "$LOG"
    python /mnt/e/sss_test/tools/cosy_server3.py
  else
    echo "[sup] $(date +%H:%M:%S) 启动二代服务" >> "$LOG"
    python /mnt/e/sss_test/tools/cosy_server.py
  fi
  code=$?
  echo "[sup] $(date +%H:%M:%S) server 退出 code=$code，3 秒后重启" >> "$LOG"
  sleep 3
done
