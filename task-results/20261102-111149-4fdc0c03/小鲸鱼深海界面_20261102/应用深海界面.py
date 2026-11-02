"""备份并替换四个静态界面文件，核对语音配置与聊天接入设置未被改动。"""

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    root = Path(__file__).resolve().parent
    monitor = Path(r"D:\deepseek\Yu\大肥鱼_实时监控面板")
    assets = Path(r"E:\sss_test\dafeiyu_assets")
    guard = [assets / "voice_config.json", assets / "qq_gateway.json"]
    before = {path.name: digest(path) for path in guard}
    validation = json.loads((root / "预览验证.json").read_text(encoding="utf-8"))
    if (
        validation["默认可见关联数"] != validation["真实关联数"]
        or validation["网页脚本错误"]
        or validation["写入请求"]
    ):
        raise RuntimeError("界面预览未通过，不替换正式页面")
    backup = Path(r"E:\sss_test\backups") / (
        "小鲸鱼深海界面_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    files = [
        (root / "monitor" / name, monitor / name)
        for name in ("dashboard.html", "memory-map.css", "memory-map.js")
    ]
    files.append(
        (root / "桌面入口.html", Path(r"C:\Users\14431\Desktop\小鲸鱼的家.html"))
    )
    backup.mkdir(parents=True, exist_ok=True)
    changed = []
    for source, target in files:
        if digest(source) == digest(target):
            continue
        shutil.copy2(target, backup / target.name)
        temporary = target.with_suffix(target.suffix + ".new")
        shutil.copy2(source, temporary)
        temporary.replace(target)
        if digest(source) != digest(target):
            raise RuntimeError("正式文件校验失败：" + target.name)
        changed.append(target.name)
    if before != {path.name: digest(path) for path in guard}:
        raise RuntimeError("语音或聊天接入配置发生变化，需核对")
    result = {
        "备份目录": str(backup),
        "替换文件": changed,
        "语音配置未改变": True,
        "聊天接入配置未改变": True,
        "重启服务": False,
        "启动或操作聊天客户端": False,
        "上传范围": "仅本次界面代码、安装与验证脚本及汇总，不包含记忆正文和截图",
    }
    (root / "应用结果.local.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
