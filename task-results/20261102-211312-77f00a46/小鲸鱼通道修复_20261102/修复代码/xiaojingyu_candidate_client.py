"""网页明确点击后只启动已核对的独立副本，不接触原安装或其他账号。"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import psutil


CLIENT = Path(r"E:\sss\小鲸鱼QQ兼容验证\Files\QQ.exe")
VERSION = "9.9.33-52230"
EXPECTED = {
    "QQ.exe": "abbed71fc3dfe84fa712a2243041029c4a2e60b25595528522cb92c5758d388a",
    "versions/9.9.33-52230/QQNT.dll": "f6f35b8517da5c38ace8d4b6abad1abed42f61c8e706d23192a22d91c7620e59",
}


class ClientBlocked(RuntimeError):
    """范围或文件核验不符时停止，不替用户关闭或切换客户端。"""


def verify_files():
    if CLIENT.resolve() != CLIENT or not CLIENT.is_file():
        raise ClientBlocked("独立验证副本尚未准备好，启动已停止。")
    config = json.loads((CLIENT.parent / "versions/config.json").read_text(encoding="utf-8"))
    if config.get("curVersion") != VERSION:
        raise ClientBlocked("验证副本版本发生变化，需要重新核对后才能启动。")
    for relative, expected in EXPECTED.items():
        target = CLIENT.parent / relative
        if target.resolve() != target or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ClientBlocked("验证副本文件发生变化，启动已停止。")


def current():
    """只读枚举并核对完整路径，任何范围外客户端都阻止本按钮继续。"""
    mains, children = [], []
    for process in psutil.process_iter(["pid", "name"]):
        if (process.info["name"] or "").lower() != "qq.exe":
            continue
        try:
            if Path(process.exe()).resolve() != CLIENT:
                raise ClientBlocked("检测到原安装或其他客户端；请保留当前窗口，本按钮不会操作它。")
            if any(argument.startswith("--type=") for argument in process.cmdline()):
                children.append(process)
            else:
                mains.append(process)
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as error:
            raise ClientBlocked("现有客户端的运行位置无法核实，已停止启动，避免打开错误窗口。") from error
    if len(mains) > 1:
        raise ClientBlocked("检测到多个验证副本主进程，已停止连接，避免选错窗口。")
    if not mains and children:
        raise ClientBlocked("验证副本仍有退出中的进程，请稍后在本页重新核对。")
    return mains[0] if mains else None


def validate_process(pid, created):
    process = current()
    if process is None:
        raise ClientBlocked("验证副本已经退出，机器人通道尚未连接。")
    if process.pid != pid or abs(process.create_time() - created) > 0.01:
        raise ClientBlocked("验证副本进程已变化，本次连接已停止，请在本页重新核对。")
    return process


def open_once(allow_launch):
    """每次网页任务最多启动一次，失败不自动重启。"""
    verify_files()
    process = current()
    if process:
        return process, None
    if not allow_launch:
        raise ClientBlocked("尚未打开验证副本，请点击本页的“启动QQ并连接小鲸鱼”。")
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("NAPCAT_", "SNOWLUMA_"))
        and key not in {"NODE_OPTIONS", "ELECTRON_RUN_AS_NODE"}
    }
    log = Path(r"E:\sss_test\tmp/xiaojingyu_candidate_start.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as output:
        launched = subprocess.Popen(
            [str(CLIENT)], cwd=CLIENT.parent, env=environment,
            stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
        )
    process = psutil.Process(launched.pid)
    if Path(process.exe()).resolve() != CLIENT:
        raise ClientBlocked("启动结果的程序路径不符，已停止后续连接。")
    return process, launched
