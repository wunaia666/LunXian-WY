"""部署主动陪伴与阅读能力，仅重载机器人后台，保留已登录的聊天客户端。"""

import datetime
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import psutil

ROOT = Path(r"E:\sss_test")
APP = ROOT / "AstrBot"
STAGE = Path(__file__).resolve().parent
PLUGIN = APP / "data/plugins/astrbot_plugin_dafeiyu_browser"
sys.path.insert(0, str(APP))


def online():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:8765/api/status", timeout=4) as response:
        return json.load(response)["data"]


def main():
    from data.plugins.astrbot_plugin_dafeiyu_selfmod.memory import MemoryStore

    current = online()
    if not current.get("qq") or current.get("qq_account") != "3768021466":
        raise RuntimeError("小鲸鱼账号当前未在线，停止部署")
    store = MemoryStore(ROOT / "dafeiyu_assets/companion_memory.db")
    owner = json.loads((ROOT / "dafeiyu_assets/companion_owner.json").read_text(encoding="utf-8"))["session"]
    deployed = all((PLUGIN / name).exists() and (PLUGIN / name).read_bytes() == (STAGE / name).read_bytes()
                   for name in ("main.py", "_conf_schema.json", "companion_model.py", "novel_ocr.py", "fanqie.py", "initiative.py"))
    registration = store.get(owner, "initiative_registration", {})
    if deployed and registration.get("enabled") and current.get("astrbot"):
        print("本次代码已部署，主动任务已注册，机器人与聊天账号在线；未重复重载。")
        return
    workers = {c.pid for c in psutil.net_connections("tcp")
               if c.laddr.port == 6185 and c.status == "LISTEN" and c.pid}
    if len(workers) != 1:
        raise RuntimeError("机器人后台监听进程不唯一，停止重载")
    worker = psutil.Process(workers.pop())
    command = worker.cmdline()
    expected_python = str(ROOT / "venvs/astrbot/Scripts/pythonw.exe")
    if not command or command[0].lower() != expected_python.lower() or "main.py" not in command:
        raise RuntimeError("监听进程不是已核对的机器人后台")
    parent = worker.parent()
    parent_matches = bool(parent and parent.cmdline() == command)
    backup = ROOT / "backups" / ("主动与小说_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    backup.mkdir(parents=True, exist_ok=False)
    files = {name: PLUGIN / name for name in (
        "main.py", "_conf_schema.json", "companion_model.py", "novel_ocr.py", "fanqie.py", "initiative.py")}
    files["tests/test_reading_initiative.py"] = PLUGIN / "tests/test_reading_initiative.py"
    files["features.json"] = Path(r"D:\deepseek\Yu\大肥鱼_实时监控面板\features.json")
    config_path = APP / "data/config/astrbot_plugin_dafeiyu_browser_config.json"
    shutil.copy2(config_path, backup / config_path.name)
    for name, target in files.items():
        source = STAGE / name
        if name.endswith(".py"):
            compile(source.read_text(encoding="utf-8"), str(source), "exec")
        if target.exists():
            saved = backup / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix + ".pending")
        shutil.copy2(source, temp)
        os.replace(temp, target)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config.update(initiative_enabled=True, novel_background_enabled=True,
                  autonomous_enabled=True, autonomous_daily_shares=0, autonomous_cooldown_hours=0)
    temp = config_path.with_suffix(".pending")
    temp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, config_path)
    store = MemoryStore(ROOT / "dafeiyu_assets/companion_memory.db")
    store.backup()
    owner = json.loads((ROOT / "dafeiyu_assets/companion_owner.json").read_text(encoding="utf-8"))["session"]
    store.put(owner, "paused", False)
    store.put(owner, "novel_paused", False)
    pending = store.get(owner, "pending")
    if pending and time.time() - float(pending.get("ts", 0)) > 86400:
        store.put(owner, "pending_before_initiative", pending)
        store.put(owner, "pending", None)
    pause = ROOT / "tmp/xiaojingyu_guard.pause"
    created_pause = not pause.exists()
    if created_pause:
        pause.write_text("正在重载主动陪伴与阅读插件", encoding="utf-8")
    try:
        worker.terminate()
        for _ in range(16):
            if not worker.is_running():
                break
            time.sleep(0.5)
        if worker.is_running():
            raise RuntimeError("旧机器人后台未退出，未重复启动")
        if parent_matches:
            try:
                parent.terminate()
            except psutil.NoSuchProcess:
                pass
        with (ROOT / "tmp/initiative_robot_reload.log").open("ab") as output:
            subprocess.Popen(command, cwd=APP, stdin=subprocess.DEVNULL, stdout=output,
                             stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(240):
            registered = store.get(owner, "initiative_registration", {})
            if registered.get("enabled") and registered.get("registered_at", 0) > time.time() - 90:
                current = online()
                if current.get("astrbot") and current.get("qq"):
                    print("主动陪伴任务已注册，聊天账号与机器人服务均在线。")
                    print("本机备份：" + str(backup))
                    return
            time.sleep(0.5)
        raise RuntimeError("新任务尚未完成注册，请查看本机重载日志")
    finally:
        if created_pause:
            pause.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
