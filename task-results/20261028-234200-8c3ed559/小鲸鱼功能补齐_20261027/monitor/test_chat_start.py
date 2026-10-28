"""验证本机启动接口、重复点击和账号隔离，不启动真实客户端。"""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch

import monitor
import xiaojingyu_chat_control as control


class ChatStartTests(unittest.TestCase):
    def test_repeated_click_reuses_task(self):
        with (
            patch.object(control, "TASK", Mock(is_alive=lambda: True)),
            patch.object(control, "status", return_value={"phase": "starting"}),
            patch.object(control, "identity") as identity,
        ):
            self.assertEqual(control.start()["phase"], "starting")
            identity.assert_not_called()

    def test_connected_keeps_automatic_attach_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gateway.json"
            path.write_text(
                json.dumps({"provider": "snowluma", "state": "paused_by_user"}),
                encoding="utf-8",
            )
            with (
                patch.object(control.gateway, "SETTINGS", path),
                patch.object(control, "STATE", Path(directory) / "state.json"),
                patch.object(control, "identity", return_value=True),
                patch.object(control, "TASK", None),
            ):
                self.assertEqual(control.start()["phase"], "online")
                state = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(state["state"], "manual_started")
                self.assertFalse(state["auto_attach"])
                self.assertFalse(state["allow_client_launch"])

    def test_post_requires_local_origin_and_nonce(self):
        server = monitor.ThreadingHTTPServer(("127.0.0.1", 0), monitor.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:" + str(server.server_port)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with patch.object(
                control, "start", return_value={"phase": "starting"}
            ) as start:
                for headers in (
                    {},
                    {
                        "Origin": "http://outside.example",
                        "X-Local-Control": monitor.CONTROL_TOKEN,
                    },
                    {"Origin": base},
                ):
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        opener.open(
                            urllib.request.Request(
                                base + "/api/chat/start", data=b"{}", headers=headers
                            )
                        )
                    self.assertEqual(error.exception.code, 403)
                start.assert_not_called()
                with opener.open(
                    urllib.request.Request(
                        base + "/api/chat/start",
                        data=b"{}",
                        headers={
                            "Origin": base,
                            "X-Local-Control": monitor.CONTROL_TOKEN,
                        },
                    )
                ) as response:
                    self.assertEqual(response.status, 202)
                start.assert_called_once()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_background_guard_does_not_start_manual_session(self):
        with (
            patch.object(
                control.gateway,
                "read_settings",
                return_value={
                    "provider": "snowluma",
                    "state": "manual_started",
                    "auto_attach": False,
                },
            ),
            patch.object(control.gateway, "hidden_start") as launch,
        ):
            self.assertIn("手动启动模式", control.gateway.ensure()["状态"])
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
