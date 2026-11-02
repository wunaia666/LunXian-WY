"""保存本轮正式验证、素材清单和接续断点，不记录记忆正文。"""

import hashlib
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image


def read_api(path):
    with urllib.request.urlopen("http://127.0.0.1:8765" + path, timeout=15) as response:
        value = json.load(response)
    if not value.get("ok"):
        raise RuntimeError("本机接口读取失败")
    return value["data"]


def main():
    root = Path(__file__).resolve().parent
    monitor = Path(r"D:\deepseek\Yu\大肥鱼_实时监控面板")
    verification = json.loads((root / "正式验证.json").read_text(encoding="utf-8"))
    if verification["网页脚本错误"] or verification["自动写入请求"]:
        raise RuntimeError("正式界面仍存在未通过项")
    for name in ("monitor.py", "dashboard.html", "memory-map.js", "memory-map.css"):
        if (root / "monitor" / name).read_bytes() != (monitor / name).read_bytes():
            raise RuntimeError("正式代码与验证版本不一致：" + name)
    manifest = []
    for path in sorted((root / "assets").glob("whale-*.png")):
        with Image.open(path) as image:
            dimensions = list(image.size)
            alpha = image.getchannel("A").getextrema() if image.mode == "RGBA" else None
        if path.name in ("whale-blink.png", "whale-hug.png") and not (
            alpha and alpha[0] == 0 and alpha[1] == 255
        ):
            raise RuntimeError("角色透明通道未通过核对：" + path.name)
        if path.read_bytes() != (monitor / "assets" / path.name).read_bytes():
            raise RuntimeError("正式图片与生成版本不一致")
        manifest.append(
            {
                "文件": "assets/" + path.name,
                "像素": dimensions,
                "真实透明背景": bool(alpha and alpha[0] == 0),
                "字节数": path.stat().st_size,
                "摘要": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    database = read_api("/api/database")
    voice = json.loads(
        Path(r"E:\sss_test\dafeiyu_assets\voice_config.json").read_text(
            encoding="utf-8"
        )
    )
    gateway = json.loads(
        Path(r"E:\sss_test\dafeiyu_assets\qq_gateway.json").read_text(encoding="utf-8")
    )
    if (
        gateway.get("allow_client_launch")
        or gateway.get("auto_attach")
        or voice.get("speech_policy") != "occasional"
    ):
        raise RuntimeError("接入关闭状态或偶尔语音策略不符")
    result = {
        "北京时间": datetime.now(timezone(timedelta(hours=8))).isoformat(
            timespec="seconds"
        ),
        "参考作品": {
            "作者": "东方鹤白",
            "作品": "鲸宝养成日记第十三天",
            "链接": "https://www.douyin.com/video/7702103501119307496",
            "实际视频秒数": 18.934,
            "已核对画面": [
                "三维纵深与旋转",
                "多个主题星团",
                "选中后的放射状关联",
                "放大探索较小星团",
            ],
        },
        "实现": [
            "真实记忆按相同主题、正文关键词或所属分类汇聚",
            "三维坐标、视角旋转、透视、缩放、自动巡游",
            "选中显示记忆来源、归组依据与修订",
            "三组新生成角色素材已接入首页与动态展区",
            "四帧眨眼、漂浮、呼吸及场景缓慢移动",
            "角色动效与巡游可暂停，遵循减少动态效果",
        ],
        "正式验证": verification,
        "素材": manifest,
        "动态图": json.loads((root / "动态导出记录.json").read_text(encoding="utf-8")),
        "已有监控回归检查": 5,
        "新增星团数据检查": 6,
        "语音": "继续使用已认可的第十条多萝声音，平时文字、偶尔生成",
        "记忆系统": "沿用已有数据库、索引、修订和上下文实现，本次只读投影星图",
        "本次未操作聊天客户端": True,
        "本次未发送聊天消息": True,
        "本次未生成语音": True,
        "验收边界": "星团目前使用可追溯的主题和关键词规则，未将其描述成完整语义模型聚类；角色动态为逐帧及网页动画。视觉效果仍待用户实际查看反馈。",
        "上传范围": "代码、生成提示词、素材摘要与验证汇总；按既有入口规则，二进制图片、视频和参考作品留在本机",
    }
    (root / "素材清单.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (root / "本轮完成记录.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    checkpoint_path = Path(r"E:\sss_test\交接\小鲸鱼_最新接续.json")
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["上一轮接续结果"] = checkpoint["最新接续结果"]
    checkpoint["最新接续结果"] = str(root / "本轮完成记录.json")
    checkpoint["记忆入口"] = (
        "左侧记忆星海：三维主题星团，可旋转缩放，选中核对关键词、来源和修订"
    )
    checkpoint["界面改版"] = (
        "参照指定公开视频的三维星团方向；首页加入三组新生成角色素材与动态展区"
    )
    checkpoint["角色动态"] = str(root / "小鲸鱼动态展示.html")
    checkpoint["数据库"] = {
        "完整性": database["integrity"],
        "记录总数": database["total"],
        "长期保存": database["permanent"],
        "已锁定": database["pinned"],
        "过期历史": database["archived"],
        "全文索引": database["fulltext"],
    }
    temporary = checkpoint_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(checkpoint_path)
    print(
        json.dumps(
            {"正式验证": verification, "三组素材已核对": True, "断点已保存": True},
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
