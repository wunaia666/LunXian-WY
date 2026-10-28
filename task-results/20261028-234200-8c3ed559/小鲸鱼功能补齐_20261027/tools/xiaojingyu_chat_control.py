"""由本机监控按钮显式启动聊天，后台守护不因此获得自动接管权限。"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path

import qq_gateway_runtime as gateway

ROOT = Path(r"E:\sss_test")
STATE = ROOT / "tmp/xiaojingyu_chat_start.json"
LOCK = threading.Lock()
TASK = None


def identity():
    """同时核对在线状态和固定机器人账号，不把管理页在线当作聊天在线。"""
    config = json.loads(
        (ROOT / "napcat/shell/config/onebot11_3768021466.json").read_text(
            encoding="utf-8"
        )
    )
    endpoint = next(
        x
        for x in config["network"]["httpServers"]
        if x.get("enable") and x.get("host") in {"127.0.0.1", "localhost"}
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    result = {}
    for action in ("get_status", "get_login_info"):
        request = urllib.request.Request(
            f"http://127.0.0.1:{int(endpoint['port'])}/{action}",
            headers={"Authorization": "Bearer " + endpoint.get("token", "")},
        )
        with opener.open(request, timeout=2) as response:
            value = json.load(response)
        if value.get("retcode") != 0:
            return False
        result[action] = value.get("data") or {}
    return (
        result["get_status"].get("online") is True
        and str(result["get_login_info"].get("user_id")) == gateway.ACCOUNT
    )


def save_state(phase, message):
    """原子保存启动进度，不记录连接凭据。"""
    state = {"phase": phase, "message": message, "at": time.time()}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(STATE)
    return state


def mark_connected():
    """只恢复本次连接状态，保留后台自动接管关闭。"""
    settings = gateway.read_settings()
    settings.update(
        state="manual_started", auto_attach=False, allow_client_launch=False
    )
    temp = gateway.SETTINGS.with_suffix(".tmp")
    temp.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temp.replace(gateway.SETTINGS)
    return save_state("online", "小鲸鱼账号已连接，可以开始聊天。")


def status():
    """返回当前这一次启动的状态，进程中断不冒充仍在执行。"""
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {"phase": "idle", "message": "点击启动，连接小鲸鱼聊天。", "at": 0}
    if (
        data["phase"] == "starting"
        and not (TASK and TASK.is_alive())
        and time.time() - data["at"] > 10
    ):
        data.update(phase="interrupted", message="上次启动已中断，可以重新点击核对。")
    return data


def start():
    """按钮重复点击复用同一任务，首次启动最多观察两分钟，不循环弹登录窗口。"""
    global TASK
    with LOCK:
        if TASK and TASK.is_alive():
            return status()
        try:
            if identity():
                return mark_connected()
        except (OSError, ValueError, KeyError, StopIteration):
            pass
        settings = gateway.read_settings()
        if settings.get("provider") != "snowluma":
            return save_state(
                "failed", "当前连接程序不是已配置的新程序，请先核对设置。"
            )
        # 本次用户点击仅授权显式启动；保持登录时自动加载和后台接管关闭。
        backup = ROOT / "backups/监控启动入口"
        backup.mkdir(parents=True, exist_ok=True)
        (backup / (str(time.time_ns()) + "_qq_gateway.json")).write_bytes(
            gateway.SETTINGS.read_bytes()
        )
        settings.update(
            state="manual_start_requested",
            auto_attach=False,
            allow_client_launch=False,
            manual_start_requested_at=time.time(),
        )
        temp = gateway.SETTINGS.with_suffix(".tmp")
        temp.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp.replace(gateway.SETTINGS)
        result = save_state("starting", "正在启动聊天并核对目标账号，请稍候。")
        TASK = threading.Thread(target=run, name="小鲸鱼手动启动", daemon=True)
        TASK.start()
        return result


def run():
    """只操作固定目标进程，出现其他账号、条款或故障时停止。"""
    deadline = time.monotonic() + 120
    try:
        while time.monotonic() < deadline:
            try:
                if identity():
                    mark_connected()
                    return
            except (OSError, ValueError, KeyError, StopIteration):
                pass
            result = gateway.ensure(manual=True)
            message = result["状态"]
            if any(
                word in message
                for word in ("其他聊天", "不唯一", "首次使用", "上限", "尚未成功")
            ):
                save_state("attention", message)
                return
            save_state("starting", message + "；正在核对登录状态。")
            time.sleep(3)
        save_state(
            "waiting_login",
            "连接程序已准备；请在小鲸鱼登录窗口完成扫码或验证，随后点击重新核对。",
        )
    except Exception as error:
        save_state(
            "failed", "启动未完成：" + type(error).__name__ + "。请查看运行日志后重试。"
        )
