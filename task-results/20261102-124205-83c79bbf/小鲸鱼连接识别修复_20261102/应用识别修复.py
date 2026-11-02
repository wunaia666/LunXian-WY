"""备份部署账号识别与状态修复，不触发手动连接或修改接入权限。"""

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    root = Path(__file__).resolve().parent
    project = Path(r"E:\sss_test")
    monitor = Path(r"D:\deepseek\Yu\大肥鱼_实时监控面板")
    guard_paths = [
        project / "dafeiyu_assets/qq_gateway.json",
        project / "dafeiyu_assets/voice_config.json",
    ]
    guards = {path.name: sha(path) for path in guard_paths}
    validation = json.loads((root / "预览验证.json").read_text(encoding="utf-8"))
    if validation["网页脚本错误"] or not validation["页面阶段准确"]:
        raise RuntimeError("独立预览未通过")
    backup = (
        project
        / "backups"
        / ("已登录账号识别修复_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    )
    pairs = [
        (root / "project/tools" / name, project / "tools" / name)
        for name in ("qq_gateway_runtime.py", "xiaojingyu_connection_probe.py")
    ]
    pairs.extend(
        (root / "monitor" / name, monitor / name)
        for name in ("monitor.py", "dashboard.html")
    )
    for source, target in pairs:
        if target.exists():
            saved = (
                backup
                / ("tools" if target.parent == project / "tools" else "monitor")
                / target.name
            )
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
        temporary = target.with_suffix(target.suffix + ".new")
        shutil.copy2(source, temporary)
        temporary.replace(target)
        if sha(source) != sha(target):
            raise RuntimeError("生产文件不一致：" + source.name)
    if guards != {path.name: sha(path) for path in guard_paths}:
        raise RuntimeError("接入设置或声音配置发生变化")
    result = {
        "备份目录": str(backup),
        "部署文件数": len(pairs),
        "接入及声音配置未改变": True,
        "本轮未调用连接动作": True,
    }
    (root / "部署记录.local.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
