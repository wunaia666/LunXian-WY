"""验证会话隔离、旧记忆检索、发送限额和后台分享流程。"""

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from data.plugins.astrbot_plugin_dafeiyu_browser import companion
from data.plugins.astrbot_plugin_dafeiyu_selfmod.memory import MemoryStore

NOW = datetime(2026, 10, 25, 11, 0, tzinfo=companion.CHINA).timestamp()


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime.fromtimestamp(NOW, tz)


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = MemoryStore(Path(self.tmp.name) / "memory.db")

    def test_old_memory_and_scope_isolation(self):
        ident = self.store.remember("主人", "去年的考试是在星期三", "event")
        for i in range(35):
            self.store.remember("主人", f"无关记录{i}：" + "天气不错" * 20, "event")
        self.store.remember("别人", "考试安排是别人的私人信息", "event")
        rows = self.store.search("主人", "去年的考试", 3)
        self.assertEqual(rows[0]["id"], ident)
        self.assertTrue(all(r["scope"] == "主人" for r in rows))
        self.assertFalse(self.store.forget("别人", ident))
        with self.assertRaises(ValueError):
            self.store.remember("别人", "试图修改", replace_id=ident)

    def test_update_expiry_and_delete(self):
        with patch("time.time", return_value=NOW):
            ident = self.store.remember("主人", "明天出门", "plan", expires_days=1)
            self.store.remember(
                "主人", "后天出门", "plan", replace_id=ident, expires_days=2
            )
        with patch("time.time", return_value=NOW + 3 * 86400):
            self.assertEqual(self.store.search("主人", "出门"), [])
        self.assertTrue(self.store.forget("主人", ident))

    def test_concurrent_shares_are_claimed_once(self):
        def claim(i):
            return self.store.claim_share(
                "主人", str(i), "真实内容", "2026-10-25", NOW, 2, 14400
            )

        with ThreadPoolExecutor(max_workers=6) as pool:
            self.assertEqual(sum(pool.map(claim, range(6))), 1)

    def test_limit_cooldown_and_failed_send(self):
        self.assertTrue(
            self.store.claim_share("主人", "甲", "内容", "2026-10-25", NOW, 2, 14400)
        )
        self.store.finish_share("主人", "甲", False)
        self.assertEqual(self.store.share_count("主人", "2026-10-25"), 0)
        self.assertTrue(
            self.store.claim_share("主人", "甲", "内容", "2026-10-25", NOW, 2, 14400)
        )
        self.store.finish_share("主人", "甲", True)
        self.assertFalse(
            self.store.claim_share(
                "主人", "乙", "内容", "2026-10-25", NOW + 100, 2, 14400
            )
        )
        self.assertTrue(
            self.store.claim_share(
                "主人", "乙", "内容", "2026-10-25", NOW + 14400, 2, 14400
            )
        )
        self.store.finish_share("主人", "乙", True)
        self.assertFalse(
            self.store.claim_share(
                "主人", "丙", "内容", "2026-10-25", NOW + 28800, 2, 14400
            )
        )
        self.assertFalse(
            self.store.claim_share(
                "主人", "甲", "内容", "2026-10-26", NOW + 86400, 2, 14400
            )
        )


class LifeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base_patch = patch.object(companion.ex, "BASE", Path(self.tmp.name))
        self.base_patch.start()
        self.addCleanup(self.base_patch.stop)
        self.manager = SimpleNamespace(
            list_jobs=AsyncMock(return_value=[]),
            add_basic_job=AsyncMock(return_value=SimpleNamespace(job_id="任务甲")),
            delete_job=AsyncMock(),
        )
        self.provider = SimpleNamespace(text_chat=AsyncMock())
        self.context = SimpleNamespace(
            cron_manager=self.manager,
            send_message=AsyncMock(return_value=True),
            get_using_provider_async=AsyncMock(return_value=self.provider),
            get_config=lambda **kwargs: {
                "agent_runner": {"config": {"persona": {"persona_id": "测试"}}}
            },
            persona_manager=SimpleNamespace(
                get_persona=AsyncMock(
                    return_value=SimpleNamespace(system_prompt="中文角色")
                )
            ),
        )
        self.browser = SimpleNamespace(
            context=self.context,
            config={"autonomous_deep_read": False},
            phone=SimpleNamespace(device=SimpleNamespace(config={}), record_image=""),
            _explore_any=AsyncMock(),
        )
        self.life = companion.AutonomousLife(self.browser)
        self.life.bind("测试平台:FriendMessage:主人")
        self.row = {
            "key": "记录甲",
            "platform": "bilibili",
            "title": "真实的猫视频",
            "summary": "实际取得的简介和热评",
            "url": "https://www.bilibili.com/video/BV1test",
            "source": "标题简介和热评",
        }

    async def test_quiet_hours_pause_and_recent_chat(self):
        self.assertTrue(self.life.contact_allowed(NOW))
        self.assertFalse(
            self.life.contact_allowed(
                datetime(2026, 10, 25, 23, tzinfo=companion.CHINA).timestamp()
            )
        )
        self.assertFalse(
            self.life.contact_allowed(
                datetime(2026, 10, 25, 8, tzinfo=companion.CHINA).timestamp()
            )
        )
        self.life.store.put(self.life.owner, "paused", True)
        self.assertFalse(self.life.contact_allowed(NOW))
        self.life.store.put(self.life.owner, "paused", False)
        self.life.store.put(self.life.owner, "last_user_ts", NOW - 60)
        self.assertFalse(self.life.contact_allowed(NOW))

    async def run_tick(self, text, **kwargs):
        self.provider.text_chat.return_value = SimpleNamespace(completion_text=text)
        with (
            patch.object(companion, "datetime", FrozenDateTime),
            patch("time.time", return_value=NOW),
            patch.object(companion.ex, "recent", side_effect=[[], [self.row]]),
        ):
            return await self.life.tick(**kwargs)

    async def test_preview_does_not_send_or_queue(self):
        result = await self.run_tick(
            '{"share":true,"record_key":"记录甲","message":"老爸，这条猫的简介和热评还挺有意思的。"}',
            dry_run=True,
        )
        self.context.send_message.assert_not_awaited()
        self.assertFalse(result["实际发送"])
        self.assertIn("猫", result["拟分享"])
        self.assertIsNone(self.life.store.get(self.life.owner, "pending"))

    async def test_video_frames_are_passed_without_entering_memory(self):
        self.browser.config["autonomous_deep_read"] = True
        frames = ["data:image/jpeg;base64,仅用于测试的帧"]
        self.life._read_video = AsyncMock(
            return_value=("取得了真实视频文字证据", frames)
        )
        await self.run_tick('{"share":false,"record_key":"记录甲","message":""}')
        self.assertEqual(self.provider.text_chat.call_args.kwargs["image_urls"], frames)
        self.assertFalse(
            any(
                "base64" in row["content"]
                for row in self.life.store.search(self.life.owner)
            )
        )

    async def test_real_record_shared_only_to_owner(self):
        self.life.bind("napcat:FriendMessage:1443192477")
        bot = SimpleNamespace(
            call_action=AsyncMock(
                side_effect=[{"user_id": 3768021466}, {"message_id": 12345}]
            )
        )
        self.context.get_platform_inst = lambda name: SimpleNamespace(
            get_client=lambda: bot
        )
        await self.run_tick(
            '{"share":true,"record_key":"记录甲","message":"老爸，这条猫的简介和热评还挺有意思的。"}'
        )
        self.context.send_message.assert_not_awaited()
        self.assertEqual(bot.call_action.call_args.args[0], "send_private_msg")
        self.assertEqual(bot.call_action.call_args.kwargs["user_id"], 1443192477)
        self.assertEqual(self.life.store.share_count(self.life.owner, "2026-10-25"), 1)
        self.assertTrue(self.life.store.search(self.life.owner, "真实的猫视频"))

    async def test_fabricated_record_is_never_sent(self):
        await self.run_tick(
            '{"share":true,"record_key":"伪造记录","message":"这条未读过的内容绝不能发出去。"}'
        )
        self.context.send_message.assert_not_awaited()

    async def test_uninteresting_content_is_saved_silently(self):
        await self.run_tick('{"share":false,"record_key":"记录甲","message":""}')
        self.context.send_message.assert_not_awaited()
        self.assertTrue(self.life.store.search(self.life.owner, "猫"))

    async def test_failed_send_is_not_counted_as_success(self):
        self.context.send_message.side_effect = RuntimeError("模拟发送失败")
        await self.run_tick(
            '{"share":true,"record_key":"记录甲","message":"老爸，这条猫的简介和热评还挺有意思的。"}'
        )
        self.assertEqual(self.life.store.share_count(self.life.owner, "2026-10-25"), 0)
        self.assertIsNotNone(self.life.store.get(self.life.owner, "pending"))

    async def test_reload_only_removes_owned_jobs(self):
        self.manager.list_jobs.return_value = [
            SimpleNamespace(
                name=companion.JOB_NAME,
                payload={"companion_tag": "dafeiyu_life"},
                job_id="旧任务",
            ),
            SimpleNamespace(name="别的提醒", payload={}, job_id="用户提醒"),
        ]
        await self.life.initialize()
        self.manager.delete_job.assert_awaited_once_with("旧任务")
        self.assertEqual(
            self.manager.add_basic_job.call_args.kwargs["timezone"], "Asia/Shanghai"
        )
        await self.life.terminate()
        self.assertTrue(self.life.stopping)


if __name__ == "__main__":
    unittest.main()
