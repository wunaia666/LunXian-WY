"""只连接当前明确核实的小鲸鱼进程一次，验证真实通道，不启动或切换客户端。"""

import argparse
import importlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, r"E:\sss_test\tools")
gateway = importlib.import_module("qq_gateway_runtime")
control = importlib.import_module("xiaojingyu_chat_control")
CANDIDATE = Path(r"E:\sss\小鲸鱼QQ兼容验证\Files\QQ.exe")


def verify_candidate_process(pid, created=None):
    """实际程序路径和进程生命周期同时相符，才允许进入连接分支。"""
    process = gateway.psutil.Process(pid)
    if Path(process.exe()).resolve() != CANDIDATE.resolve():
        raise RuntimeError("当前进程不是获准验证副本，停止连接")
    current_created = process.create_time()
    if created is not None and abs(current_created - created) > 0.01:
        raise RuntimeError("验证副本进程已变化，停止连接")
    return current_created


def online():
    try:
        return control.identity()
    except (OSError, ValueError, KeyError, StopIteration):
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    args = parser.parse_args()
    process_created = verify_candidate_process(args.pid)
    token = gateway.auth()

    def target():
        verify_candidate_process(args.pid, process_created)
        rows = gateway.verified_target_rows(gateway.process_rows(
            gateway.management("/api/processes", token=token)
        ))
        if len(rows) != 1 or int(rows[0]["pid"]) != args.pid:
            raise RuntimeError("当前已登录目标不符，停止本轮连接")
        return rows[0]

    row = target()
    settings = gateway.read_settings()
    if settings.get("auto_attach") or settings.get("allow_client_launch"):
        raise RuntimeError("自动连接开关不符")
    error = gateway.bridge_error(row)
    if error:
        raise RuntimeError("当前进程已有明确连接故障，停止重复加载：" + error)
    if not online() and not row.get("injected"):
        value = gateway.management(f"/api/processes/{args.pid}/load", {}, token=token)
        print(json.dumps({"阶段":"本轮目标连接已请求","接口接受":value.get("success") is True,"目标进程":args.pid},ensure_ascii=False),flush=True)
    deadline = time.monotonic() + 85
    connected = False
    while time.monotonic() < deadline:
        row = target()
        verify_candidate_process(args.pid, process_created)
        if online():
            connected = True
            control.mark_connected()
            break
        error = gateway.bridge_error(row)
        if error:
            gateway.remember_bridge_failure(row, error)
            control.save_state("failed", "机器人连接失败：" + error)
            break
        time.sleep(2)
    result = {"目标进程":args.pid,"目标账号":gateway.ACCOUNT,"机器人通道已连接":connected,
              "组件状态":row.get("status"),"错误":row.get("error",""),
              "关闭或启动客户端":False,"发送聊天消息":False,"自动接管":False}
    (Path(__file__).parent/"本轮真实连接.local.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False),flush=True)
    raise SystemExit(0 if connected else 2)


if __name__ == "__main__":
    main()
