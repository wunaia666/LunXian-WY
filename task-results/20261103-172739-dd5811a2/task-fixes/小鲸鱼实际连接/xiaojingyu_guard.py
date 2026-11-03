"""小鲸鱼静默守护：检查真实状态，限次恢复，不抢焦点、不重复扫码。"""

from __future__ import annotations

import argparse
import json
import msvcrt
import os
import socket
import subprocess
import sys
import time
import traceback
import urllib.request
from datetime import datetime
from pathlib import Path

import psutil

ROOT = Path(r"E:\sss_test")
TMP = ROOT / "tmp"
STATE = TMP / "xiaojingyu_guard_state.json"
PYTHON = ROOT / "venvs/astrbot/Scripts/pythonw.exe"
SHELL = ROOT / "napcat/shell"
MONITOR = Path(r"D:\deepseek\Yu\大肥鱼_实时监控面板")
ACCOUNT = "3768021466"
FLAGS = subprocess.CREATE_NO_WINDOW


def listening(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def fetch(url):
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=3) as response:
            return json.load(response)
    except (OSError, ValueError):
        return {}


def processes():
    rows = []
    for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
        try:
            rows.append(proc.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return rows


def append_log(message):
    target = TMP / "xiaojingyu_guard.log"
    if target.exists() and target.stat().st_size > 2_000_000:
        target.replace(target.with_suffix(".previous.log"))
    with target.open("a", encoding="utf-8") as output:
        output.write(datetime.now().isoformat(timespec="seconds") + " " + message + "\n")


def check(state, dry_run=False):
    if (TMP / "xiaojingyu_guard.pause").exists():
        state.update(checked_at=datetime.now().isoformat(timespec="seconds"), components={"守护": "已暂停"})
        return state
    now = time.time()
    rows = processes()
    result = {}
    history = state.setdefault("launches", {})

    def launch(key, command, cwd, env=None, cooldown=180, maximum=3):
        stamps = [stamp for stamp in history.get(key, []) if now - stamp < 3600]
        history[key] = stamps
        if stamps and now - stamps[-1] < cooldown:
            return "恢复冷却中"
        if len(stamps) >= maximum:
            return "本小时恢复次数已达上限"
        if dry_run:
            return "需要启动"
        startup = subprocess.STARTUPINFO()
        startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        with (TMP / ("xiaojingyu_" + key + ".log")).open("ab") as output:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT,
                                       creationflags=FLAGS, startupinfo=startup)
        history[key].append(now)
        append_log(key + " 已静默启动，进程 " + str(process.pid))
        return "已发出启动请求"

    astr = any("main.py" in (row["cmdline"] or []) and
               any("astrbot" in item.lower() for item in row["cmdline"] or []) for row in rows)
    result["机器人"] = "正常" if listening(6185) else "启动中" if astr else launch(
        "robot", [str(PYTHON), "-B", "-X", "utf8", "main.py"], ROOT / "AstrBot")
    panel = any(any(str(MONITOR / "monitor.py").lower() == item.lower() for item in row["cmdline"] or []) for row in rows)
    result["监控面板"] = "正常" if listening(8765) else "启动中" if panel else launch(
        "monitor", [str(PYTHON), "-B", "-X", "utf8", str(MONITOR / "monitor.py"), "--no-browser"], MONITOR)

    from qq_gateway_runtime import read_settings, ensure as ensure_gateway
    gateway_settings = read_settings()
    gateway = gateway_settings.get("provider", "napcat")
    qq = any((row["name"] or "").lower() in {"qq.exe", "napcatwinbootmain.exe"} for row in rows)
    status = fetch("http://127.0.0.1:8765/api/status").get("data", {})
    if gateway=="snowluma":
        outcome=ensure_gateway(dry_run=dry_run)
        result["连接程序"]=outcome["状态"]
        result["聊天账号"]="在线" if status.get("qq") else status.get("qq_state") or "等待新连接程序就绪"
    elif status.get("qq"):
        result["聊天账号"] = "在线"
    elif (gateway_settings.get("state") == "paused_by_user"
          or gateway_settings.get("auto_attach") is False
          or gateway_settings.get("allow_client_launch") is False):
        result["聊天账号"] = "手动连接模式，请从网页启动小鲸鱼"
    elif qq:
        result["聊天账号"] = status.get("qq_state") or "客户端运行中，等待登录或重连"
    else:
        env = os.environ.copy()
        env.update(NAPCAT_PATCH_PACKAGE=str(SHELL / "qqnt.json"), NAPCAT_LOAD_PATH=str(SHELL / "loadNapCat.js"),
                   NAPCAT_INJECT_PATH=str(SHELL / "NapCatWinBootHook.dll"), NAPCAT_MAIN_PATH=str(SHELL / "napcat.mjs"))
        result["聊天账号"] = launch("qq", [str(SHELL / "NapCatWinBootMain.exe"),
            r"C:\Program Files\Tencent\QQNT\QQ.exe", str(SHELL / "NapCatWinBootHook.dll"), "-q", ACCOUNT],
            SHELL, env, cooldown=600, maximum=2)

    health = fetch("http://127.0.0.1:9880/health")
    if health:
        result["本地语音"] = "异常，等待检查" if health.get("phase") == "degraded" else "就绪" if health.get("ready") else "加载中"
        if health.get("warning"):
            result["语音提示"] = health["warning"]
        result["参考音"] = health.get("prompt", "")
    else:
        # 服务加载期间不重复启动；后台启动器尚在等待健康接口时也视为启动中。
        wsl_start = any((row["name"] or "").lower() == "wsl.exe" and
                        any("cosy_wsl.sh" in item for item in row["cmdline"] or []) for row in rows)
        result["本地语音"] = "加载中" if wsl_start else launch("voice",
            ["wsl.exe", "-d", "Ubuntu", "--", "bash", "/mnt/e/sss_test/tools/cosy_wsl.sh", "start"],
            ROOT, cooldown=600, maximum=2)
    previous = state.get("components")
    state.update(checked_at=datetime.now().isoformat(timespec="seconds"), components=result,
                 interval_seconds=60, waiting_login_does_not_restart=True)
    if previous != result and not dry_run:
        append_log(json.dumps(result, ensure_ascii=False))
    return state


def read_state():
    try:
        value = json.loads(STATE.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return value
    except FileNotFoundError:
        return {}
    except (ValueError, UnicodeError):
        pass
    append_log("守护状态损坏，将从实际服务状态重新检查。")
    return {}


def main():
    parser = argparse.ArgumentParser(description="小鲸鱼静默守护")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--delay", type=int, default=0)
    args = parser.parse_args()
    TMP.mkdir(parents=True, exist_ok=True)
    with (TMP / "xiaojingyu_guard.lock").open("a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if not lock.tell():
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if not args.check_only:
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                return
        try:
            if args.delay:
                time.sleep(min(args.delay, 120))
            while True:
                try:
                    state = read_state()
                    state = check(state, args.check_only)
                    if not args.check_only:
                        temp = STATE.with_suffix(".tmp")
                        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                        temp.replace(STATE)
                    if sys.stdout:
                        print(json.dumps(state.get("components"), ensure_ascii=False), flush=True)
                except Exception:
                    append_log("检查异常，将在下次重试：" + traceback.format_exc())
                    if not args.watch:
                        raise
                if not args.watch or args.check_only:
                    break
                time.sleep(60)
        finally:
            if not args.check_only:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == "__main__":
    main()
