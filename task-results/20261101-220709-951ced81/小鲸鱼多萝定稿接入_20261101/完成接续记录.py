"""将选声接入的最终检查结果写回断点，保留未验收范围及审批拦截事实。"""

import hashlib
import json
import shutil
from pathlib import Path


def main():
    folder = Path(__file__).resolve().parent
    root = Path(r"E:\sss_test")
    monitor = Path(r"D:\deepseek\Yu\大肥鱼_实时监控面板")
    for source in (folder / "project").rglob("*"):
        if source.is_file() and source.suffix in {".py", ".sh"}:
            target = root / source.relative_to(folder / "project")
            shutil.copy2(source, target)
            if (
                hashlib.sha256(target.read_bytes()).digest()
                != hashlib.sha256(source.read_bytes()).digest()
            ):
                raise RuntimeError("安装代码与完成快照不一致")
    for name in ("monitor.py", "dashboard.html"):
        shutil.copy2(folder / "monitor" / name, monitor / name)
    path = folder / "接续结果.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    result["回归检查"] = (
        "五项新增检查、六项现有原声保护检查通过；监控浏览器只读检查通过；启动脚本语法检查通过"
    )
    result["监控验证"] = json.loads(
        (folder / "监控界面验证结果.json").read_text(encoding="utf-8")
    )
    result["额外启动验证"] = (
        "自动审批因可能恢复旧语音后端而拦截了再次调用启动入口的命令；未绕过或重试，改用健康接口、端口与已安装脚本的只读检查"
    )
    result["管理员服务重载"] = (
        "沿用现有管理员计划任务，机器人与监控已重新加载；没有重新安装、弹权限窗口或操作桌面聊天客户端"
    )
    result["其他模块"] = "聊天接入配置摘要未变，记忆数据库未修改"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    installation_path = folder / "安装结果.local.json"
    installation = json.loads(installation_path.read_text(encoding="utf-8"))
    installation.update(
        服务验证="已就绪，真实合成与第十条逐字节一致",
        安装文件数=10,
        监控已刷新=True,
        机器人已重载=True,
    )
    installation_path.write_text(
        json.dumps(installation, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    path = Path(r"E:\sss\多萝原视频重做_20261101\接续断点.json")
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    checkpoint["真实状态"] = (
        "用户已接受并指定采用第十条试听；已接入日常合成且复现相同波形。其他候选、其他情绪语速及分钟级稳定性不据此视为通过。"
    )
    checkpoint["生产配置"] = (
        "日常语音已按最新明确选声切到原多萝训练配对与生日对白参考，旧配置和代码已备份；聊天接入配置与记忆未改动"
    )
    checkpoint["下一步"] = [
        "沿用用户已确认的第十条声音，不继续自动更换参考或堆叠候选",
        "后续仅根据新文本的具体问题调整；其他情绪和分钟级长语音仍需独立试听验收",
    ]
    checkpoint["分开提供参考实验"]["下一步"] = (
        "用户已选择现有第十条声音，该未完成实验不作为当前日常接入的必要步骤，不继续自动试验"
    )
    path.write_text(
        json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("已保存准确的已确认状态、安装代码与最终检查证据。")


if __name__ == "__main__":
    main()
