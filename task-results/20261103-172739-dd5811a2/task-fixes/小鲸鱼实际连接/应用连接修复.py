"""备份并部署手动聊天连接入口，只重载监控与守护，不中断客户端。"""

import datetime
import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import psutil

STAGE = Path(__file__).resolve().parent
ROOT = Path(r"E:\sss_test")
PANEL = Path(r"D:\deepseek\Yu\大肥鱼_实时监控面板")
FILES = {
    "xiaojingyu_chat_control.py": ROOT / "tools/xiaojingyu_chat_control.py",
    "xiaojingyu_guard.py": ROOT / "tools/xiaojingyu_guard.py",
    "dashboard.html": PANEL / "dashboard.html",
}


def main():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:8765/api/status", timeout=4) as response:
        current = json.load(response)["data"]
    if not current.get("qq") or current.get("qq_account") != "3768021466":
        raise RuntimeError("实际小鲸鱼账号未在线，停止切换已验证连接配置")
    backup = ROOT / "backups" / ("本机聊天接入_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    backup.mkdir(parents=True, exist_ok=False)
    settings = ROOT / "dafeiyu_assets/qq_gateway.json"
    shutil.copy2(settings, backup / settings.name)
    for name, target in FILES.items():
        compile((STAGE / name).read_text(encoding="utf-8"), name, "exec") if name.endswith(".py") else None
        shutil.copy2(target, backup / name)
        temporary = target.with_suffix(target.suffix + ".pending")
        shutil.copy2(STAGE / name, temporary)
        os.replace(temporary, target)
    config = json.loads(settings.read_text(encoding="utf-8"))
    config.update(provider="napcat", state="manual_started", auto_attach=False,
                  allow_client_launch=False)
    temporary = settings.with_suffix(".pending")
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, settings)
    targets = {str(ROOT / "tools/xiaojingyu_guard.py").lower(), str(PANEL / "monitor.py").lower()}
    to_stop = []
    for process in psutil.process_iter(["name", "cmdline"]):
        try:
            if (process.info["name"] or "").lower() not in {"python.exe", "pythonw.exe"}:
                continue
            if targets.intersection(arg.lower() for arg in process.info["cmdline"] or []):
                to_stop.append(process)
        except psutil.NoSuchProcess:
            pass
    # 只停止两个后台脚本及其解释器包装进程，不匹配聊天客户端或机器人进程。
    for process in reversed(to_stop):
        try:
            process.terminate()
        except psutil.NoSuchProcess:
            pass
    alive = to_stop
    for _ in range(16):
        alive = [process for process in alive if process.is_running()]
        if not alive:
            break
        time.sleep(0.5)
    if alive:
        raise RuntimeError("旧监控进程未退出；备份已保留，不重复启动")
    python = ROOT / "venvs/astrbot/Scripts/pythonw.exe"
    for script, cwd, args, log in (
        (PANEL / "monitor.py", PANEL, ["--no-browser"], "xiaojingyu_monitor_reload.log"),
        (ROOT / "tools/xiaojingyu_guard.py", ROOT, ["--watch"], "xiaojingyu_guard_reload.log"),
    ):
        with (ROOT / "tmp" / log).open("ab") as output:
            subprocess.Popen([str(python), "-B", "-X", "utf8", str(script), *args],
                             cwd=cwd, stdin=subprocess.DEVNULL, stdout=output,
                             stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(20):
        try:
            with opener.open("http://127.0.0.1:8765/api/status", timeout=2) as response:
                status = json.load(response)["data"]
            if status.get("qq") and status.get("gateway") == "napcat":
                print("已部署并重载监控；小鲸鱼聊天连接保持在线。")
                print("本机备份：" + str(backup))
                return
        except OSError:
            pass
        time.sleep(0.5)
    raise RuntimeError("监控重载尚未完成，请检查本机重载日志")


if __name__ == "__main__":
    main()
