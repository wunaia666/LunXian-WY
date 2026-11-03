"""验证官方阅读范围、断点提交、主人隔离和主动消息的实际回执。"""

import importlib
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, r"E:\sss_test\AstrBot")
package = importlib.import_module("data.plugins.astrbot_plugin_dafeiyu_browser")
package.__path__.insert(0, str(Path(__file__).parents[1]))
fanqie = importlib.import_module(package.__name__ + ".fanqie")
initiative = importlib.import_module(package.__name__ + ".initiative")
from data.plugins.astrbot_plugin_dafeiyu_browser.companion import AutonomousLife, CHINA

NOW = datetime(2026, 11, 3, 16, 0, tzinfo=CHINA).timestamp()


class OfficialScopeTests(unittest.TestCase):
    def test_only_official_books_and_chapters_are_accepted(self):
        self.assertEqual(fanqie.official_url("https://fanqienovel.com/page/7069948840148732967"),
                         "https://fanqienovel.com/page/7069948840148732967")
        for url in ("http://127.0.0.1:8765/", "https://fanqienovel.com.evil.test/page/12345678",
                    "https://fanqienovel.com@evil.test/page/12345678", "file:///C:/Windows/a",
                    "https://fanqienovel.com:9555/page/12345678", "https://fanqienovel.com/../../config"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                fanqie.official_url(url)


class InitiativeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base_patch = patch.object(fanqie.ex, "BASE", Path(self.tmp.name))
        base_patch.start()
        self.addCleanup(base_patch.stop)
        self.bot = SimpleNamespace(call_action=AsyncMock(side_effect=[
            {"user_id": 3768021466}, {"message_id": 1001}]))
        self.manager = SimpleNamespace(list_jobs=AsyncMock(return_value=[]),
            add_basic_job=AsyncMock(return_value=SimpleNamespace(job_id="主动任务")), delete_job=AsyncMock())
        self.browser = SimpleNamespace(config={"autonomous_daily_shares": 0,
            "autonomous_cooldown_hours": 0, "novel_background_enabled": False},
            context=SimpleNamespace(cron_manager=self.manager,
                get_platform_inst=lambda name: SimpleNamespace(get_client=lambda: self.bot)))
        self.browser.life = AutonomousLife(self.browser)
        self.browser.life.bind("napcat:FriendMessage:1443192477")
        self.browser.novel = SimpleNamespace(read=AsyncMock(), status=lambda: {})
        self.activity = initiative.Initiative(self.browser)
        self.ask_patch = patch.object(initiative, "ask", AsyncMock(return_value={
            "send": True, "message": "老爸，我刚想起之前说过的那件小事，想过来和你聊两句。"}))
        self.ask = self.ask_patch.start()
        self.addCleanup(self.ask_patch.stop)
        self.clock_patch = patch("time.time", return_value=NOW)
        self.clock_patch.start()
        self.addCleanup(self.clock_patch.stop)

    async def test_proactive_message_requires_platform_receipt(self):
        result = await self.activity.tick()
        self.assertTrue(result["发送"])
        self.assertEqual(self.bot.call_action.call_args.args[0], "send_private_msg")
        self.assertEqual(self.bot.call_action.call_args.kwargs["user_id"], 1443192477)
        self.assertEqual(self.browser.life.store.share_count(self.browser.life.owner, "2026-11-03"), 1)

    async def test_wrong_robot_account_never_sends(self):
        self.bot.call_action.side_effect = [{"user_id": 9988}]
        result = await self.activity.tick()
        self.assertFalse(result["发送"])
        self.assertEqual(self.bot.call_action.await_count, 1)

    async def test_pause_and_recent_chat_are_respected(self):
        self.browser.life.store.put(self.browser.life.owner, "paused", True)
        await self.activity.tick()
        self.ask.assert_not_awaited()
        self.browser.life.store.put(self.browser.life.owner, "paused", False)
        self.browser.life.store.put(self.browser.life.owner, "last_user_ts", NOW - 60)
        await self.activity.tick()
        self.ask.assert_not_awaited()

    async def test_quiet_hours_do_not_generate_or_send(self):
        night = datetime(2026, 11, 3, 23, 30, tzinfo=CHINA).timestamp()
        with patch("time.time", return_value=night):
            result = await self.activity.tick()
        self.assertFalse(result["发送"])
        self.ask.assert_not_awaited()

    async def test_preview_does_not_send_or_queue(self):
        result = await self.activity.tick(dry_run=True)
        self.assertIn("预览消息", result)
        self.bot.call_action.assert_not_awaited()
        self.assertIsNone(self.browser.life.store.get(self.browser.life.owner, "pending"))

    async def test_model_can_choose_silence(self):
        self.ask.return_value = {"send": False, "message": ""}
        result = await self.activity.tick()
        self.assertFalse(result["发送"])
        self.bot.call_action.assert_not_awaited()

    async def test_unknown_delivery_stops_following_messages(self):
        self.browser.life.store.put(self.browser.life.owner, "delivery_unknown", {"key": "旧消息"})
        result = await self.activity.tick()
        self.assertFalse(result["发送"])
        self.ask.assert_not_awaited()

    async def test_reload_only_removes_own_job(self):
        self.manager.list_jobs.return_value = [
            SimpleNamespace(name=initiative.JOB_NAME, payload={"initiative_tag": initiative.TAG}, job_id="旧主动"),
            SimpleNamespace(name="用户提醒", payload={}, job_id="用户任务")]
        await self.activity.initialize()
        self.manager.delete_job.assert_awaited_once_with("旧主动")
        self.assertEqual(self.manager.add_basic_job.call_args.kwargs["timezone"], "Asia/Shanghai")


class BookmarkTests(unittest.IsolatedAsyncioTestCase):
    async def test_ocr_failure_does_not_advance_bookmark(self):
        with tempfile.TemporaryDirectory() as directory:
            from data.plugins.astrbot_plugin_dafeiyu_selfmod.memory import MemoryStore
            store = MemoryStore(Path(directory) / "memory.db")
            life = SimpleNamespace(owner="主人", store=store)
            state = {"书名": "测试小说", "书籍链接": "https://fanqienovel.com/page/12345678",
                     "chapters": [{"url": "https://fanqienovel.com/reader/87654321", "name": "第一章"}],
                     "index": 0, "offset": 0}
            store.put(life.owner, "novel_current", state)
            shelf = fanqie.NovelShelf(SimpleNamespace(life=life))
            async def evaluate(session, expression):
                if "s.scrollTo(" in expression:
                    return {"position": 0, "maximum": 0}
                return {"left": 0, "top": 0, "width": 800, "height": 800}

            client = SimpleNamespace(call=AsyncMock(return_value={"data": "eA=="}),
                                     evaluate=AsyncMock(side_effect=evaluate))

            @asynccontextmanager
            async def tab():
                yield client, "会话"

            with patch.object(shelf, "tab", tab), patch.object(shelf, "goto", AsyncMock()), \
                    patch.object(shelf, "ocr", AsyncMock(side_effect=RuntimeError("识字失败"))), \
                    patch.object(fanqie.ex, "BASE", Path(directory)), \
                    patch.object(fanqie.asyncio, "sleep", AsyncMock()):
                with self.assertRaisesRegex(RuntimeError, "识字失败"):
                    await shelf.read()
            self.assertEqual(store.get(life.owner, "novel_current"), state)

    async def test_model_outage_keeps_actual_page_and_retries_without_skipping(self):
        with tempfile.TemporaryDirectory() as directory:
            from data.plugins.astrbot_plugin_dafeiyu_selfmod.memory import MemoryStore
            store = MemoryStore(Path(directory) / "memory.db")
            life = SimpleNamespace(owner="主人", store=store)
            shelf = fanqie.NovelShelf(SimpleNamespace(life=life))
            state = {"书名": "测试小说", "index": 0, "offset": 0, "章节链接": "https://fanqienovel.com/reader/87654321",
                     "pending_read": {"chapter": {"name": "第一章", "url": "https://fanqienovel.com/reader/87654321"},
                                      "index": 0, "offset": 800, "height": 1600, "evidence": "真正从页面识别到的文字" * 20}}
            with patch.object(fanqie, "ask", AsyncMock(side_effect=TimeoutError())):
                result = await shelf.finish_read(state)
            self.assertTrue(result["读后感待生成"])
            saved = store.get(life.owner, "novel_current")
            self.assertEqual(saved["offset"], 0)
            self.assertIn("真正从页面", saved["pending_read"]["evidence"])
            with patch.object(fanqie, "ask", AsyncMock(return_value={
                    "summary": "本段只描述已观察到的故事情节，没有加入后续章节的推测。", "take": "我想接着看看人物会怎样处理。"})), \
                    patch.object(fanqie.ex, "record"):
                result = await shelf.finish_read(saved)
            self.assertFalse(result["读后感待生成"])
            saved = store.get(life.owner, "novel_current")
            self.assertEqual(saved["offset"], 800)
            self.assertNotIn("pending_read", saved)


if __name__ == "__main__":
    unittest.main()
