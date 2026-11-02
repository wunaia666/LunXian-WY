"""网页明确点击后只启动已核对的独立副本，不接触原安装或其他账号。"""

from __future__ import annotations

import hashlib
import json
import base64
import subprocess
import time
from datetime import datetime
from pathlib import Path

import psutil


CLIENT = Path(r"E:\sss\小鲸鱼QQ兼容验证\Files\QQ.exe")
VERSION = "9.9.33-52230"
DESKTOP_TASK = "小鲸鱼验证副本手动启动"
EXPECTED = {
    "QQ.exe": "abbed71fc3dfe84fa712a2243041029c4a2e60b25595528522cb92c5758d388a",
    "versions/9.9.33-52230/QQNT.dll": "f6f35b8517da5c38ace8d4b6abad1abed42f61c8e706d23192a22d91c7620e59",
}


class ClientBlocked(RuntimeError):
    """范围或文件核验不符时停止，不替用户关闭或切换客户端。"""


class ClientLaunchFailed(ClientBlocked):
    """桌面启动未进入可用状态，保留错误且不重试。"""


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
    mains, children, parents = [], [], {}
    for process in psutil.process_iter(["pid", "name"]):
        if (process.info["name"] or "").lower() != "qq.exe":
            continue
        try:
            if Path(process.exe()).resolve() != CLIENT:
                raise ClientBlocked("检测到原安装或其他客户端；请保留当前窗口，本按钮不会操作它。")
            parents[process.pid] = process.ppid()
            if any(argument == "--type" or argument.startswith("--type=")
                   or argument == "--crashpad-handler" for argument in process.cmdline()):
                children.append(process)
            else:
                mains.append(process)
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as error:
            raise ClientBlocked("现有客户端的运行位置无法核实，已停止启动，避免打开错误窗口。") from error
    # 同一客户端的无类型启动辅助进程仍属于同一棵进程树。
    main_ids = {process.pid for process in mains}
    def has_main_parent(process):
        seen = {process.pid}
        parent = parents.get(process.pid)
        while parent in parents and parent not in seen:
            if parent in main_ids:
                return True
            seen.add(parent)
            parent = parents.get(parent)
        return False
    roots = [process for process in mains if not has_main_parent(process)]
    if len(roots) > 1:
        raise ClientBlocked("检测到多个验证副本主进程，已停止连接，避免选错窗口。")
    if not roots and children:
        raise ClientBlocked("验证副本仍有退出中的进程，请稍后在本页重新核对。")
    return roots[0] if roots else None


def desktop_task(run=False):
    """只调用无触发器、普通权限、固定完整路径的桌面启动任务。"""
    script = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$task = Get-ScheduledTask -TaskPath '\' -TaskName '小鲸鱼验证副本手动启动'
$actions = @($task.Actions)
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$owner = $task.Principal.UserId
if ($owner -notlike 'S-1-*') {
    $owner = ([Security.Principal.NTAccount]::new($owner)).Translate([Security.Principal.SecurityIdentifier]).Value
}
if ($actions.Count -ne 1 -or
    $actions[0].Execute -ine 'E:\sss\小鲸鱼QQ兼容验证\Files\QQ.exe' -or
    $actions[0].WorkingDirectory -ine 'E:\sss\小鲸鱼QQ兼容验证\Files' -or
    $actions[0].Arguments -or @($task.Triggers | Where-Object {$null -ne $_}).Count -ne 0 -or
    $owner -ne $identity.User.Value -or
    $task.Principal.RunLevel.ToString() -ne 'Limited' -or
    $task.Principal.LogonType.ToString() -ne 'Interactive' -or
    $task.Settings.MultipleInstances.ToString() -ne 'IgnoreNew') {
    throw '桌面启动任务配置不符，已停止'
}
'''
    if run:
        script += "\nStart-ScheduledTask -InputObject $task\n"
    script += r'''
$info = Get-ScheduledTaskInfo -InputObject $task
$task = Get-ScheduledTask -TaskPath '\' -TaskName '小鲸鱼验证副本手动启动'
@{state=$task.State.ToString(); result=[long]$info.LastTaskResult;
  at=$info.LastRunTime.ToUniversalTime().ToString('o')} | ConvertTo-Json -Compress
'''
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    reply = subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
        timeout=15, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if reply.returncode:
        raise ClientBlocked("当前用户的桌面启动入口不可用，已停止；不会改用原安装客户端。")
    return json.loads(reply.stdout.lstrip("\ufeff"))


class DesktopLaunch:
    """记录桌面任务启动的固定进程，不把进程出现当成登录成功。"""

    def __init__(self, process):
        self.process = process
        self.returncode = None

    def poll(self):
        try:
            if self.process.is_running():
                return None
        except psutil.NoSuchProcess:
            pass
        self.returncode = int(desktop_task().get("result", 0))
        return self.returncode


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
    requested_at = time.time()
    desktop_task(run=True)
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        process = current()
        if process:
            return process, DesktopLaunch(process)
        state = desktop_task()
        ran_at = datetime.fromisoformat(state["at"]).timestamp()
        if ran_at >= requested_at - 2 and state["state"] != "Running":
            code = int(state["result"]) & 0xffffffff
            raise ClientLaunchFailed(f"QQ验证副本未进入登录状态，桌面启动返回0x{code:08x}；本次不会自动重启。")
        time.sleep(0.5)
    raise ClientLaunchFailed("已提交当前用户桌面启动，但尚未检测到可核对的验证副本进程；本次不会重复启动。")
