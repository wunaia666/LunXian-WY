"""验证登录检查、记忆维护接口与原声候选确认，不发送聊天消息。"""

import hashlib
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import monitor
import xiaojingyu_checks as checks
import xiaojingyu_voice_studio as studio


class ConsoleUpgradeTests(unittest.TestCase):
    def test_current_voice_list_excludes_unverified_old_voices(self):
        def read(path, default=None):
            if path.name == "voice_config.json":
                return {
                    "reference_only": True,
                    "_模型": {"ref_wav_wsl": "/指定原声.wav"},
                }
            if path.name == "voice_samples.json":
                return [{"name": "旧音色", "file": "old.wav"}]
            if path.name == "voice_candidates.json":
                return [
                    {
                        "name": "已核对原声",
                        "file": "verified.wav",
                        "reference_sha": checks.REFERENCE_SHA,
                    }
                ]
            return {}

        with (
            patch.object(monitor, "read_json", side_effect=read),
            patch.object(monitor, "audio_files", return_value={}),
        ):
            result = monitor.api_voice()
        self.assertEqual([row["name"] for row in result["samples"]], ["已核对原声"])

    def test_database_status_counts_are_bound_to_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with patch.object(monitor, "ASSETS", folder):
                store = monitor.memory_store()
                store.remember("甲", "长期事实")
                store.remember("乙", "另一会话的事实")
                with patch.object(monitor, "owner", return_value="甲"):
                    value = monitor.api_database()
                self.assertEqual(value["total"], 1)
                self.assertEqual(value["integrity"], "通过")
                self.assertTrue(value["fulltext"])

    def test_memory_search_covers_topic_and_state(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with (
                patch.object(monitor, "ASSETS", folder),
                patch.object(monitor, "owner", return_value="甲"),
            ):
                store = monitor.memory_store()
                ident = store.remember("甲", "不加糖", topic="饮食偏好")
                store.pin("甲", ident)
                value = monitor.api_memories(
                    {"search": ["饮食偏好"], "state": ["locked"]}
                )
                self.assertEqual(value["items"][0]["id"], ident)
                self.assertIsNone(value["items"][0]["expires"])

    def test_login_check_worker_saves_real_completion(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(checks, "STATE", Path(directory) / "check.json"),
            patch.object(checks, "TASK", None),
            patch.object(
                checks,
                "probe",
                return_value=[{"name": "隔离测试", "ok": True, "detail": "通过"}],
            ),
        ):
            checks.start()
            checks.TASK.join(timeout=5)
            result = checks.status()
            self.assertEqual(result["phase"], "done")
            self.assertFalse(result["sent_messages"])

    def test_voice_accept_requires_matching_candidate_and_confirmation(self):
        candidate = {
            "phase": "ready",
            "id": "候选甲",
            "reference_sha": studio.REFERENCE_SHA,
        }
        with (
            patch.object(studio, "status", return_value=candidate),
            patch.object(studio, "checked_config") as config,
        ):
            for body in ({"id": "候选甲"}, {"id": "候选乙", "accepted": True}):
                with self.assertRaises(ValueError):
                    studio.accept(body)
            config.assert_not_called()

    def test_voice_source_hash_cannot_be_replaced_by_profile(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(studio, "ROOT", Path(directory)),
        ):
            assets = Path(directory) / "dafeiyu_assets"
            reference = (
                assets / "audio/_cosy_ref/ref_douyin_link_7689724715246372473.wav"
            )
            reference.parent.mkdir(parents=True)
            reference.write_bytes(b"wrong-source")
            (assets / "voice_config.json").write_text(
                json.dumps(
                    {
                        "_模型": {
                            "source_video_id": "7689724715246372473",
                            "ref_wav_wsl": reference.name,
                        }
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "原声校验"):
                studio.checked_config()

    def test_voice_confirmation_changes_parameters_and_keeps_source(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(studio, "ROOT", Path(directory)),
            patch.object(studio, "STATE", Path(directory) / "studio.json"),
        ):
            assets = Path(directory) / "dafeiyu_assets"
            reference = (
                assets / "audio/_cosy_ref/ref_douyin_link_7689724715246372473.wav"
            )
            reference.parent.mkdir(parents=True)
            reference.write_bytes(b"test-reference")
            digest = hashlib.sha256(reference.read_bytes()).hexdigest()
            cfg = {
                "_模型": {
                    "source_video_id": "7689724715246372473",
                    "ref_wav_wsl": reference.name,
                }
            }
            (assets / "voice_config.json").write_text(json.dumps(cfg), encoding="utf-8")
            preview = assets / "audio/previews/abc.wav"
            preview.parent.mkdir()
            preview.write_bytes(b"a" * 1001)
            candidate = {
                "phase": "ready",
                "id": "abc",
                "file": "abc.wav",
                "reference_sha": digest,
                "profile": "stable",
                "tempo": 0.94,
            }
            with (
                patch.object(studio, "REFERENCE_SHA", digest),
                patch.object(studio, "status", return_value=candidate),
            ):
                result = studio.accept({"id": "abc", "accepted": True})
            applied = json.loads(
                (assets / "voice_config.json").read_text(encoding="utf-8")
            )
            self.assertTrue(result["production_changed"])
            self.assertEqual(applied["_模型"], cfg["_模型"])
            self.assertTrue(applied["reference_only"])
            self.assertEqual(applied["fallback"], "none")

    def test_mutating_memory_endpoint_rejects_missing_nonce(self):
        server = monitor.ThreadingHTTPServer(("127.0.0.1", 0), monitor.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = "http://127.0.0.1:" + str(server.server_port)
            request = urllib.request.Request(
                base + "/api/memory/backup", data=b"{}", headers={"Origin": base}
            )
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                    request
                )
            self.assertEqual(error.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
