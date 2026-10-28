"""客户端连接层的静默启动与目标进程接管；首次条款必须先完成确认。"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import psutil

ROOT = Path(r"E:\sss_test")
SETTINGS = ROOT / "dafeiyu_assets/qq_gateway.json"
TARGET = Path(r"D:\deepseek\Yu\SnowLuma")
QQ = Path(r"C:\Program Files\Tencent\QQNT\QQ.exe")
ACCOUNT = "3768021466"
RECOVERY = ROOT / "tmp/qq_gateway_guard_state.json"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def read_settings():
    return (
        json.loads(SETTINGS.read_text(encoding="utf-8"))
        if SETTINGS.exists()
        else {"provider": "napcat"}
    )


def management(path, payload=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(
        "http://127.0.0.1:5099" + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers=headers,
    )
    try:
        with OPENER.open(request, timeout=4) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        try:
            return json.load(error)
        except ValueError:
            return {"success": False, "http_status": error.code}


def auth():
    secret = json.loads((TARGET / ".local_admin.json").read_text(encoding="utf-8"))[
        "password"
    ]
    result = management("/api/login", {"password": secret})
    if not result.get("success") or not result.get("token"):
        raise RuntimeError("新连接程序管理认证未通过")
    return result["token"]


def hidden_start(command, cwd, log_name, env=None):
    startup = subprocess.STARTUPINFO()
    startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    with (ROOT / "tmp" / log_name).open("ab") as output:
        return subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
            startupinfo=startup,
        )


def node_processes():
    result = []
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if (process.info["name"] or "").lower() == "node.exe" and str(
                TARGET / "index.mjs"
            ).lower() in [item.lower() for item in process.info["cmdline"] or []]:
                result.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return result


def start_management():
    if node_processes():
        return
    secret = json.loads((TARGET / ".local_admin.json").read_text(encoding="utf-8"))[
        "password"
    ]
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("NAPCAT_") and not key.startswith("SNOWLUMA_ACCEPT_")
    }
    env.update(
        SNOWLUMA_HOOK_AUTOLOAD="0",
        SNOWLUMA_WEBUI_HOST="127.0.0.1",
        SNOWLUMA_WEBUI_PORT="5099",
        SNOWLUMA_TELEMETRY="0",
        SNOWLUMA_WEBUI_BOOTSTRAP_PASSWORD=secret,
    )
    hidden_start(
        [str(TARGET / "node.exe"), str(TARGET / "index.mjs")],
        TARGET,
        "snowluma_runtime.log",
        env,
    )


def target_main_processes():
    rows = []
    for process in psutil.process_iter(["pid", "name", "cmdline", "exe"]):
        try:
            args = process.info["cmdline"] or []
            if (process.info["name"] or "").lower() == "qq.exe" and not any(
                item.startswith("--type=") for item in args
            ):
                if (
                    "-q" in args
                    and args.index("-q") + 1 < len(args)
                    and args[args.index("-q") + 1] == ACCOUNT
                ):
                    rows.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return rows


def ensure(dry_run=False, manual=False):
    settings = read_settings()
    if settings.get("provider") != "snowluma":
        return {"状态": "旧连接层仍在使用"}
    if not manual and (
        settings.get("state") == "paused_by_user"
        or settings.get("auto_attach") is False
    ):
        return {
            "状态": "接入已暂停，普通客户端自动登录与接管已关闭"
            if settings.get("state") == "paused_by_user"
            else "手动启动模式，后台自动启动与接管保持关闭"
        }
    if not node_processes():
        if dry_run:
            return {"状态": "新连接程序需要启动"}
        start_management()
        return {"状态": "新连接程序启动中"}
    token = auth()
    agreements = management("/api/agreements", token=token)
    if agreements.get("consentRequired") or (agreements.get("data") or {}).get(
        "consentRequired"
    ):
        return {"状态": "等待首次使用条款确认"}
    targets = target_main_processes()
    if not targets:
        if not manual and settings.get("allow_client_launch") is False:
            return {"状态": "普通客户端自动启动已关闭"}
        if any(
            (process.info["name"] or "").lower() == "qq.exe"
            for process in psutil.process_iter(["name"])
        ):
            return {"状态": "存在其他聊天进程，等待选择目标账号"}
        if dry_run:
            return {"状态": "目标客户端需要启动"}
        recovery = (
            json.loads(RECOVERY.read_text(encoding="utf-8"))
            if RECOVERY.exists()
            else {}
        )
        launches = [
            stamp
            for stamp in recovery.get("launches", [])
            if time.time() - stamp < 3600
        ]
        if launches and time.time() - launches[-1] < 600:
            return {"状态": "客户端恢复冷却中，避免反复弹窗"}
        if len(launches) >= 2:
            return {"状态": "客户端本小时恢复次数已达上限"}
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("NAPCAT_")
        }
        process = hidden_start(
            [str(QQ), "-q", ACCOUNT], QQ.parent, "snowluma_qq.log", env
        )
        RECOVERY.write_text(
            json.dumps({"launches": launches + [time.time()]}), encoding="utf-8"
        )
        return {"状态": "目标客户端启动中", "进程": process.pid}
    if len(targets) != 1:
        return {"状态": "目标主进程不唯一，等待核对"}
    pid = targets[0].pid
    listing = management("/api/processes", token=token)
    rows = listing.get("list") or listing.get("processes") or listing.get("data") or []
    if isinstance(rows, dict):
        rows = rows.get("processes") or []
    selected = (
        next((row for row in rows if str(row.get("pid")) == str(pid)), {})
        if isinstance(rows, list)
        else {}
    )
    status = str(selected.get("status", "")).lower()
    if selected.get("injected") or status in {
        "loaded",
        "connected",
        "ready",
        "online",
        "connecting",
        "loading",
        "injecting",
        "observing",
        "passive",
    }:
        return {"状态": "新连接程序已接管目标进程", "进程": pid}
    if dry_run:
        return {"状态": "等待接管目标进程", "进程": pid}
    result = management("/api/processes/" + str(pid) + "/load", {}, token=token)
    return {
        "状态": "已请求新程序接管目标进程"
        if result.get("success")
        else "目标接管尚未成功",
        "进程": pid,
    }


if __name__ == "__main__":
    print(json.dumps(ensure(), ensure_ascii=False))
