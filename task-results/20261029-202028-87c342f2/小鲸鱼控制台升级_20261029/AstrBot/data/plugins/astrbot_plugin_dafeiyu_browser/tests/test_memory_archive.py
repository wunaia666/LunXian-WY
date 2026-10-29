"""验证长期记忆、全文索引、历史检索和数据库快照。"""

import json
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from data.plugins.astrbot_plugin_dafeiyu_selfmod.memory import MemoryStore
from data.plugins.astrbot_plugin_dafeiyu_selfmod.memory_pipeline import MemoryPipeline
from data.plugins.astrbot_plugin_dafeiyu_voice import tts


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = MemoryStore(Path(self.tmp.name) / "memory.db")

    def test_pin_preserves_content_across_expiry_and_correction(self):
        ident = self.store.remember(
            "甲", "我明天要去看小猫", kind="plan", expires_days=1, topic="约定"
        )
        self.store.pin("甲", ident)
        self.store.remember(
            "甲",
            "改成后天去看小猫",
            kind="plan",
            replace_id=ident,
            expires_days=1,
            topic="约定",
        )
        row = self.store.search("甲", "小猫")[0]
        self.assertIsNone(row["expires"])
        self.assertTrue(row["pinned"])
        body, _ = self.store.assemble("甲", "最近有什么约定")
        self.assertIn("后天", body)
        with self.assertRaises(ValueError):
            self.store.pin("乙", ident)

    def test_archived_rows_can_be_searched_without_reviving_them(self):
        ident = self.store.remember(
            "甲", "以前看过一只纸箱小猫", kind="browse", expires_days=1
        )
        with closing(self.store.connect()) as db, db:
            db.execute(
                "UPDATE memories SET expires=? WHERE id=?", (time.time() - 1, ident)
            )
        self.assertEqual(self.store.search("甲", "纸箱小猫"), [])
        rows = self.store.search("甲", "纸箱小猫", include_expired=True)
        self.assertEqual(rows[0]["id"], ident)
        self.assertTrue(rows[0]["expired"])

    def test_fulltext_index_tracks_correction_and_forgetting(self):
        ident = self.store.remember("甲", "用户喜欢奶茶", topic="饮食偏好")
        with closing(self.store.connect()) as db:
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM memory_fts WHERE memory_fts MATCH ?",
                    ('"喜欢奶茶"',),
                ).fetchone()[0],
                1,
            )
        self.store.remember(
            "甲", "用户改为喜欢清水", replace_id=ident, topic="饮食偏好"
        )
        with closing(self.store.connect()) as db:
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM memory_fts WHERE memory_fts MATCH ?",
                    ('"喜欢奶茶"',),
                ).fetchone()[0],
                0,
            )
        self.store.forget("甲", ident)
        with closing(self.store.connect()) as db:
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM memory_fts WHERE memory_fts MATCH ?",
                    ('"喜欢清水"',),
                ).fetchone()[0],
                0,
            )

    def test_backup_restores_content_and_revisions(self):
        ident = self.store.remember("甲", "第一次约定")
        self.store.remember("甲", "更正后的约定", replace_id=ident)
        receipt = self.store.backup()
        restored = self.store.path.parent / "backups/memory" / receipt["文件"]
        with closing(sqlite3.connect(restored)) as db:
            self.assertEqual(db.execute("PRAGMA quick_check").fetchone()[0], "ok")
            self.assertEqual(
                db.execute("SELECT content FROM memories").fetchone()[0], "更正后的约定"
            )
            self.assertEqual(
                json.loads(
                    db.execute("SELECT previous FROM memory_revisions").fetchone()[0]
                )["content"],
                "第一次约定",
            )

    def test_topic_and_source_are_searchable(self):
        ident = self.store.remember(
            "甲", "不加糖", source="用户亲口交代", topic="饮食偏好"
        )
        self.assertEqual(self.store.search("甲", "饮食偏好")[0]["id"], ident)
        self.assertGreater(self.store.search("甲", "亲口交代")[0]["score"], 0)

    def test_voice_does_not_silently_truncate_long_text(self):
        self.assertEqual(len(tts.clean_text("中" * 360)), 360)
        with self.assertRaisesRegex(ValueError, "未截短"):
            tts.clean_text("中" * (tts.MAX_CHARS + 1))

    def test_new_pins_do_not_displace_highest_priority_name(self):
        name = self.store.remember(
            "甲", "用户要求称呼为老爸", topic="称呼", importance=100
        )
        for index in range(2):
            ident = self.store.remember(
                "甲", "重要记录" * 40, topic="约定" + str(index), importance=98
            )
            self.store.pin("甲", ident)
        body, trace = self.store.assemble("甲", "今天怎么样", budget=1000)
        self.assertIn("老爸", body)
        self.assertIn(name, {row["id"] for row in trace["included"]})


class StableRetentionTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_cannot_expire_a_stable_personal_fact(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(Path(directory) / "memory.db")
            message = "我喜欢喝不加糖的茶"
            rows = [
                {
                    "content": "用户喜欢不加糖的茶",
                    "evidence": message,
                    "kind": "preference",
                    "topic": "饮食偏好",
                    "expires_days": 1,
                }
            ]
            provider = SimpleNamespace(
                text_chat=AsyncMock(
                    return_value=SimpleNamespace(
                        completion_text=json.dumps(rows, ensure_ascii=False)
                    )
                )
            )
            context = SimpleNamespace(
                get_using_provider_async=AsyncMock(return_value=provider)
            )
            pipeline = MemoryPipeline(context, store, lambda: "甲")
            await pipeline.extract({"scope": "甲", "message": message})
            self.assertIsNone(store.search("甲", "不加糖")[0]["expires"])


if __name__ == "__main__":
    unittest.main()
