"""验证电脑默认目标、观察绑定和压缩截图坐标，不操作真实电脑输入。"""

import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

path = Path(__file__).parents[2] / "astrbot_plugin_xiaojingyu_host/desktop.py"
spec = importlib.util.spec_from_file_location("desktop_completion_test", path)
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)


class DesktopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.session = desktop.DesktopSession(Path(self.tmp.name))
        self.info = {
            "ok": True,
            "foreground": {"pid": 12, "process": "notepad", "title": "电脑控制测试"},
            "virtualDesktop": {"x": -100, "y": 0, "width": 2560, "height": 1440},
        }
        self.calls = []

        async def run(command, cwd, timeout):
            action = command[command.index("-Action") + 1]
            self.calls.append((action, command))
            return {
                "退出码": 0,
                "输出": json.dumps(
                    self.info if action == "info" else {"ok": True, "action": action}
                ),
                "超时": False,
            }

        self.run = run

    async def observe(self):
        with patch.object(
            desktop, "capture", return_value=(b"preview", (2560, 1440), (1568, 882))
        ):
            value, _ = await self.session.observe(self.run)
        return value

    async def test_scaled_image_coordinates_map_to_real_desktop(self):
        value = await self.observe()
        await self.session.act(
            self.run,
            "click",
            {
                "ObservationId": value["观察编号"],
                "ExpectTitle": "电脑控制测试",
                "X": 784,
                "Y": 441,
            },
        )
        command = self.calls[-1][1]
        self.assertEqual(command[command.index("-X") + 1], "1180")
        self.assertEqual(command[command.index("-Y") + 1], "720")
        self.assertEqual(command[command.index("-ExpectProcessId") + 1], "12")

    async def test_observation_cannot_be_reused(self):
        value = await self.observe()
        arguments = {
            "ObservationId": value["观察编号"],
            "ExpectTitle": "电脑控制测试",
            "Text": "测试",
        }
        await self.session.act(self.run, "type", arguments)
        with self.assertRaisesRegex(ValueError, "重新观察"):
            await self.session.act(self.run, "type", arguments)

    async def test_window_change_prevents_input(self):
        value = await self.observe()
        self.info = {
            **self.info,
            "foreground": {"pid": 13, "process": "notepad", "title": "其他窗口"},
        }
        with self.assertRaisesRegex(ValueError, "已改变"):
            await self.session.act(
                self.run,
                "click",
                {
                    "ObservationId": value["观察编号"],
                    "ExpectTitle": "电脑控制测试",
                    "X": 10,
                    "Y": 10,
                },
            )
        self.assertFalse(any(row[0] == "click" for row in self.calls))

    async def test_expired_or_guessed_observation_prevents_input(self):
        value = await self.observe()
        self.session.observation["时间"] = time.time() - 65
        with self.assertRaises(ValueError):
            await self.session.act(
                self.run,
                "key",
                {
                    "ObservationId": value["观察编号"],
                    "ExpectTitle": "电脑控制测试",
                    "Key": "ENTER",
                },
            )

    async def test_executor_failure_is_not_reported_as_success(self):
        run = AsyncMock(
            return_value={"退出码": 0, "输出": '{"ok":false,"error":"输入失败"}'}
        )
        with self.assertRaisesRegex(RuntimeError, "输入失败"):
            await self.session.bridge(run, "click")

    async def test_chat_and_emulator_windows_are_protected(self):
        for process in ("QQ", "Weixin", "dnplayer"):
            with self.assertRaises(ValueError):
                self.session.check_window({"process": process})


class PriorityTests(unittest.IsolatedAsyncioTestCase):
    async def test_general_computer_request_hides_phone_tools(self):
        from data.plugins.astrbot_plugin_dafeiyu_browser.main import DafeiyuBrowser

        instance = DafeiyuBrowser.__new__(DafeiyuBrowser)
        instance.life = SimpleNamespace(owner="主人")
        tools = SimpleNamespace(remove_tool=lambda name: removed.append(name))
        for message, expected in (
            ("帮我控制电脑看视频", True),
            ("在手机上看视频", False),
        ):
            removed = []
            request = SimpleNamespace(system_prompt="", func_tool=tools)
            await instance.inject_phone_rules(
                SimpleNamespace(unified_msg_origin="主人", message_str=message), request
            )
            self.assertEqual("phone_screen" in removed, expected)
            self.assertIn(
                "电脑操作优先" if expected else "本条明确指定了手机",
                request.system_prompt,
            )


if __name__ == "__main__":
    unittest.main()
