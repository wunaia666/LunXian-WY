"""小鲸鱼实时监控：读取真实日志、聊天、请求快照和记忆，仅监听本机。"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import importlib
import json
import mimetypes
import re
import secrets
import socket
import sqlite3
import sys
import time
import urllib.request
import webbrowser
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

HERE = Path(__file__).resolve().parent
DEFAULT = {
    "astrbot_dir": r"E:\sss_test\AstrBot",
    "assets_dir": r"E:\sss_test\dafeiyu_assets",
    "port": 8765,
}
try:
    CONFIG = {**DEFAULT, **json.loads((HERE / "config.json").read_text("utf-8-sig"))}
except (OSError, ValueError):
    CONFIG = DEFAULT
ROOT = Path(CONFIG["astrbot_dir"])
DATA = ROOT / "data"
ASSETS = Path(CONFIG["assets_dir"])
RUNTIME = ASSETS / "runtime"
PORT = int(CONFIG["port"])
HOST = "127.0.0.1"
CONTROL_TOKEN = secrets.token_urlsafe(32)
tool_directory = HERE.parent / "tools"
sys.path.insert(
    0, str(tool_directory if tool_directory.is_dir() else ROOT.parent / "tools")
)
chat_control = importlib.import_module("xiaojingyu_chat_control")

if not 1024 <= PORT <= 65535:
    raise ValueError("监控端口无效")
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def sanitize(value):
    if isinstance(value, dict):
        return {
            str(k): "【已遮盖】"
            if re.search(
                r"(?i)secret|password|api_key|authorization|access_token", str(k)
            )
            else sanitize(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, str):
        value = ANSI.sub("", value)
        value = re.sub(
            r"data:[^;\s]+;base64,[A-Za-z0-9+/=]+", "【媒体正文已省略】", value
        )
        value = re.sub(r"\bsk-[A-Za-z0-9_-]{6,}", "【密钥已遮盖】", value)
        value = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]{8,}", "【凭据已遮盖】", value)
        return re.sub(
            r"(?i)((?:api[_-]?key|jwt_secret|password|access[_-]?token|authorization)\s*[:=]\s*[\"']?)[^\s\"',;}{]{6,}",
            r"\1【已遮盖】",
            value,
        )
    return value


def read_json(path, default=None):
    try:
        return json.loads(path.read_text("utf-8-sig"))
    except (OSError, ValueError):
        return default if default is not None else {}


def tail(path, limit=300, max_bytes=300_000):
    if not path.is_file():
        return []
    with path.open("rb") as stream:
        size = stream.seek(0, 2)
        stream.seek(max(0, size - max_bytes))
        raw = stream.read(max_bytes).decode("utf-8-sig", errors="replace")
    if size > max_bytes:
        raw = raw.split("\n", 1)[-1]
    return raw.splitlines()[-limit:]


def events(name, limit=300):
    rows = []
    for line in tail(RUNTIME / f"{name}.jsonl", limit, 1_000_000):
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return rows


def safe_time(value):
    if not value:
        return ""
    try:
        if isinstance(value, (int, float)):
            instant = dt.datetime.fromtimestamp(value, dt.UTC)
        else:
            instant = dt.datetime.fromisoformat(str(value))
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=dt.UTC)
        return instant.astimezone(dt.timezone(dt.timedelta(hours=8))).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (ValueError, OSError, OverflowError):
        return str(value)


@contextmanager
def open_sqlite(path):
    connection = sqlite3.connect(
        "file:" + quote(path.resolve().as_posix(), safe="/:") + "?mode=ro",
        uri=True,
        timeout=2,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        yield connection
    finally:
        connection.close()


def tables(db):
    return {
        r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def owner():
    return read_json(ASSETS / "companion_owner.json").get("session", "")


def source_id(path):
    return hashlib.sha256(str(path).encode()).hexdigest()[:16]


def log_sources():
    candidates = list((DATA / "logs").glob("*.log"))
    candidates += [
        DATA / "astrbot.log",
        ROOT / "astrbot.log",
        ROOT.parent / "tmp/astrbot_guard_start.log",
        ROOT.parent / "tmp/napcat_guard.log",
    ]
    return sorted(
        {p.resolve() for p in candidates if p.is_file()},
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def find_log():
    candidates = [p for p in log_sources() if p.name != "napcat_guard.log"]
    return candidates[0] if candidates else None


def api_logs(q):
    sources = log_sources()
    chosen = (
        next((p for p in sources if source_id(p) == q.get("source", [""])[0]), None)
        or find_log()
    )
    lines = tail(chosen, 600) if chosen else []
    search = q.get("search", [""])[0].lower()
    level = q.get("level", [""])[0]
    rows = []
    for line in lines:
        line = sanitize(line)[:9000]
        if search and search not in line.lower():
            continue
        if level and level.lower() not in line.lower():
            continue
        rows.append(line)
    return {
        "file": str(chosen or ""),
        "found": bool(chosen),
        "lines": rows,
        "mtime": safe_time(chosen.stat().st_mtime) if chosen else "",
        "source": source_id(chosen) if chosen else "",
        "sources": [
            {"id": source_id(p), "name": p.name, "mtime": safe_time(p.stat().st_mtime)}
            for p in sources
        ],
    }


def as_payload(body):
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return [{"role": "资料", "content": sanitize(body)}]
    output = []
    for item in body if isinstance(body, list) else []:
        content = item.get("content", "")
        if isinstance(content, list):
            content = "\n".join(
                str(part.get("text", "【媒体】"))
                if isinstance(part, dict)
                else str(part)
                for part in content
            )
        content = re.sub(
            r"<system_reminder>.*?</system_reminder>", "", str(content), flags=re.DOTALL
        ).strip()
        if not content and item.get("tool_calls"):
            content = "【调用工具】" + "、".join(
                call.get("function", {}).get("name", "") for call in item["tool_calls"]
            )
        if content:
            output.append(
                {
                    "role": item.get("role", "资料"),
                    "content": content[:14000],
                    "time": "",
                    "source": "已保存的会话",
                }
            )
    return sanitize(output[-250:])


def api_sessions(kind="context"):
    path = DATA / "data_v4.db"
    if not path.is_file():
        return {"items": [], "note": "尚未找到聊天数据库"}
    with open_sqlite(path) as db:
        rows = db.execute(
            "SELECT conversation_id,title,user_id,platform_id,updated_at FROM conversations ORDER BY updated_at DESC LIMIT 100"
        ).fetchall()
    return {
        "items": [
            {
                "id": "c:" + r["conversation_id"],
                "title": "老爸与小鲸鱼 · 当前私聊"
                if r["user_id"] == owner()
                else "官方通道历史"
                if str(r["platform_id"]).startswith("qq_official")
                else "网页会话 · " + safe_time(r["updated_at"])[5:16]
                if str(r["platform_id"]).startswith("webchat")
                else r["title"] or r["user_id"],
                "scope": r["user_id"],
                "subtitle": safe_time(r["updated_at"]),
                "updated": safe_time(r["updated_at"]),
            }
            for r in rows
        ],
        "note": "从真实保存的会话读取；新消息和实际发送记录在下方实时补充。",
    }


def api_session_detail(q):
    ident = q.get("id", [""])[0]
    if not ident.startswith("c:") or len(ident) > 180:
        return {"items": [], "events": []}
    with open_sqlite(DATA / "data_v4.db") as db:
        row = db.execute(
            "SELECT content,user_id,updated_at FROM conversations WHERE conversation_id=?",
            (ident[2:],),
        ).fetchone()
    if not row:
        return {"items": [], "events": []}
    live = [r for r in events("chat") if r.get("scope") == row["user_id"]]
    for item in live:
        item["time"] = safe_time(item.get("at"))
    return {
        "items": as_payload(row["content"]),
        "events": live[-100:],
        "saved_at": safe_time(row["updated_at"]),
        "note": "上方是已保存的会话，下方是启用监控后捕获的收发事件；两者有独立来源，可能重叠。",
    }


def api_context(q):
    ident = q.get("id", [""])[0]
    latest = read_json(RUNTIME / "request_latest.json")
    rows = events("request", 30)
    selected = (
        next((r for r in rows if r.get("id") == ident), latest) if ident else latest
    )
    selected["time"] = safe_time(selected.get("at"))
    linked = [
        r for r in events("tool", 100) if r.get("request_id") == selected.get("id")
    ]
    return {
        "request": selected,
        "tools": linked,
        "requests": [
            {
                "id": r.get("id"),
                "time": safe_time(r.get("at")),
                "prompt": str(r.get("prompt", ""))[:80],
                "preview": r.get("preview"),
            }
            for r in reversed(rows)
        ],
        "note": "这是请求钩子完成后、原生摘要压缩前的首轮输入快照。动态记忆只用于本轮，可在实际注入的记忆中查看。后续工具结果单独列出；验收请求会明确标注。",
    }


def api_memories(q=None):
    q = q or {}
    path = ASSETS / "companion_memory.db"
    if not path.is_file():
        return {"items": [], "jobs": {}, "total": 0}
    scope = owner()
    search = q.get("search", [""])[0][:150]
    kind = q.get("kind", [""])[0]
    page = max(0, min(int(q.get("page", ["0"])[0]), 10000))
    where, args = "scope=?", [scope]
    if search:
        where += " AND (instr(content,?)>0 OR instr(source,?)>0)"
        args += [search, search]
    if kind in {"preference", "event", "browse", "plan"}:
        where += " AND kind=?"
        args.append(kind)
    with open_sqlite(path) as db:
        total = db.execute(
            "SELECT COUNT(*) FROM memories WHERE " + where, args
        ).fetchone()[0]
        rows = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM memories WHERE "
                + where
                + " ORDER BY updated DESC LIMIT 50 OFFSET ?",
                args + [page * 50],
            )
        ]
        jobs, failed = {}, []
        if "memory_jobs" in tables(db):
            jobs = dict(
                db.execute(
                    "SELECT status,COUNT(*) FROM memory_jobs WHERE scope=? GROUP BY status",
                    (scope,),
                ).fetchall()
            )
            failed = [
                dict(r)
                for r in db.execute(
                    "SELECT id,message,status,error,updated FROM memory_jobs WHERE scope=? AND status='failed' ORDER BY updated DESC LIMIT 8",
                    (scope,),
                )
            ]
    for row in rows:
        row["time"] = safe_time(row["updated"])
        row["expired"] = (
            row.get("expires") is not None and row["expires"] <= time.time()
        )
        row["last_used"] = safe_time(row.get("last_accessed"))
    trace = read_json(RUNTIME / "request_latest.json").get("memory", {})
    return {
        "items": rows,
        "total": total,
        "page": page,
        "jobs": jobs,
        "failed": failed,
        "injected_ids": [r["id"] for r in trace.get("included", [])],
        "injection": trace,
        "worker": read_json(RUNTIME / "memory_worker_latest.json"),
        "note": "显示绑定私聊的真实记忆；更正会保留修订，过期项不再送给模型。",
    }


def api_memory_detail(q):
    ident = q.get("key", [""])[0]
    with open_sqlite(ASSETS / "companion_memory.db") as db:
        row = db.execute(
            "SELECT * FROM memories WHERE id=? AND scope=?", (ident, owner())
        ).fetchone()
        revisions = []
        if "memory_revisions" in tables(db):
            revisions = [
                dict(r)
                for r in db.execute(
                    "SELECT action,previous,changed FROM memory_revisions WHERE scope=? AND memory_id=? ORDER BY changed DESC LIMIT 20",
                    (owner(), ident),
                )
            ]
    return {"record": dict(row) if row else {}, "revisions": revisions}


def api_desktop():
    value = read_json(RUNTIME / "desktop_latest.json")
    value["画面可用"] = (
        RUNTIME / "desktop_latest.jpg"
    ).is_file() and "图片尺寸" in value
    value["显示时间"] = safe_time(value.get("时间"))
    value["默认目标"] = "本机真实电脑桌面和软件窗口"
    audit_path = ROOT.parent / "tmp/host_control_audit.jsonl"
    records = []
    for line in tail(audit_path, 20):
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    value["操作记录"] = list(reversed(records))
    return value


def audio_files():
    root = (ASSETS / "audio").resolve()
    files = {
        source_id(p): p
        for p in root.glob("*")
        if p.is_file()
        and p.resolve().parent == root
        and p.suffix.lower() in {".mp3", ".wav"}
        and not p.name.endswith(".send.wav")
    }
    preview = (HERE / "audio").resolve()
    for path in preview.glob("*.wav"):
        if path.is_file() and path.resolve().parent == preview:
            files[source_id(path)] = path
    return files


def api_voice():
    cfg = read_json(ASSETS / "voice_config.json")
    samples = read_json(RUNTIME / "voice_samples.json", [])
    samples = read_json(HERE / "voice_candidates.json", []) + samples
    files = audio_files()
    by_name = {p.name: key for key, p in files.items()}
    for sample in samples:
        sample["url"] = (
            "/audio/" + by_name[sample["file"]] if sample.get("file") in by_name else ""
        )
    latest = read_json(RUNTIME / "voice_latest.json")
    latest["url"] = (
        "/audio/" + by_name[latest["file"]] if latest.get("file") in by_name else ""
    )
    latest["time"] = safe_time(latest.get("at"))
    return {
        "configuration": {
            "backend": cfg.get("backend"),
            "voice": cfg.get("edge_voice"),
            "rate": cfg.get("edge_rate_percent"),
            "pitch": cfg.get("edge_pitch_hz"),
            "style": cfg.get("voice_style"),
            "cooldown": 0,
            # 本地情感引擎相关（只读展示，不参与决策）
            "cosy_url": cfg.get("cosy_url"),
            "cosy_air_db": cfg.get("cosy_air_db", 0),
            "ref": latest.get("ref") or "",
            "backend_actual": latest.get("backend_actual")
            or latest.get("backend")
            or "",
            "fallback": latest.get("fallback") or "",
            "fallback_reason": latest.get("fallback_reason") or "",
            "mood": latest.get("mood") or "",
            "synth_ms": latest.get("synth_ms") or 0,
            "chunks": latest.get("chunks") or 0,
        },
        "latest": latest,
        "samples": samples,
    }


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def api_status():
    latest = read_json(RUNTIME / "request_latest.json")
    log = find_log()
    qq_state = "未连接"
    online = False
    account_id = ""
    try:
        config = read_json(ROOT.parent / "napcat/shell/config/onebot11_3768021466.json")
        endpoint = next(
            x
            for x in config.get("network", {}).get("httpServers", [])
            if x.get("enable") and x.get("host") in {"127.0.0.1", "localhost"}
        )
        request = urllib.request.Request(
            f"http://127.0.0.1:{int(endpoint['port'])}/get_status",
            headers={"Authorization": "Bearer " + endpoint.get("token", "")},
        )
        result = json.load(urllib.request.urlopen(request, timeout=0.5))
        online = (
            result.get("retcode") == 0 and result.get("data", {}).get("online") is True
        )
        qq_state = "账号在线" if online else "等待登录"
        if online:
            identity_request = urllib.request.Request(
                f"http://127.0.0.1:{int(endpoint['port'])}/get_login_info",
                headers={"Authorization": "Bearer " + endpoint.get("token", "")},
            )
            identity = json.load(urllib.request.urlopen(identity_request, timeout=1))
            account_id = str((identity.get("data") or {}).get("user_id", ""))
            if account_id != "3768021466":
                online = False
                qq_state = "当前登录账号与小鲸鱼目标账号不一致"
    except (OSError, ValueError, StopIteration):
        online = False
        qr = ROOT.parent / "napcat/shell/cache/qrcode.png"
        if qr.exists() and time.time() - qr.stat().st_mtime < 300:
            qq_state = "等待扫码"
    return {
        "at": safe_time(time.time()),
        "gateway": read_json(ASSETS / "qq_gateway.json").get("provider", "napcat"),
        "astrbot": port_open(6185),
        "qq": online,
        "qq_state": qq_state,
        "qq_account": account_id,
        "voice_local": port_open(9880),
        "request_at": safe_time(latest.get("at")),
        "log_path": str(log or ""),
        "log_at": safe_time(log.stat().st_mtime) if log else "",
        "readonly": False,
        "service": "xiaojingyu-monitor",
        "chat_start": chat_control.status(),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "LocalMonitor/2.0"

    def log_message(self, *args):
        pass

    def reply(self, status, body, mime="application/json; charset=utf-8", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; media-src 'self'; frame-ancestors 'none'",
        )
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.headers.get("Host", "").split(":")[0].lower() not in {
            "127.0.0.1",
            "localhost",
        }:
            self.reply(403, "仅允许本机访问".encode(), "text/plain; charset=utf-8")
            return
        try:
            url = urlsplit(self.path)
            q = parse_qs(url.query)
            if url.path == "/api/control":
                self.reply(
                    200,
                    json.dumps(
                        {
                            "ok": True,
                            "data": {
                                "nonce": CONTROL_TOKEN,
                                "start": chat_control.status(),
                            },
                        },
                        ensure_ascii=False,
                    ).encode(),
                )
                return
            if url.path == "/api/features":
                self.reply(
                    200,
                    json.dumps(
                        {
                            "ok": True,
                            "data": read_json(HERE / "features.json", {"items": []}),
                        },
                        ensure_ascii=False,
                    ).encode(),
                )
                return
            if url.path.startswith("/assets/"):
                name = url.path.removeprefix("/assets/")
                allowed = {"character.jpg", "happy.png", "sleepy.png"}
                target = HERE / "assets" / name
                if name not in allowed or not target.is_file():
                    self.reply(404, b"{}")
                else:
                    self.reply(
                        200,
                        target.read_bytes(),
                        mimetypes.guess_type(name)[0] or "image/jpeg",
                    )
                return
            if url.path in {"/login", "/login/"}:
                self.reply(
                    200, (HERE / "login.html").read_bytes(), "text/html; charset=utf-8"
                )
                return
            if url.path == "/login/qrcode.png":
                qr = ROOT.parent / "napcat/shell/cache/qrcode.png"
                if not qr.is_file():
                    self.reply(404, b"", "image/png")
                else:
                    self.reply(200, qr.read_bytes(), "image/png")
                return
            if url.path == "/api/login":
                status = api_status()
                qr = ROOT.parent / "napcat/shell/cache/qrcode.png"
                status.update(
                    qr_available=qr.is_file() and status.get("gateway") != "snowluma",
                    qr_mtime=qr.stat().st_mtime if qr.is_file() else 0,
                    qr_age_s=round(time.time() - qr.stat().st_mtime)
                    if qr.is_file()
                    else None,
                )
                self.reply(
                    200,
                    json.dumps(
                        {"ok": True, "data": status}, ensure_ascii=False
                    ).encode(),
                )
                return
            if url.path in {"/", "/index.html"}:
                self.reply(
                    200,
                    (HERE / "dashboard.html").read_bytes(),
                    "text/html; charset=utf-8",
                )
                return
            if url.path == "/desktop/latest.jpg":
                path = RUNTIME / "desktop_latest.jpg"
                if not path.is_file():
                    self.reply(404, b"{}")
                else:
                    self.reply(200, path.read_bytes(), "image/jpeg")
                return
            if url.path.startswith("/audio/"):
                path = audio_files().get(url.path.removeprefix("/audio/"))
                if not path:
                    self.reply(404, b"{}")
                    return
                size = path.stat().st_size
                start, end = 0, size - 1
                span = self.headers.get("Range", "")
                if span:
                    match = re.fullmatch(r"bytes=(\d+)-(\d*)", span)
                    if not match or int(match[1]) >= size:
                        self.reply(416, b"", extra={"Content-Range": f"bytes */{size}"})
                        return
                    start, end = (
                        int(match[1]),
                        min(int(match[2]) if match[2] else end, end),
                    )
                    if end < start:
                        self.reply(416, b"")
                        return
                with path.open("rb") as stream:
                    stream.seek(start)
                    body = stream.read(end - start + 1)
                extra = {"Accept-Ranges": "bytes"}
                if span:
                    extra["Content-Range"] = f"bytes {start}-{end}/{size}"
                self.reply(
                    206 if span else 200,
                    body,
                    mimetypes.guess_type(path.name)[0] or "audio/mpeg",
                    extra,
                )
                return
            endpoints = {
                "/api/status": api_status,
                "/api/logs": lambda: api_logs(q),
                "/api/sessions": api_sessions,
                "/api/detail": lambda: api_session_detail(q),
                "/api/context": lambda: api_context(q),
                "/api/memories": lambda: api_memories(q),
                "/api/memory": lambda: api_memory_detail(q),
                "/api/voice": api_voice,
                "/api/desktop": api_desktop,
            }
            if url.path not in endpoints:
                self.reply(404, b"{}")
                return
            data = sanitize(endpoints[url.path]())
            self.reply(
                200, json.dumps({"ok": True, "data": data}, ensure_ascii=False).encode()
            )
        except (ValueError, OSError, sqlite3.Error, KeyError) as error:
            self.reply(
                503,
                json.dumps(
                    {"ok": False, "error": "数据暂时不可读：" + type(error).__name__},
                    ensure_ascii=False,
                ).encode(),
            )

    def do_POST(self):
        host = self.headers.get("Host", "")
        expected = {
            f"127.0.0.1:{self.server.server_address[1]}",
            f"localhost:{self.server.server_address[1]}",
        }
        origin = self.headers.get("Origin", "")
        supplied = self.headers.get("X-Local-Control", "")
        if (
            host not in expected
            or origin != "http://" + host
            or not hmac.compare_digest(supplied, CONTROL_TOKEN)
        ):
            self.reply(
                403,
                json.dumps(
                    {"ok": False, "error": "请从本机监控页面点击启动按钮"},
                    ensure_ascii=False,
                ).encode(),
            )
            return
        if urlsplit(self.path).path != "/api/chat/start":
            self.reply(404, b"{}")
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 <= size <= 256:
                raise ValueError("请求体长度无效")
            if size:
                self.rfile.read(size)
            result = chat_control.start()
            self.reply(
                202,
                json.dumps({"ok": True, "data": result}, ensure_ascii=False).encode(),
            )
        except (OSError, ValueError) as error:
            self.reply(
                503,
                json.dumps(
                    {"ok": False, "error": "启动请求未完成：" + type(error).__name__},
                    ensure_ascii=False,
                ).encode(),
            )


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f"小鲸鱼监控已启动：http://{HOST}:{PORT}", flush=True)
    if "--no-browser" not in sys.argv:
        webbrowser.open(f"http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
