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
            "按同一副本进程树归并无类型辅助进程，多个独立主进程仍停止接入",
            "旧多进程提示在对应进程退出后明确标为上次启动失败，不冒充当前仍有多开",
            "网页启动改为当前用户普通桌面的固定按需任务，无定时或登录触发器，原安装不操作",
            "只有进程出现时显示等待初始化，尚未识别登录窗口不提示扫码",
            "同一网页接口实测限次启动，副本异常退出能显示实际错误码且不会自动重启",
        ],
        "验证": {"自动检查通过": 46, "网页脚本语法检查":"通过",
                 "本轮正式页面只读核对":"启动按钮和四步进度已实际提供",
                 "本轮网页实际点击验证":"用户截图确认启动失败；修复后通过网页同一接口限次实测，副本返回0x80000003，页面准确显示启动失败",
                 "普通桌面对照":"两种描述符与两种访问方式共四次临时窗口站创建均成功；临时对象均已关闭",
                 "副本调用实测":"普通桌面下两次创建调用均返回空句柄、系统错误5，随后在QQNT.dll偏移0x26b6e3a退出；访问控制表与成功对照一致",
                 "运行身份核对":"同一普通桌面会话，无应用程序包身份；进程身份限制标记与成功对照一致，未发现线程模拟身份",
                 "上一轮正式故障页面验证": formal,
                 "实际连接状态": status["connection"], "机器人服务": status["astrbot"]},
        "记忆数据库": {key: database.get(key) for key in ("integrity","total","permanent","pinned","fulltext")},
        "约束": {"自动启动客户端":False,"自动接管客户端":False,"自动加载":False,
                 "本轮向其他账号发送测试消息":False,"继续安装容器方案":False},
        "待处理": [] if status["qq"] else [
            "独立副本创建隔离窗口站失败，普通桌面调用实测两次均返回系统错误5，初始化返回12，并以0x80000003退出；具体进程级差异尚未确定",
            "网页登录入口与失败反馈已实际核对，但副本尚未进入可用登录状态，扫码、账号识别与机器人连通仍未通过",
            "先前原安装进程出现首次连接60秒超时；这不能证明已修好的网页入口能够建立新通道",
            "普通桌面成功对照与QQ使用同一访问控制表和相同身份限制标记；不能把故障简单归因于管理员权限、应用程序包身份、版本或中文路径，不修改系统安全设置或关闭隔离保护",
        ],
        "官方候选包": {"版本":candidate["版本"],"摘要已核对":True,"已安装":False,
                         "兼容性":"尚未通过运行与机器人连接验证"} if candidate else {"状态":"尚未完成下载与校验","已安装":False},
        "独立验证副本": {**(independent or {}),"网页入口已接入":True,"运行已验收":False,
                         "本轮已实际试启动":True,"启动客户端":True,"本轮操作扫码":False,
                         "当前运行":bool(status["connection"].get("client_detected")),
                         "兼容性":"本机登录前初始化失败，返回0x80000003，尚不可用于聊天"},
        "本轮授权": "用户允许仅启动和调试独立验证副本，扫码由用户完成；原安装及其他账号不操作",
        "停止点": "网页启动和失败反馈修复已部署；固定副本初始化仍失败，停止反复试启动，原始诊断仅保存在本机。聊天未连接。",
        "下一步": "先核对QQ自身的窗口站创建为何被拒绝，或在获准副本目录对照已核验官方候选；普通桌面同访问控制表与身份标记的对照可成功。修复启动后再通过网页限次验证登录和机器人通道，不再要求用户重复双击文件或扫码，不操作原安装和其他账号。",
    }
    output = ROOT / "修复验证结果.json"
    output.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    handoff_path = PROJECT / "交接/小鲸鱼_最新接续.json"
    handoff = read(handoff_path)
    if handoff.get("最新接续结果") != str(output):
        handoff["上一轮接续结果"] = handoff.get("最新接续结果")
    handoff.update({"最新接续结果":str(output),"实际接入待办":data["待处理"],
        "本轮接续断点":data["下一步"],"聊天通道已连接":bool(status["qq"]),
        "连接组件版本":"2.3.4","用户最新纠正":"用户截图确认验证副本启动崩溃，网页先前同时显示多个主进程；不能称聊天已修好",
        "客户端限制":"后台自动启动、自动接管和自动加载继续关闭；固定副本仅按需启动与调试，扫码由用户完成。按需桌面任务无触发器；临时诊断任务已移除，不操作原安装及其他账号。"})
    temporary = handoff_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(handoff,ensure_ascii=False,indent=2),encoding="utf-8")
    temporary.replace(handoff_path)
    print(json.dumps({"断点已保存":str(output),"真实聊天已连接":status["qq"],
        "数据库完整性":database.get("integrity"),"当前连接阶段":status["connection"]["phase"]},ensure_ascii=False))


if __name__ == "__main__":
    main()
