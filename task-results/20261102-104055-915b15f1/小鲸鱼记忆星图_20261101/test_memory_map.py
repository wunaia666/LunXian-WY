"""验证真实关联、展示上限与偶尔语音策略，不连接聊天账号或修改正式记忆。"""

import copy
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / "project/tools"))
graph = importlib.import_module("xiaojingyu_memory_map")
speech = importlib.import_module("xiaojingyu_speech_policy")


class MemoryMapTests(unittest.TestCase):
    def test_relations_are_only_actual_category_and_identical_topic(self):
        rows = [
            {
                "id": str(i),
                "kind": "preference",
                "topic": topic,
                "content": "真实记录",
                "scope": "甲",
            }
            for i, topic in enumerate(("称呼", "称呼", "称呼偏好"))
        ]
        result = graph.build_memory_map({"items": rows, "total": 3})
        self.assertEqual(sum(node["type"] == "memory" for node in result["nodes"]), 3)
        self.assertEqual(sum(node["type"] == "topic" for node in result["nodes"]), 1)
        self.assertEqual(
            sum(edge["relation"] == "相同主题" for edge in result["links"]), 2
        )
        self.assertTrue(all("scope" not in node for node in result["nodes"]))

    def test_empty_database_has_no_fake_memories(self):
        result = graph.build_memory_map({"items": [], "total": 0})
        self.assertTrue(result["empty"])
        self.assertEqual(result["links"], [])
        self.assertEqual(result["shown"], 0)

    def test_overflow_is_bounded_and_reported(self):
        result = graph.build_memory_map(
            {
                "items": [
                    {"id": str(i), "kind": "browse", "content": "浏览记录"}
                    for i in range(140)
                ],
                "total": 140,
            }
        )
        self.assertEqual(result["shown"], 80)
        self.assertEqual(result["omitted"], 60)
        self.assertLessEqual(len(result["nodes"]), 97)

    def test_read_only_preserves_pinned_expiry_and_input(self):
        source = {
            "items": [
                {
                    "id": "甲",
                    "kind": "plan",
                    "pinned": 1,
                    "expires": 1,
                    "content": "原始正文",
                }
            ],
            "total": 1,
        }
        before = copy.deepcopy(source)
        result = graph.build_memory_map(source)
        record = next(row for row in result["nodes"] if row["type"] == "memory")
        self.assertTrue(record["pinned"])
        self.assertTrue(record["expired"])
        self.assertEqual(source, before)


class SpeechPolicyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name) / "usage.json"
        self.patch = patch.object(speech, "STATE", self.state)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.config = {
            "speech_policy": "occasional",
            "spontaneous_voice_interval_seconds": 1800,
        }

    def test_explicit_request_bypasses_spontaneous_interval(self):
        speech.mark_speech_sent("甲", now=1000)
        self.assertTrue(
            speech.speech_allowed("甲", "再发一句语音", self.config, now=1001)[0]
        )
        self.assertFalse(
            speech.speech_allowed("甲", "今天做什么", self.config, now=1001)[0]
        )
        self.assertTrue(speech.speech_allowed("甲", "继续", self.config, now=1001)[0])

    def test_interval_persists_and_is_scoped(self):
        speech.mark_speech_sent("甲", now=1000)
        self.assertFalse(
            speech.speech_allowed("甲", "普通对话", self.config, now=2000)[0]
        )
        self.assertTrue(
            speech.speech_allowed("甲", "普通对话", self.config, now=2801)[0]
        )
        self.assertTrue(
            speech.speech_allowed("乙", "普通对话", self.config, now=2000)[0]
        )

    def test_corrupt_usage_keeps_text_response(self):
        self.state.write_text(json.dumps(["错误结构"]), encoding="utf-8")
        self.assertFalse(
            speech.speech_allowed("甲", "普通对话", self.config, now=2000)[0]
        )
        self.assertTrue(
            speech.speech_allowed("甲", "请朗读这句话", self.config, now=2000)[0]
        )

    def test_manual_preview_does_not_write_usage(self):
        self.assertTrue(
            speech.speech_allowed("甲", "网页试听", self.config, preview=True)[0]
        )
        self.assertFalse(self.state.exists())


if __name__ == "__main__":
    unittest.main()
