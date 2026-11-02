"""备份并部署网页显式登录入口，只重载监控后台，不启动聊天客户端。"""

import ast
import hashlib
import json
import shutil
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
PROJECT = Path(r"E:\sss_test")
PANEL = Path(r"D:\deepseek\Yu\大肥鱼_实时监控面板")
FILES = {
    "xiaojingyu_candidate_client.py": PROJECT/"tools/xiaojingyu_candidate_client.py",
    "xiaojingyu_chat_control.py": PROJECT/"tools/xiaojingyu_chat_control.py",
    "monitor.py": PANEL/"monitor.py",
    "dashboard.html": PANEL/"dashboard.html",
}


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def migrate_start_state(backup):
    """保留旧失败证据，防止上一轮原客户端的进度挡住新的网页入口。"""
    state_path = PROJECT/"tmp/xiaojingyu_chat_start.json"
    if not state_path.exists():
        return
    previous = json.loads(state_path.read_text(encoding="utf-8"))
    if previous.get("client") == "verified_copy":
        return
    shutil.copy2(state_path,backup/"旧启动状态.json")
    value = {"phase":"idle","message":"网页登录入口已就绪，点击“启动QQ并连接小鲸鱼”继续。",
             "at":time.time(),"step":0,"client":"verified_copy"}
    temporary = state_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    temporary.replace(state_path)


def main():
    previous = json.loads((ROOT/"部署结果.local.json").read_text(encoding="utf-8"))["部署文件"]
    settings = json.loads((PROJECT/"dafeiyu_assets/qq_gateway.json").read_text(encoding="utf-8"))
    runtime = json.loads(Path(r"D:\deepseek\Yu\SnowLuma\config\runtime.json").read_text(encoding="utf-8"))
    if settings.get("auto_attach") or settings.get("allow_client_launch") or runtime.get("hookAutoLoad"):
        raise RuntimeError("自动接入约束不符，停止部署")
    for name,target in FILES.items():
        if name in previous and checksum(target) != previous[name]:
            raise RuntimeError("生产文件有其他修改，停止覆盖："+name)
        if name not in previous and target.exists():
            raise RuntimeError("新增入口已存在，停止覆盖")
        if name.endswith(".py"):
            ast.parse((ROOT/"修复代码"/name).read_text(encoding="utf-8"))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:8765/api/status",timeout=15) as response:
        status = json.load(response)["data"]
    if status.get("service") != "xiaojingyu-monitor":
        raise RuntimeError("当前监听者不是小鲸鱼监控，停止部署")
    backup = PROJECT/"backups"/("网页验证副本登录_"+datetime.now().strftime("%Y%m%d_%H%M%S"))
    backup.mkdir(parents=True)
    for name,target in FILES.items():
        if target.exists():
            shutil.copy2(target,backup/name)
        temporary = target.with_suffix(target.suffix+".网页部署.tmp")
        shutil.copy2(ROOT/"修复代码"/name,temporary)
        temporary.replace(target)
        if checksum(target) != checksum(ROOT/"修复代码"/name):
            raise RuntimeError("部署后摘要不符："+name)
    migrate_start_state(backup)
    result = {"部署时间":datetime.now().isoformat(timespec="seconds"),"备份":str(backup),
              "文件":{name:checksum(path) for name,path in FILES.items()},
              "自动启动":False,"自动接管":False,"自动加载":False,
              "启动聊天客户端":False,"等待用户网页点击":True}
    (ROOT/"网页登录部署.local.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()
