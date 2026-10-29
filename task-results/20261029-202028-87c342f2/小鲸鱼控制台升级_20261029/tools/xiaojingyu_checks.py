"""登录成功后的本机数据检查，只读核对，不发送测试消息。"""

from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(r"E:\sss_test")
STATE = ROOT / "dafeiyu_assets/runtime/login_checks.json"
LOCK = threading.Lock()
TASK = None
REFERENCE_SHA = "d1688351da3c0092165ef379445cfb6eb6ed4861440d6f682d52e1cf4c487e08"


def save(value):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(STATE)
    return value


def status():
    try:
        value = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "phase": "idle",
            "message": "登录成功后自动检查数据，也可以手动检查。",
            "items": [],
        }
    if (
        value.get("phase") == "running"
        and not (TASK and TASK.is_alive())
        and time.time() - value.get("at", 0) > 15
    ):
        value.update(phase="interrupted", message="上次检查已中断，可以重新检查。")
    return value


def probe():
    assets = ROOT / "dafeiyu_assets"
    rows = []

    def add(name, ok, detail):
        rows.append({"name": name, "ok": bool(ok), "detail": detail})

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
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
        replies = {}
        for action in ("get_status", "get_login_info"):
            request = urllib.request.Request(
                f"http://127.0.0.1:{int(endpoint['port'])}/{action}",
                headers={"Authorization": "Bearer " + endpoint.get("token", "")},
            )
            with opener.open(request, timeout=2) as response:
                replies[action] = json.load(response)
        online = (
            all(v.get("retcode") == 0 for v in replies.values())
            and replies["get_status"].get("data", {}).get("online") is True
            and str(replies["get_login_info"].get("data", {}).get("user_id"))
            == "3768021466"
        )
        add(
            "聊天账号",
            online,
            "小鲸鱼目标账号已在线" if online else "目标账号尚未完成登录",
        )
    except (OSError, ValueError, KeyError, StopIteration):
        add("聊天账号", False, "聊天接口尚未连接")
    try:
        with socket.create_connection(("127.0.0.1", 6185), timeout=1):
            add("机器人服务", True, "机器人服务正在监听")
    except OSError:
        add("机器人服务", False, "机器人服务尚未就绪")
    try:
        with sqlite3.connect(
            "file:" + (assets / "companion_memory.db").as_posix() + "?mode=ro", uri=True
        ) as db:
            ok = db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            count = db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        add("记忆数据库", ok, f"完整性{'通过' if ok else '异常'}，已保存{count}条记忆")
    except sqlite3.Error:
        add("记忆数据库", False, "数据库暂时不可读")
    try:
        with opener.open("http://127.0.0.1:9880/health", timeout=3) as response:
            health = json.load(response)
        reference = assets / "audio/_cosy_ref/ref_douyin_link_7689724715246372473.wav"
        verified = hashlib.sha256(reference.read_bytes()).hexdigest() == REFERENCE_SHA
        add(
            "指定原声语音",
            health.get("ready") is True
            and verified
            and Path(health.get("prompt", "")).name == reference.name,
            "指定原声已核对；语速与听感仍需试听" if verified else "原声音频摘要不一致",
        )
    except (OSError, ValueError):
        add("指定原声语音", False, "本地语音服务或指定原声尚未就绪")
    try:
        owner = json.loads(
            (assets / "companion_owner.json").read_text(encoding="utf-8")
        )["session"]
        add(
            "会话绑定",
            owner == "napcat:FriendMessage:1443192477",
            "主人私聊绑定正确"
            if owner == "napcat:FriendMessage:1443192477"
            else "请核对主人私聊绑定",
        )
    except (OSError, ValueError, KeyError):
        add("会话绑定", False, "主人会话绑定尚未就绪")
    return rows


def run():
    try:
        rows = probe()
        save(
            {
                "phase": "done",
                "message": "检查完成；存在待处理项"
                if any(not row["ok"] for row in rows)
                else "登录与数据检查通过",
                "at": time.time(),
                "items": rows,
                "passed": sum(row["ok"] for row in rows),
                "sent_messages": False,
            }
        )
    except Exception as error:
        save(
            {
                "phase": "failed",
                "message": "检查未完成：" + type(error).__name__,
                "at": time.time(),
                "items": [],
            }
        )


def start(force=False):
    global TASK
    with LOCK:
        if TASK and TASK.is_alive():
            return status()
        previous = status()
        if (
            not force
            and previous.get("phase") == "done"
            and time.time() - previous.get("at", 0) < 30
        ):
            return previous
        value = save(
            {
                "phase": "running",
                "message": "正在核对登录账号、服务、记忆和指定原声。",
                "at": time.time(),
                "items": [],
            }
        )
        TASK = threading.Thread(target=run, name="小鲸鱼数据检查", daemon=True)
        TASK.start()
        return value
