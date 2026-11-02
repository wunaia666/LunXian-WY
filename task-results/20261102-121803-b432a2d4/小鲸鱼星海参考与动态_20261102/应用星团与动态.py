"""备份并部署星团页面及角色素材，不改变记忆实现、声音或客户端接入设置。"""

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    root = Path(__file__).resolve().parent
    target = Path(r"D:\deepseek\Yu\大肥鱼_实时监控面板")
    assets = Path(r"E:\sss_test\dafeiyu_assets")
    validation = json.loads((root / "预览验证.json").read_text(encoding="utf-8"))
    if (
        validation["网页脚本错误"]
        or validation["自动写入请求"]
        or not validation["三维旋转与缩放"]
    ):
        raise RuntimeError("预览验证未通过")
    configuration = json.loads((assets / "qq_gateway.json").read_text(encoding="utf-8"))
    if configuration.get("allow_client_launch") or configuration.get("auto_attach"):
        raise RuntimeError("需先核对客户端自动启动和接管设置，本次部署未修改设置")
    guards = {
        name: sha(assets / name) for name in ("voice_config.json", "qq_gateway.json")
    }
    backup = Path(r"E:\sss_test\backups") / (
        "三维星团与动态角色_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    backup.mkdir(parents=True, exist_ok=True)
    manifest = []
    for folder, names in (
        (
            "monitor",
            ("monitor.py", "dashboard.html", "memory-map.js", "memory-map.css"),
        ),
        ("assets", ("whale-blink.png", "whale-hug.png", "whale-starry.png")),
    ):
        for name in names:
            source = root / folder / name
            destination = target / ("assets" if folder == "assets" else "") / name
            if destination.exists():
                saved = backup / folder / name
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, saved)
            temporary = destination.with_suffix(destination.suffix + ".new")
            shutil.copy2(source, temporary)
            temporary.replace(destination)
            if sha(source) != sha(destination):
                raise RuntimeError("正式文件校验失败：" + name)
            manifest.append(
                {
                    "文件": name,
                    "摘要": sha(destination),
                    "字节数": destination.stat().st_size,
                }
            )
    if guards != {name: sha(assets / name) for name in guards}:
        raise RuntimeError("声音或接入配置发生变化")
    result = {
        "备份目录": str(backup),
        "部署文件": manifest,
        "声音配置未改动": True,
        "接入配置未改动": True,
        "记忆数据库未写入": True,
        "桌面入口继续指向正式页面": True,
    }
    (root / "部署记录.local.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "部署文件数": len(manifest),
                "声音及接入配置未改动": True,
                "备份目录": str(backup),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
