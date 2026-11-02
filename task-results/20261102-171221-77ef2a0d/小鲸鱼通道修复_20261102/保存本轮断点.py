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
        ],
        "验证": {"自动检查通过": 23, "候选网页状态验证": 3, "正式页面": formal,
                 "实际连接状态": status["connection"], "机器人服务": status["astrbot"]},
        "记忆数据库": {key: database.get(key) for key in ("integrity","total","permanent","pinned","fulltext")},
        "约束": {"自动启动客户端":False,"自动接管客户端":False,"自动加载":False,
                 "本轮向其他账号发送测试消息":False,"继续安装容器方案":False},
        "待处理": [] if status["qq"] else [
            "用户重新登录后的新进程仍出现首次连接60秒超时，真实机器人通道未建立",
            "原生组件在先前进程中的初始化线程退出码为1，所需接口指针未定位完整；权限和签名核验正常",
            "实际主程序记录9.9.20.36330，安装配置带商店渠道标记；用户反馈客户端自身显示已是最新版",
            "需要继续核对客户端发行构建与原生组件的兼容性；不能仅凭版本目录判断，也不能保证换版一定解决",
        ],
        "官方候选包": {"版本":candidate["版本"],"摘要已核对":True,"已安装":False,
                         "兼容性":"待实际验证"} if candidate else {"状态":"尚未完成下载与校验","已安装":False},
        "独立验证副本": independent,
        "下一步": "已请用户手动退出原窗口并启动独立验证副本；等待用户确认后，只对核实为小鲸鱼的新进程验证一次真实通道。原安装保留，后台自动接管继续关闭。",
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
        "客户端限制":"后台自动启动、自动接管和自动加载继续关闭；用户本轮已手动登录，并明确要求继续检查该账号。"})
    temporary = handoff_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(handoff,ensure_ascii=False,indent=2),encoding="utf-8")
    temporary.replace(handoff_path)
    print(json.dumps({"断点已保存":str(output),"真实聊天已连接":status["qq"],
        "数据库完整性":database.get("integrity"),"当前连接阶段":status["connection"]["phase"]},ensure_ascii=False))


if __name__ == "__main__":
    main()
