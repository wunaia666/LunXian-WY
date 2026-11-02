"""保存静态界面发布证据和接续断点，仅记录统计，不保存记忆正文。"""

import hashlib
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


def read_api(path):
    with urllib.request.urlopen("http://127.0.0.1:8765" + path, timeout=15) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError("本机接口读取失败：" + path)
    return result["data"]


def main():
    root = Path(__file__).resolve().parent
    monitor = Path(r"D:\deepseek\Yu\大肥鱼_实时监控面板")
    validation = json.loads((root / "正式界面验证.json").read_text(encoding="utf-8"))
    deployment = json.loads((root / "应用结果.local.json").read_text(encoding="utf-8"))
    if validation["网页脚本错误"] or validation["写入请求"]:
        raise RuntimeError("正式界面验证尚未通过")
    digests = {}
    for name in ("dashboard.html", "memory-map.css", "memory-map.js"):
        source = hashlib.sha256((root / "monitor" / name).read_bytes()).hexdigest()
        live = hashlib.sha256((monitor / name).read_bytes()).hexdigest()
        if source != live:
            raise RuntimeError("正式页面与已检查的版本不一致：" + name)
        digests[name] = live
    desktop = Path(r"C:\Users\14431\Desktop\小鲸鱼的家.html")
    if desktop.read_bytes() != (root / "桌面入口.html").read_bytes():
        raise RuntimeError("桌面入口版本不一致")
    database = read_api("/api/database")
    result = {
        "北京时间": datetime.now(timezone(timedelta(hours=8))).isoformat(
            timespec="seconds"
        ),
        "完成事项": [
            "控制台整体更换为小鲸鱼深海陪伴舱风格",
            "沿用原角色素材并加入鲸鱼标识、舷窗、波纹与星海",
            "真实分类和主题关系以清晰弧线绘制，点选后高亮到中心的路径",
            "支持标签展开、动效开关、沉浸全屏、拖动、键盘与列表查看",
            "手机使用独立星域布局并为工具栏留出空间",
            "桌面入口同步更换主题",
        ],
        "正式文件摘要": digests,
        "正式界面验证": validation,
        "本次保留": {
            "原七个栏目及功能入口": True,
            "已确认的第十条声音及偶尔生成策略": True,
            "现有记忆数据库和检索实现": True,
            "聊天客户端自动启动与自动接管关闭": True,
        },
        "本轮运行操作": {
            "重启服务": False,
            "操作聊天客户端": False,
            "发送聊天消息": False,
            "生成语音": False,
        },
        "验收边界": "真实数据与界面功能已验证；本次视觉效果仍以用户实际查看后的反馈为准。",
        "备份目录": deployment["备份目录"],
    }
    output = root / "改版结果.json"
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    checkpoint_path = Path(r"E:\sss_test\交接\小鲸鱼_最新接续.json")
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["上一轮接续结果"] = checkpoint["最新接续结果"]
    checkpoint["最新接续结果"] = str(output)
    checkpoint["记忆入口"] = (
        "左侧记忆星海；清晰真实连线、路径高亮、沉浸全屏、列表及来源修订"
    )
    checkpoint["界面改版"] = (
        "小鲸鱼深海陪伴舱，桌面入口与正式页面已同步；等待用户视觉反馈"
    )
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
            {"正式文件数": 4, "界面验证": validation, "断点已保存": True},
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
