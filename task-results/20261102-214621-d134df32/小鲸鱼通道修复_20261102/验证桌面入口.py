"""通过网页同一接口限次核对桌面启动，不操作窗口、不发送聊天。"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).parent
PROJECT = Path(r"E:\sss_test")
URL = "http://127.0.0.1:8765"
OPENER = build_opener(ProxyHandler({}))


def fetch(path, payload=None, nonce=""):
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(URL + path, data=data, headers={"Content-Type": "application/json",
                      "Origin": URL, "X-Local-Control": nonce})
    with OPENER.open(request, timeout=20) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError("监控接口未接受本次核对")
    return result["data"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-once", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(PROJECT / "tools"))
    import xiaojingyu_candidate_client as candidate

    candidate.verify_files()
    control = fetch("/api/control")
    task = candidate.desktop_task()
    result = {"时间": datetime.now().isoformat(timespec="seconds"), "启动请求次数": 0,
              "启动前": control["start"], "任务状态": task["state"], "阶段": [],
              "操作窗口": False, "发送聊天": False}
    if args.start_once:
        if candidate.current() is not None:
            raise RuntimeError("已有验证副本，不再创建测试窗口")
        result["阶段"].append(fetch("/api/chat/start", {"mode": "candidate_login"}, control["nonce"]))
        result["启动请求次数"] = 1
        for _ in range(20):
            time.sleep(1.5)
            phase = fetch("/api/control")["start"]
            if phase["phase"] != result["阶段"][-1]["phase"]:
                result["阶段"].append(phase)
                print(json.dumps({"阶段": phase["phase"], "说明": phase["message"]}, ensure_ascii=False), flush=True)
            if phase["phase"] in {"launch_failed", "failed", "attention", "online"}:
                break
    final = fetch("/api/status")
    result.update(最终启动状态=final["chat_start"], 实际连接=final["connection"],
                  真实聊天在线=final["qq"], 机器人服务=final["astrbot"])
    process = candidate.current()
    result["副本运行"] = process is not None
    if process:
        result["副本运行秒数"] = round(time.time() - process.create_time(), 1)
        result["副本完整路径"] = process.exe()
        result["副本进程号"] = process.pid
    output = ROOT / "桌面入口实际核对.local.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
