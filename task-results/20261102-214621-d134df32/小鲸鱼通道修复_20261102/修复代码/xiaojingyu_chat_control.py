"""由本机监控按钮显式启动聊天，后台守护不因此获得自动接管权限。"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path

import qq_gateway_runtime as gateway
import xiaojingyu_connection_probe as connection_probe
import xiaojingyu_candidate_client as candidate

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


def save_state(phase, message, step=0):
    """原子保存启动进度，不记录连接凭据。"""
    state = {"phase": phase, "message": message, "at": time.time(), "step": step,
             "client": "verified_copy"}
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
    gateway.BRIDGE_FAILURE.unlink(missing_ok=True)
    state = save_state("online", "小鲸鱼机器人通道已连接，正在检查本地数据。", 4)
    import xiaojingyu_checks

    xiaojingyu_checks.start(force=True)
    return state


def status():
    """返回当前这一次启动的状态，进程中断不冒充仍在执行。"""
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {"phase": "idle", "message": "点击启动，连接小鲸鱼聊天。", "at": 0}
    if (
        data["phase"] in {"starting", "launching", "waiting_scan", "connecting"}
        and not (TASK and TASK.is_alive())
        and time.time() - data["at"] > 10
    ):
        data.update(phase="interrupted", message="上次启动已中断，可以重新点击核对。")
    if data["phase"] == "attention" and "多个验证副本主进程" in data.get("message", ""):
        try:
            if candidate.current() is None:
                data = {**data, "phase": "launch_failed", "previous_message": data["message"],
                        "message": "上次启动检测到多个副本进程；当前这些进程均已退出，聊天仍未连接。"}
        except candidate.ClientBlocked:
            pass
    return data


def start(mode="connect"):
    """网页点击可显式启动副本；重复点击复用任务，不改变后台自动开关。"""
    global TASK
    with LOCK:
        if mode not in {"connect", "candidate_login"}:
            raise ValueError("启动方式不正确")
        if TASK and TASK.is_alive():
            return status()
        try:
            if identity():
                return mark_connected()
        except (OSError, ValueError, KeyError, StopIteration):
            pass
        if mode == "connect":
            connection = connection_probe.snapshot()
            if connection.get("phase") == "bridge_failed":
                return save_state("failed", connection["message"])
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
        result = save_state("launching" if mode == "candidate_login" else "starting",
                            "正在启动独立验证副本，请稍候。" if mode == "candidate_login"
                            else "正在核对验证副本及小鲸鱼账号。", 1)
        TASK = threading.Thread(target=run, args=(mode,), name="小鲸鱼网页登录", daemon=True)
        TASK.start()
        return result


def run(mode="connect"):
    """启动、用户扫码、固定账号接入和只读数据检查组成一次网页任务。"""
    try:
        if mode == "connect":
            connection = connection_probe.snapshot()
            if connection.get("phase") == "bridge_failed":
                save_state("failed", connection["message"])
                return
        process, launched = candidate.open_once(mode == "candidate_login")
        pid, created = process.pid, process.create_time()
        token = gateway.auth()
        agreements = gateway.management("/api/agreements", token=token)
        if agreements.get("consentRequired") or (agreements.get("data") or {}).get("consentRequired"):
            save_state("attention", "连接程序仍有首次使用条款待你确认。", 3)
            return
        deadline = time.monotonic() + 600
        load_requested = False
        recognized_at = None
        data_checked = False
        while time.monotonic() < deadline:
            if launched is not None and launched.poll() is not None:
                code = f"0x{launched.returncode & 0xffffffff:08x}"
                save_state("launch_failed", "QQ验证副本启动后已退出（" + code
                           + "），尚未进入可用聊天状态。本次不会自动重启。", 1)
                return
            candidate.validate_process(pid, created)
            try:
                if identity():
                    mark_connected()
                    return
            except (OSError, ValueError, KeyError, StopIteration):
                pass
            rows = gateway.process_rows(gateway.management("/api/processes", token=token))
            selected = [row for row in rows if str(row.get("pid")) == str(pid)]
            if len(selected) > 1:
                save_state("attention", "验证副本状态不唯一，已停止本次连接。", 2)
                return
            if not selected:
                save_state("starting", "验证副本进程已出现，正在等待客户端初始化与账号识别；尚未确认登录窗口可用。", 1)
                time.sleep(2)
                continue
            row = selected[0]
            if not gateway.process_account(row):
                candidate.validate_process(pid, created)
                row = gateway.refresh_unidentified_account([row], token)[0]
            account = gateway.process_account(row)
            if account and account != gateway.ACCOUNT:
                save_state("attention", "当前登录账号不是小鲸鱼3768021466，已停止接入，请在QQ窗口自行核对。", 2)
                return
            if not account:
                save_state("waiting_scan", "验证副本已打开，请在QQ窗口登录小鲸鱼账号3768021466；本页会自动核对。", 2)
                time.sleep(2)
                continue
            if not data_checked:
                import xiaojingyu_checks

                xiaojingyu_checks.start(force=True)
                data_checked = True
            error = gateway.bridge_error(row)
            if error:
                gateway.remember_bridge_failure(row, error)
                save_state("failed", "小鲸鱼账号已识别，但机器人连接失败：" + error, 3)
                return
            if recognized_at is None:
                recognized_at = time.monotonic()
            loading = row.get("injected") or str(row.get("status", "")).lower() in {
                "loaded", "connected", "ready", "online", "connecting", "loading",
                "injecting", "observing", "passive",
            }
            if not loading and not load_requested:
                candidate.validate_process(pid, created)
                reply = gateway.management(f"/api/processes/{pid}/load", {}, token=token)
                load_requested = True
                if reply.get("success") is not True:
                    save_state("failed", "连接程序未接受本次接入请求，已停止重复加载。", 3)
                    return
            if time.monotonic() - recognized_at > 90:
                save_state("failed", "小鲸鱼账号已识别，但机器人通道核对超时；数据检查见下方，聊天尚不可用。", 3)
                return
            save_state("connecting", "已识别小鲸鱼账号，正在核对机器人真实通道；本地数据检查已启动，无需重复扫码。", 3)
            time.sleep(2)
        save_state("attention", "本次等待登录已结束；请完成QQ窗口中的登录后，在本页重新核对。", 2)
    except candidate.ClientLaunchFailed as error:
        save_state("launch_failed", str(error), 1)
    except candidate.ClientBlocked as error:
        save_state("attention", str(error), 1)
    except gateway.psutil.NoSuchProcess:
        save_state("launch_failed", "QQ验证副本已经退出，尚未建立机器人通道。本次不会自动重启。", 1)
    except Exception as error:
        save_state(
            "failed", "网页启动未完成：" + type(error).__name__ + "。请查看本页故障状态后重试。", 1
        )
