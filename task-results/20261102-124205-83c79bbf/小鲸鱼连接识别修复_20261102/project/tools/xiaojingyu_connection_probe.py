"""只读区分客户端账号已识别、连接组件加载、机器人通道三个阶段。"""

import threading
import time

import qq_gateway_runtime as gateway


LOCK = threading.Lock()
TOKEN = ""
TOKEN_AT = 0
CACHE = None
CACHE_AT = 0


def inspect_rows(rows):
    """客户端出现或账号已识别，都不能被当成机器人已经在线。"""
    targets = gateway.verified_target_rows(rows)
    if len(targets) > 1:
        return {
            "phase": "ambiguous",
            "client_detected": True,
            "account": "",
            "message": "检测到多个小鲸鱼进程，请核对后再连接。",
        }
    if len(targets) == 1:
        row = targets[0]
        loaded = bool(row.get("injected")) or str(row.get("status", "")).lower() in {
            "loaded",
            "connected",
            "ready",
            "online",
            "loading",
            "injecting",
            "observing",
            "passive",
        }
        return {
            "phase": "waiting_bridge" if loaded else "client_ready",
            "client_detected": True,
            "account": gateway.ACCOUNT,
            "pid": int(row["pid"]),
            "bridge_loaded": loaded,
            "message": "已识别小鲸鱼账号，连接组件已加载，正在等待机器人通道。"
            if loaded
            else "已识别小鲸鱼账号 3768021466；客户端已打开，机器人尚未接入。点击“连接已登录账号”继续。",
        }
    if rows:
        known = any(gateway.process_account(row) for row in rows)
        return {
            "phase": "account_mismatch" if known else "client_unknown",
            "client_detected": True,
            "account": "",
            "message": "当前识别到其他账号，尚未选择小鲸鱼。"
            if known
            else "检测到客户端，但登录账号尚未核实；保留当前窗口。",
        }
    return {
        "phase": "client_missing",
        "client_detected": False,
        "account": "",
        "message": "尚未检测到小鲸鱼客户端。",
    }


def snapshot():
    """短时缓存只读结果与本机认证，轮询不会启动、接管或重连客户端。"""
    global TOKEN, TOKEN_AT, CACHE, CACHE_AT
    with LOCK:
        now = time.monotonic()
        if CACHE is not None and now - CACHE_AT < 6:
            return dict(CACHE)
        try:
            if not TOKEN or now - TOKEN_AT > 300:
                TOKEN = gateway.auth()
                TOKEN_AT = now
            reply = gateway.management("/api/processes", token=TOKEN)
            if reply.get("success") is False or not any(
                name in reply for name in ("list", "processes", "data")
            ):
                TOKEN = ""
                raise ValueError("管理服务未通过读取认证")
            value = inspect_rows(gateway.process_rows(reply))
        except (OSError, ValueError, KeyError, RuntimeError):
            value = {
                "phase": "manager_unavailable",
                "client_detected": False,
                "account": "",
                "message": "连接管理服务暂不可读，客户端状态尚未核实。",
            }
        CACHE, CACHE_AT = value, now
        return dict(value)
