"""新增能力的真实边界：暂停不发送、未知不重发、参考图必须入请求。"""

import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from PIL import Image

from data.plugins.astrbot_plugin_dafeiyu_browser import companion
from data.plugins.astrbot_plugin_dafeiyu_browser.android_device import AndroidDevice
from data.plugins.astrbot_plugin_dafeiyu_browser.phone_extensions import collect_image
from data.plugins.astrbot_plugin_dafeiyu_selfmod import local_media
from data.plugins.astrbot_plugin_dafeiyu_selfmod.memory import MemoryStore
from data.plugins.astrbot_plugin_dafeiyu_selfmod.qzone import QzonePosts


class QzoneTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.bot = SimpleNamespace(call_action=AsyncMock())
        self.context = SimpleNamespace(
            get_platform_inst=lambda key: SimpleNamespace(get_client=lambda: self.bot)
        )
        self.posts = QzonePosts(self.context, self.base)
        (self.base / "qq_gateway.json").write_text(
            '{"state":"ready"}', encoding="utf-8"
        )

    async def test_prepare_has_no_external_effect(self):
        result = self.posts.prepare("今天也想和老爸分享一件小事。", "好友")
        self.assertEqual(result["状态"], "待确认")
        self.assertIn("确认命令", result)
        self.bot.call_action.assert_not_awaited()

    async def test_paused_gateway_keeps_draft(self):
        draft = self.posts.prepare("这是一份本地草稿。")
        (self.base / "qq_gateway.json").write_text(
            '{"state":"paused_by_user"}', encoding="utf-8"
        )
        with self.assertRaisesRegex(RuntimeError, "暂停"):
            await self.posts.publish(draft["编号"])
        self.bot.call_action.assert_not_awaited()

    async def test_wrong_account_cannot_publish(self):
        self.bot.call_action.return_value = {"user_id": 123}
        with self.assertRaisesRegex(RuntimeError, "账号"):
            await self.posts.publish(self.posts.prepare("不会发给错误的账号。")["编号"])
        self.bot.call_action.assert_awaited_once_with("get_login_info")

    async def test_receipt_and_readback_are_required(self):
        draft = self.posts.prepare("本地隔离测试内容。", "仅自己")
        self.bot.call_action.side_effect = [
            {"user_id": 3768021466},
            {"tid": "帖子甲"},
            {"msglist": [{"tid": "帖子甲", "content": draft["正文"]}]},
        ]
        result = await self.posts.publish(draft["编号"])
        self.assertEqual(result["状态"], "已发布并回读正文")
        self.assertEqual(self.bot.call_action.call_args_list[1].kwargs["ugc_right"], 64)
        await self.posts.publish(draft["编号"])
        self.assertEqual(self.bot.call_action.await_count, 3)

    async def test_timeout_is_not_retried(self):
        draft = self.posts.prepare("网络结果不明时不要重复发布。")
        self.bot.call_action.side_effect = [
            {"user_id": 3768021466},
            asyncio.TimeoutError(),
        ]
        result = await self.posts.publish(draft["编号"])
        self.assertIn("待核对", result["状态"])
        await self.posts.publish(draft["编号"])
        self.assertEqual(self.bot.call_action.await_count, 2)

    async def test_expired_or_invalid_draft_cannot_send(self):
        with self.assertRaises(ValueError):
            await self.posts.publish("../文件")
        with patch("time.time", return_value=time.time() - 90000):
            draft = self.posts.prepare("过期的正文。")
        with self.assertRaisesRegex(ValueError, "过期"):
            await self.posts.publish(draft["编号"])
        self.bot.call_action.assert_not_awaited()


class SharingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.patch = patch.object(companion.ex, "BASE", self.base)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.bot = SimpleNamespace(call_action=AsyncMock())
        context = SimpleNamespace(
            get_platform_inst=lambda key: SimpleNamespace(get_client=lambda: self.bot)
        )
        self.life = companion.AutonomousLife(
            SimpleNamespace(context=context, config={})
        )
        self.life.bind("napcat:FriendMessage:1443192477")
        self.life.contact_allowed = lambda now: True
        self.life.store.put(
            self.life.owner,
            "pending",
            {
                "key": "记录甲",
                "message": "老爸，看到一件有意思的事。",
                "ts": time.time(),
            },
        )

    async def test_pause_does_not_consume_quota(self):
        (self.base / "qq_gateway.json").write_text(
            '{"state":"paused_by_user"}', encoding="utf-8"
        )
        result = await self.life.deliver_pending()
        self.assertFalse(result["发送"])
        self.bot.call_action.assert_not_awaited()
        self.assertIsNotNone(self.life.store.get(self.life.owner, "pending"))

    async def test_receipt_clears_pending_and_records_id(self):
        self.bot.call_action.side_effect = [
            {"user_id": 3768021466},
            {"message_id": 321},
        ]
        result = await self.life.deliver_pending()
        self.assertTrue(result["发送"])
        self.assertEqual(
            self.life.store.get(self.life.owner, "last_delivery")["message_id"], "321"
        )
        self.assertIsNone(self.life.store.get(self.life.owner, "pending"))

    async def test_missing_receipt_never_counts_as_success(self):
        self.bot.call_action.side_effect = [{"user_id": 3768021466}, {}]
        self.assertFalse((await self.life.deliver_pending())["发送"])
        self.assertFalse((await self.life.deliver_pending())["发送"])
        self.assertEqual(self.bot.call_action.await_count, 2)

    async def test_timeout_retains_pending_without_resend(self):
        self.bot.call_action.side_effect = [
            {"user_id": 3768021466},
            asyncio.TimeoutError(),
        ]
        with self.assertRaises(asyncio.TimeoutError):
            await self.life.deliver_pending()
        result = await self.life.deliver_pending()
        self.assertIn("结果不明", result["原因"])
        self.assertEqual(self.bot.call_action.await_count, 2)


class ReferenceImageTests(unittest.IsolatedAsyncioTestCase):
    async def test_reference_pixels_reach_local_service(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            assets = base / "dafeiyu_assets"
            assets.mkdir()
            owner = "napcat:FriendMessage:1443192477"
            (assets / "companion_owner.json").write_text(
                json.dumps({"session": owner}), encoding="utf-8"
            )
            config = assets / "local_media_config.json"
            config.write_text('{"token":"仅用于本地测试"}', encoding="utf-8")
            source = base / "主人原图.png"
            Image.new("RGB", (120, 90), (200, 40, 20)).save(source)
            generated = assets / "generated/result.png"
            generated.parent.mkdir()
            Image.new("RGB", (512, 512)).save(generated)
            received = SimpleNamespace(
                convert_to_file_path=AsyncMock(return_value=str(source))
            )
            event = SimpleNamespace(
                unified_msg_origin=owner, get_group_id=lambda: "", send=AsyncMock()
            )
            context = SimpleNamespace(
                get_using_provider_async=AsyncMock(
                    return_value=SimpleNamespace(
                        text_chat=AsyncMock(
                            return_value=SimpleNamespace(completion_text="cat")
                        )
                    )
                )
            )
            post = AsyncMock(
                return_value=SimpleNamespace(
                    status_code=200, json=lambda: {"path": str(generated)}
                )
            )
            client = MagicMock()
            client.__aenter__ = AsyncMock(return_value=SimpleNamespace(post=post))
            client.__aexit__ = AsyncMock(return_value=False)
            with (
                patch.object(local_media, "BASE", base),
                patch.object(local_media, "CONFIG_PATH", config),
                patch.object(
                    local_media,
                    "ensure_service",
                    AsyncMock(return_value={"image_ready": True}),
                ),
                patch.object(local_media.httpx, "AsyncClient", return_value=client),
                patch(
                    "data.plugins.astrbot_plugin_dafeiyu_selfmod.stickers.StickerLibrary.received_image",
                    AsyncMock(return_value=(received, "原消息")),
                ),
            ):
                media = local_media.LocalMedia(context, MemoryStore(assets / "test.db"))
                await media.draw(event, "照这张图画一只猫", True, 0.45)
            request = post.call_args.kwargs["json"]
            self.assertEqual(request["strength"], 0.45)
            with Image.open(request["reference_path"]) as picture:
                self.assertEqual(picture.getpixel((100, 100)), (200, 40, 20))
            event.send.assert_awaited_once()


class PhoneTests(unittest.IsolatedAsyncioTestCase):
    async def test_home_does_not_require_app_name(self):
        device = AndroidDevice()
        screen = {
            "observation_id": "当前",
            "time": time.time(),
            "package": "com.android.launcher3",
            "blocked": False,
            "targets": [],
        }
        device.observations["当前"] = screen
        device._observe = Mock(return_value=screen)
        device._adb = Mock()
        with patch("asyncio.sleep", new=AsyncMock()):
            await device.act("home", "当前", app="")
        device._adb.assert_called_once_with("shell", "input", "keyevent", "3")

    async def test_stale_image_is_never_saved(self):
        device = AndroidDevice()
        device._adb = Mock()
        with self.assertRaisesRegex(ValueError, "过期"):
            await collect_image(device, None, None, "主人", "不存在", "猜测")
        device._adb.assert_not_called()

    async def test_missing_douyin_is_not_reported_open(self):
        device = AndroidDevice()
        device._observe = Mock(
            return_value={"blocked": False, "package": "com.android.launcher3"}
        )
        device._adb = Mock(return_value=b"No activity found")
        with self.assertRaisesRegex(ValueError, "未安装"):
            await device.act("open", app="douyin")
        self.assertEqual(device._adb.call_count, 1)
