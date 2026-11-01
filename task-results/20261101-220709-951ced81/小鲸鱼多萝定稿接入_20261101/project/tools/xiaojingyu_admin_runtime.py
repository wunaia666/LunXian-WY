"""由系统计划任务启动，维护管理员运行入口，不处理聊天客户端。"""

from __future__ import annotations

import ctypes
import json
import os
import time
from pathlib import Path

import psutil
from qq_gateway_runtime import hidden_start, node_processes, start_management

ROOT = Path(r"E:\sss_test")
STATE = ROOT / "tmp/xiaojingyu_admin_state.json"


def belongs(process, kind):
    """只匹配已知安装位置和完整入口，避免误停其他程序。"""
    try:
        args = process.cmdline()
        exe = process.exe().lower()
        if kind == "gateway":
            return exe == r"D:\deepseek\Yu\SnowLuma\node.exe".lower() and any(
                str(Path(r"D:\deepseek\Yu\SnowLuma\index.mjs")).lower() == arg.lower()
                for arg in args
            )
        if exe not in {
            str(ROOT / "venvs/astrbot/Scripts/pythonw.exe").lower(),
            str(ROOT / "venvs/astrbot/Scripts/python.exe").lower(),
        }:
            return False
        if kind == "guard":
            return any(
                arg.lower() == str(ROOT / "tools/xiaojingyu_guard.py").lower()
                for arg in args
            )
        if kind == "monitor":
            return any(
                arg.lower() == r"D:\deepseek\Yu\大肥鱼_实时监控面板\monitor.py".lower()
                for arg in args
            )
        return (
            any(arg.lower() == str(ROOT / "AstrBot/main.py").lower() for arg in args)
            or "main.py" in args
            and Path(process.cwd()) == ROOT / "AstrBot"
        )
    except (psutil.Error, OSError):
        return False


def main():
    if not ctypes.windll.shell32.IsUserAnAdmin():
        STATE.write_text(
            json.dumps(
                {"管理员": False, "状态": "需要系统管理员确认", "时间": time.time()},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return
    # 此入口只由单实例计划任务调用；先替换已知普通权限实例。
    for kind in ("guard", "robot", "gateway", "monitor"):
        targets = [
            p
            for p in psutil.process_iter()
            if p.pid != os.getpid() and belongs(p, kind)
        ]
        for process in targets:
            try:
                process.terminate()
            except psutil.Error:
                pass
        _, alive = psutil.wait_procs(targets, timeout=8)
        for process in alive:
            try:
                process.kill()
            except psutil.Error:
                pass
    start_management()
    process = hidden_start(
        [
            str(ROOT / "venvs/astrbot/Scripts/pythonw.exe"),
            "-B",
            "-X",
            "utf8",
            str(ROOT / "tools/xiaojingyu_guard.py"),
            "--watch",
        ],
        ROOT,
        "xiaojingyu_admin_guard.log",
    )
    STATE.write_text(
        json.dumps(
            {
                "管理员": True,
                "状态": "管理员守护已启动",
                "时间": time.time(),
                "入口进程": os.getpid(),
                "守护进程": process.pid,
                "连接管理进程": [p.pid for p in node_processes()],
                "桌面客户端自动启动": False,
                "桌面客户端自动接管": False,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    # 管理页与聊天接入分开守护：只恢复管理进程，不启动聊天客户端。
    recoveries = []
    while process.poll() is None:
        time.sleep(30)
        now = time.time()
        recoveries = [stamp for stamp in recoveries if now - stamp < 3600]
        if (
            not node_processes()
            and len(recoveries) < 3
            and (not recoveries or now - recoveries[-1] >= 180)
        ):
            start_management()
            recoveries.append(now)
        state = json.loads(STATE.read_text(encoding="utf-8"))
        state.update(
            最近检查时间=now,
            连接管理进程=[p.pid for p in node_processes()],
            管理页本小时恢复次数=len(recoveries),
        )
        STATE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    # 守护进程异常退出交给系统限次重启任务。
    raise SystemExit(process.returncode or 1)


if __name__ == "__main__":
    main()
