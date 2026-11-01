"""验证选声绑定、错误时不换音色以及长文本完整保留，不发送聊天消息。"""

import importlib.util
import io
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

STAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(STAGE / "project/tools"))
sys.path.append(r"E:\sss_test\tools")
server = importlib.import_module("xiaojingyu_gptsovits_server")
admin = importlib.import_module("xiaojingyu_admin_runtime")

SPEC = importlib.util.spec_from_file_location(
    "approved_test_tts",
    STAGE / "project/AstrBot/data/plugins/astrbot_plugin_dafeiyu_voice/tts.py",
)
tts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tts)
CONFIG = {
    "backend": "gptsovits",
    "reference_only": True,
    "fallback": "none",
    "gptsovits": {
        "profile_id": "approved-test",
        "reference_sha": "a" * 64,
        "reference_path": "指定.wav",
        "accepted_sample_sha": "b" * 64,
    },
}


class ApprovedVoiceTests(unittest.IsolatedAsyncioTestCase):
    def test_admin_reload_matches_only_known_monitor(self):
        process = type(
            "Process",
            (),
            {
                "exe": lambda self: str(
                    admin.ROOT / "venvs/astrbot/Scripts/pythonw.exe"
                ),
                "cmdline": lambda self: [
                    r"D:\deepseek\Yu\大肥鱼_实时监控面板\monitor.py"
                ],
            },
        )()
        self.assertTrue(admin.belongs(process, "monitor"))
        process.cmdline = lambda: [r"E:\其他任务\monitor.py"]
        self.assertFalse(admin.belongs(process, "monitor"))

    def test_split_keeps_complete_text(self):
        for text in (
            "今天先喝水。再休息一会儿。",
            "这一句没有标点" * 40,
            "\n你好！\n接着说。",
        ):
            chunks = server.split_text(text)
            self.assertEqual("".join(chunks), text)
            self.assertTrue(all(len(chunk) <= 80 for chunk in chunks))

    async def test_explicit_other_backend_is_blocked(self):
        with patch.object(tts, "load_voice_config", return_value=CONFIG):
            with self.assertRaises(RuntimeError):
                await tts.synth("只用已确认声音。", backend="cosy")

    async def test_wrong_response_cannot_fallback(self):
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.post.return_value = httpx.Response(200, content="其他声音".encode())
        with (
            patch.object(tts, "load_voice_config", return_value=CONFIG),
            patch("httpx.AsyncClient", return_value=client),
            patch.object(tts, "_synth_one", AsyncMock()) as other,
        ):
            with self.assertRaises(RuntimeError):
                await tts.synth("只能使用已确认的声音。")
            other.assert_not_awaited()

    async def test_approved_response_keeps_pcm_without_pitch_change(self):
        stream = io.BytesIO()
        with wave.open(stream, "wb") as audio:
            audio.setparams((1, 2, 32000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\x10\x00" * 5000)
        data = stream.getvalue()
        response = httpx.Response(
            200,
            content=data,
            headers={
                "X-Engine": "gptsovits",
                "X-Profile": "approved-test",
                "X-Ref-SHA": "a" * 64,
                "X-Fails": "-",
            },
        )
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.post.return_value = response
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(tts, "AUDIO_DIR", Path(folder)),
            patch.object(tts, "load_voice_config", return_value=CONFIG),
            patch("httpx.AsyncClient", return_value=client),
            patch.object(tts, "_pitch_match") as pitch,
        ):
            result = await tts.synth("沿用已确认的声音。")
            self.assertEqual(result.read_bytes(), data)
            self.assertEqual(tts.LAST_SYNTH_META["backend_actual"], "gptsovits")
            self.assertFalse(tts.LAST_SYNTH_META["emotion_control_applied"])
            pitch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
