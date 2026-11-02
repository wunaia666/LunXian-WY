"""备份并部署已验证的故障识别修复，仅重载小鲸鱼后台。"""

import ast
import hashlib
import importlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
PROJECT = Path(r"E:\sss_test")
PANEL = Path(r"D:\deepseek\Yu\大肥鱼_实时监控面板")
INSTALL = Path(r"D:\deepseek\Yu\SnowLuma")
FILES = {
    "qq_gateway_runtime.py": PROJECT / "tools/qq_gateway_runtime.py",
    "xiaojingyu_connection_probe.py": PROJECT / "tools/xiaojingyu_connection_probe.py",
    "xiaojingyu_chat_control.py": PROJECT / "tools/xiaojingyu_chat_control.py",
    "monitor.py": PANEL / "monitor.py",
    "dashboard.html": PANEL / "dashboard.html",
}


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    backup = PROJECT / "backups" / ("通道故障识别_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    backup.mkdir(parents=True)
    for name, target in FILES.items():
        source = ROOT / "修复代码" / name
        if name.endswith(".py"):
            ast.parse(source.read_text(encoding="utf-8"))
        shutil.copy2(target, backup / name)
    if checksum(INSTALL / "index.mjs") != checksum(ROOT / "已核对更新包/index.mjs"):
        raise RuntimeError("一次性诊断入口尚未恢复，停止部署")
    voice = PROJECT / "dafeiyu_assets/voice_config.json"
    voice_before = checksum(voice)
    for name, target in FILES.items():
        shutil.copy2(ROOT / "修复代码" / name, target)
        if checksum(target) != checksum(ROOT / "修复代码" / name):
            raise RuntimeError("部署后文件摘要不符：" + name)
    sys.path.insert(0, str(PROJECT / "tools"))
    gateway = importlib.import_module("qq_gateway_runtime")
    control = importlib.import_module("xiaojingyu_chat_control")
    rows = gateway.verified_target_rows(gateway.process_rows(
        gateway.management("/api/processes", token=gateway.auth())
    ))
    recorded_failure = False
    if len(rows) == 1 and int(rows[0]["pid"]) == 3144:
        diagnostic = json.loads((ROOT / "组件只读结果.local.json").read_text(encoding="utf-8"))
        diagnostic = json.loads(diagnostic["output"])
        module = diagnostic["模块"][0]
        original = json.loads((ROOT / "原生恢复已领取.local.json").read_text(encoding="utf-8"))
        if module.get("初始化线程退出码") == 1 and abs(gateway.psutil.Process(3144).create_time() - original["created_at"]) < 0.01:
            message = "连接组件初始化线程已退出（错误码 1），尚未建立机器人通道。当前所需客户端接口未定位完整，需继续核对版本兼容性；当前账号无需重复扫码。"
            gateway.remember_bridge_failure(rows[0], message)
            control.save_state("failed", message)
            recorded_failure = True
    if not rows:
        control.save_state("waiting_user", "当前未检测到小鲸鱼客户端；请手动打开并登录后，再核对机器人连接。")
    settings = gateway.read_settings()
    runtime = json.loads((INSTALL / "config/runtime.json").read_text(encoding="utf-8"))
    if settings.get("auto_attach") or settings.get("allow_client_launch") or runtime.get("hookAutoLoad"):
        raise RuntimeError("自动启动或接管设置发生变化")
    if checksum(voice) != voice_before:
        raise RuntimeError("声音配置发生变化")
    value = {"阶段":"故障识别代码已部署，机器人连接尚未恢复", "备份":str(backup),
             "当前目标进程":[row["pid"] for row in rows],"旧进程故障记录已写入":recorded_failure,
             "连接程序版本":"2.3.4","临时入口已恢复":True,
             "自动启动":False,"自动接管":False,"自动加载":False,"声音配置保持":True,
             "部署文件":{name:checksum(target) for name,target in FILES.items()}}
    (ROOT / "部署结果.local.json").write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(value,ensure_ascii=False))


if __name__ == "__main__":
    main()
