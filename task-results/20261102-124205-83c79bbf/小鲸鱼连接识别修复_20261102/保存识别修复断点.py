"""记录识别修复和仍待用户点击的实际接入步骤，不把未连接说成已完成。"""

import json
import urllib.request
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    verification = json.loads((root / "正式验证.json").read_text(encoding="utf-8"))
    with urllib.request.urlopen(
        "http://127.0.0.1:8765/api/status", timeout=15
    ) as response:
        status = json.load(response)["data"]
    settings = json.loads(
        Path(r"E:\sss_test\dafeiyu_assets\qq_gateway.json").read_text(encoding="utf-8")
    )
    if settings.get("allow_client_launch") or settings.get("auto_attach"):
        raise RuntimeError("自动启动或自动接管状态发生变化")
    result = {
        "问题原因": "已登录的目标客户端没有带账号启动参数，旧程序因此未选中该进程；连接组件未加载，机器人通道未启动。",
        "修复": [
            "从管理程序实际识别的账号选择目标，不只依赖启动参数",
            "未知、冲突、其他账号及多个目标均不发起接入",
            "只读区分客户端已识别、组件已加载及机器人通道在线",
            "修正旧提示，并为已识别客户端显示连接已登录账号按钮",
        ],
        "正式状态": {
            "目标客户端已识别": status.get("connection", {}).get("account")
            == "3768021466",
            "机器人已连接": status["qq"],
        },
        "已通过检查": {
            "新增账号识别检查": 9,
            "已有连接及监控回归": 13,
            "合计": 22,
            "真实界面验证": verification,
        },
        "自动启动客户端": False,
        "自动接管客户端": False,
        "本轮实际接管客户端": False,
        "本轮发送聊天消息": False,
        "后续步骤": "用户刷新网页后点击连接已登录账号，才触发目标客户端的实际接入；成功后自动检查本地数据。"
        if not status["qq"]
        else "机器人通道已由实际状态接口核对在线。",
    }
    (root / "修复结果.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    checkpoint_path = Path(r"E:\sss_test\交接\小鲸鱼_最新接续.json")
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["上一轮接续结果"] = checkpoint["最新接续结果"]
    checkpoint["最新接续结果"] = str(root / "修复结果.json")
    checkpoint["登录状态修复"] = (
        "目标客户端已识别与机器人通道在线分开显示；手动登录无需启动参数；后台不因此获得自动接入权限"
    )
    checkpoint["实际接入待办"] = result["后续步骤"]
    temporary = checkpoint_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(checkpoint_path)
    print(
        json.dumps(
            {
                "正式状态": result["正式状态"],
                "实际接入步骤": result["后续步骤"],
                "断点已保存": True,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
