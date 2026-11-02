"""按摘要备份并部署桌面启动修复，不直接启动聊天客户端。"""

import ast
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
PROJECT = Path(r"E:\sss_test")
FILES = ["xiaojingyu_candidate_client.py", "xiaojingyu_chat_control.py"]


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    baseline = json.loads((ROOT / "网页登录部署.local.json").read_text(encoding="utf-8"))["文件"]
    settings = json.loads((PROJECT / "dafeiyu_assets/qq_gateway.json").read_text(encoding="utf-8"))
    runtime = json.loads(Path(r"D:\deepseek\Yu\SnowLuma\config\runtime.json").read_text(encoding="utf-8"))
    if settings.get("auto_attach") or settings.get("allow_client_launch") or runtime.get("hookAutoLoad"):
        raise RuntimeError("自动接入开关不符，停止部署")
    sys.path.insert(0, str(ROOT / "修复代码"))
    import xiaojingyu_candidate_client as candidate

    candidate.verify_files()
    if candidate.current() is not None:
        raise RuntimeError("客户端正在运行，停止覆盖启动模块")
    task = candidate.desktop_task()
    for name in FILES:
        target = PROJECT / "tools" / name
        if checksum(target) != baseline[name]:
            raise RuntimeError("生产文件已有其他改动，停止覆盖：" + name)
        ast.parse((ROOT / "修复代码" / name).read_text(encoding="utf-8"))
    backup = PROJECT / "backups" / ("普通桌面启动修复_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    backup.mkdir(parents=True)
    for name in FILES:
        target = PROJECT / "tools" / name
        shutil.copy2(target, backup / name)
        temporary = target.with_suffix(".py.桌面部署.tmp")
        shutil.copy2(ROOT / "修复代码" / name, temporary)
        temporary.replace(target)
        if checksum(target) != checksum(ROOT / "修复代码" / name):
            raise RuntimeError("部署后摘要不符：" + name)
    result = {"时间": datetime.now().isoformat(timespec="seconds"), "备份": str(backup),
              "文件": {name: checksum(PROJECT / "tools" / name) for name in FILES},
              "任务状态": task["state"], "自动触发器": False, "启动QQ": False}
    (ROOT / "桌面启动部署.local.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
