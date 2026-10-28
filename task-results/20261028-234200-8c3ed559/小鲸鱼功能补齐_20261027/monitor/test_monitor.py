"""验证真实数据读取、遮密与音频接口，所有测试使用临时目录。"""

import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import monitor


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ["data/logs", "assets/runtime", "assets/audio", "tmp"]:
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.patches = [
            patch.object(monitor, key, value)
            for key, value in {
                "ROOT": self.root,
                "HERE": self.root / "panel",
                "DATA": self.root / "data",
                "ASSETS": self.root / "assets",
                "RUNTIME": self.root / "assets/runtime",
            }.items()
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        (self.root / "assets/companion_owner.json").write_text(
            json.dumps({"session": "甲"}), encoding="utf-8"
        )
        with closing(sqlite3.connect(self.root / "data/data_v4.db")) as db, db:
            db.executescript(
                "CREATE TABLE platform_message_history(id INTEGER); CREATE TABLE conversations(conversation_id TEXT,title TEXT,user_id TEXT,platform_id TEXT,updated_at TEXT,content TEXT);"
            )
            db.execute(
                "INSERT INTO conversations VALUES (?,?,?,?,?,?)",
                (
                    "会话",
                    "",
                    "甲",
                    "napcat",
                    "2026-10-25 12:24:00",
                    json.dumps(
                        [{"role": "user", "content": "真实消息"}], ensure_ascii=False
                    ),
                ),
            )

    def test_empty_platform_history_does_not_hide_saved_chats(self):
        result = monitor.api_sessions("platform")
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["title"], "老爸与小鲸鱼 · 当前私聊")
        self.assertEqual(
            monitor.api_session_detail({"id": ["c:会话"]})["items"][0]["content"],
            "真实消息",
        )

    def test_latest_log_ignores_guard_as_primary_source(self):
        first = self.root / "data/logs/astrbot.log"
        second = self.root.parent / "tmp/astrbot_guard_start.log"
        # 临时根目录独立设置，避免触碰实际运行日志。
        with patch.object(monitor, "ROOT", self.root / "AstrBot"):
            second = self.root / "tmp/astrbot_guard_start.log"
            guard = self.root / "tmp/napcat_guard.log"
            first.write_text("旧日志", encoding="utf-8")
            second.write_text("新日志", encoding="utf-8")
            guard.write_text("守护", encoding="utf-8")
            now = time.time()
            os.utime(first, (now - 60, now - 60))
            os.utime(second, (now - 20, now - 20))
            self.assertEqual(monitor.find_log(), second.resolve())

    def test_utc_database_dates_display_in_beijing_time(self):
        self.assertEqual(
            monitor.safe_time("2026-10-25 12:24:00"), "2026-10-25 20:24:00"
        )

    def test_json_and_inline_credentials_are_masked(self):
        data = monitor.sanitize(
            {
                "api_key": "secret12345",
                "content": "Bearer abcdefghijklm data:image/png;base64,AAAAAA==",
            }
        )
        self.assertNotIn("secret12345", json.dumps(data))
        self.assertNotIn("abcdefghijklm", json.dumps(data))
        self.assertNotIn("AAAAAA", json.dumps(data))

    def test_audio_access_uses_only_enumerated_ids(self):
        (self.root / "assets/audio/sample.mp3").write_bytes(b"a" * 1000)
        (self.root / "assets/secret.txt").write_text(
            "不能从音频接口读取", encoding="utf-8"
        )
        files = monitor.audio_files()
        self.assertEqual(len(files), 1)
        self.assertNotIn("../secret.txt", files)
        server = monitor.ThreadingHTTPServer(("127.0.0.1", 0), monitor.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = "http://127.0.0.1:" + str(server.server_address[1])
            request = urllib.request.Request(
                base + "/audio/" + next(iter(files)), headers={"Range": "bytes=0-99"}
            )
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(len(response.read()), 100)
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(
                    urllib.request.Request(
                        base + "/api/status", headers={"Host": "outside.example"}
                    )
                )
            self.assertEqual(error.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
