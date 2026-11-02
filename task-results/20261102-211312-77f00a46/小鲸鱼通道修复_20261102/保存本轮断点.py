"""保存真实运行状态和未完成事项，不把界面修复当成聊天连接完成。"""

import json
import urllib.request
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).parent
PROJECT = Path(r"E:\sss_test")
INSTALL = Path(r"D:\deepseek\Yu\SnowLuma")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def fetch(path):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:8765" + path, timeout=15) as response:
        return json.load(response)["data"]


def main():
    status = fetch("/api/status")
    database = fetch("/api/database")
    settings = read(PROJECT / "dafeiyu_assets/qq_gateway.json")
    runtime = read(INSTALL / "config/runtime.json")
    if settings.get("auto_attach") or settings.get("allow_client_launch") or runtime.get("hookAutoLoad"):
        raise RuntimeError("自动接入限制发生变化，停止记录为通过")
    formal = read(ROOT / "页面正式验证.json")
    candidate_path = ROOT / "官方候选核对.local.json"
    candidate = read(candidate_path) if candidate_path.exists() else None
    copy_path = ROOT / "独立副本准备结果.local.json"
    independent = read(copy_path) if copy_path.exists() else None
    data = {
        "记录时间": datetime.now().isoformat(timespec="seconds"),
        "本轮代码修复": "已部署并通过检查",
        "整体聊天连接完成": bool(status["qq"]),
        "已完成": [
            "连接程序经官方更新器升级至 2.3.4，更新包摘要与官方记录相符",
            "故障状态优先于已加载标志，失败不会继续冒充通道待就绪",
            "同一客户端进程的失败记录在后台重启后仍可核对，新进程不会套用旧故障",
            "已识别账号等待机器人通道时不再被提示重复扫码",
            "手动连接时可刷新未识别账号，仅在无通信管道时进入官方只读刷新分支",
            "查看连接故障不会自动发起重新加载",
            "网页新增显式启动独立QQ验证副本的入口，完整路径和官方文件摘要固定核对",
            "网页显示打开窗口、识别账号、连接真实通道和检查本地数据四步进度",
            "识别小鲸鱼账号后自动开始只读数据检查；真实在线后重新核对检查结果",
            "每次网页任务最多启动一次，重复点击复用任务；客户端退出会显示失败，不自动重启",
            "保留旧启动失败证据，避免旧客户端进度阻挡新网页入口",
        ],
        "验证": {"自动检查通过": 37, "网页脚本语法检查":"通过",
                 "本轮正式页面只读核对":"启动按钮和四步进度已实际提供",
                 "本轮网页实际点击验证":"用户按退出键停止界面操作，尚未完成",
                 "上一轮正式故障页面验证": formal,
                 "实际连接状态": status["connection"], "机器人服务": status["astrbot"]},
        "记忆数据库": {key: database.get(key) for key in ("integrity","total","permanent","pinned","fulltext")},
        "约束": {"自动启动客户端":False,"自动接管客户端":False,"自动加载":False,
                 "本轮向其他账号发送测试消息":False,"继续安装容器方案":False},
        "待处理": [] if status["qq"] else [
            "独立副本此前启动在创建隔离窗口站时失败，实测返回12、系统错误5；自动调试和普通桌面启动尝试均在相同位置退出",
            "网页登录入口现已接入，但完整网页点击、用户扫码和机器人连通仍待实际验证",
            "先前原安装进程出现首次连接60秒超时；这不能证明已修好的网页入口能够建立新通道",
            "未确认问题仅由客户端版本、应用程序包身份或中文路径导致，不修改系统安全设置或关闭隔离保护",
        ],
        "官方候选包": {"版本":candidate["版本"],"摘要已核对":True,"已安装":False,
                         "兼容性":"尚未通过运行与机器人连接验证"} if candidate else {"状态":"尚未完成下载与校验","已安装":False},
        "独立验证副本": {**(independent or {}),"网页入口已接入":True,"运行已验收":False,
                         "兼容性":"尚待从网页启动、扫码与机器人连接的完整验证"},
        "本轮授权": "用户允许仅启动和调试独立验证副本，扫码由用户完成；原安装及其他账号不操作",
        "停止点": "用户按退出键停止电脑界面操作，已停止所有界面输入；只保存代码与真实状态",
        "下一步": "从桌面“小鲸鱼的家.html”进入监控并刷新，点击“启动QQ并连接小鲸鱼”；核对真实副本路径及窗口存活，扫码由用户完成，识别固定账号后只请求接入一次。页面显示机器人通道在线前不能宣布聊天修好。",
    }
    output = ROOT / "修复验证结果.json"
    output.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    handoff_path = PROJECT / "交接/小鲸鱼_最新接续.json"
    handoff = read(handoff_path)
    if handoff.get("最新接续结果") != str(output):
        handoff["上一轮接续结果"] = handoff.get("最新接续结果")
    handoff.update({"最新接续结果":str(output),"实际接入待办":data["待处理"],
        "本轮接续断点":data["下一步"],"聊天通道已连接":bool(status["qq"]),
        "连接组件版本":"2.3.4","用户最新纠正":"客户端自身显示已是最新版，不能要求用户重复点击更新",
        "客户端限制":"后台自动启动、自动接管和自动加载继续关闭；用户允许仅通过网页显式启动与调试独立验证副本，扫码由用户完成；本轮电脑界面操作已由用户停止。"})
    temporary = handoff_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(handoff,ensure_ascii=False,indent=2),encoding="utf-8")
    temporary.replace(handoff_path)
    print(json.dumps({"断点已保存":str(output),"真实聊天已连接":status["qq"],
        "数据库完整性":database.get("integrity"),"当前连接阶段":status["connection"]["phase"]},ensure_ascii=False))


if __name__ == "__main__":
    main()
