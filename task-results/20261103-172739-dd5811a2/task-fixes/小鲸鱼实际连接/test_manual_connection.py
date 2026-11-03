"""验证离线启动、重复请求、账号核验及手动模式不会触发后台重启。"""

import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, r"E:\sss_test\tools")
sys.path.insert(0, str(Path(__file__).parent))
import xiaojingyu_chat_control as control
import xiaojingyu_guard as guard


class ManualConnectionTests(unittest.TestCase):
    def simulate(self, *, online=None, exit_code=None, clock=None, running=False):
        states = []
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            shell = root / "napcat/shell"
            shell.mkdir(parents=True)
            for name in ("NapCatWinBootMain.exe", "NapCatWinBootHook.dll",
                         "loadNapCat.js", "napcat.mjs", "qqnt.json"):
                (shell / name).touch()
            qq = root / "QQ.exe"
            qq.touch()
            stack.enter_context(patch.object(control, "ROOT", root))
            stack.enter_context(patch.object(control.gateway, "QQ", qq))
            stack.enter_context(patch.object(control, "identity", side_effect=online or [False, True]))
            stack.enter_context(patch.object(control.gateway.psutil, "process_iter",
                                             return_value=[Mock(info={"name": "QQ.exe"})] if running else []))
            launch = stack.enter_context(patch.object(control.subprocess, "Popen"))
            launch.return_value.poll.return_value = exit_code
            connected = stack.enter_context(patch.object(control, "mark_connected"))
            stack.enter_context(patch.object(control, "save_state", side_effect=lambda *args: states.append(args)))
            stack.enter_context(patch.object(control.time, "sleep"))
            if clock:
                stack.enter_context(patch.object(control.time, "monotonic", side_effect=clock))
            control.run_napcat("candidate_login")
            return states, launch, connected

    def test_offline_service_does_not_prevent_launch(self):
        states, launch, connected = self.simulate(online=[OSError("服务离线"), False, True])
        launch.assert_called_once()
        connected.assert_called_once()
        command = launch.call_args.args[0]
        self.assertEqual(command[-2:], ["-q", control.gateway.ACCOUNT])
        self.assertTrue(command[0].endswith("NapCatWinBootMain.exe"))
        self.assertEqual(states[0][0], "waiting_scan")

    def test_online_reuses_connection(self):
        _, launch, connected = self.simulate(online=[True])
        launch.assert_not_called()
        connected.assert_called_once()

    def test_existing_unconnected_client_is_preserved(self):
        states, launch, connected = self.simulate(online=[False], running=True)
        launch.assert_not_called()
        connected.assert_not_called()
        self.assertEqual(states[0][0], "attention")

    def test_launcher_failure_does_not_respawn(self):
        states, launch, connected = self.simulate(online=[False, False], exit_code=12)
        launch.assert_called_once()
        connected.assert_not_called()
        self.assertEqual(states[-1][0], "launch_failed")

    def test_timeout_does_not_report_account_online(self):
        states, launch, connected = self.simulate(online=[False, False], clock=[0, 0, 601])
        launch.assert_called_once()
        connected.assert_not_called()
        self.assertEqual(states[-1][0], "attention")

    def test_recheck_never_launches_client(self):
        with patch.object(control, "identity", return_value=False), \
                patch.object(control, "save_state") as save, \
                patch.object(control.subprocess, "Popen") as launch:
            control.run_napcat("connect")
            launch.assert_not_called()
            self.assertEqual(save.call_args.args[0], "attention")

    def test_configured_runtime_is_selected_and_automatic_flags_stay_off(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            settings = root / "gateway.json"
            settings.write_text(json.dumps({"provider": "napcat"}), encoding="utf-8")
            stack.enter_context(patch.object(control, "ROOT", root))
            stack.enter_context(patch.object(control, "STATE", root / "state.json"))
            stack.enter_context(patch.object(control, "TASK", None))
            stack.enter_context(patch.object(control, "identity", side_effect=OSError("离线")))
            stack.enter_context(patch.object(control.gateway, "SETTINGS", settings))
            thread = stack.enter_context(patch.object(control.threading, "Thread"))
            control.start("candidate_login")
            self.assertIs(thread.call_args.kwargs["target"], control.run_napcat)
            thread.return_value.start.assert_called_once()
            saved = json.loads(settings.read_text(encoding="utf-8"))
            self.assertFalse(saved["auto_attach"])
            self.assertFalse(saved["allow_client_launch"])

    def test_guard_respects_manual_mode_for_backup_runtime(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch.object(guard, "TMP", Path(directory)))
            stack.enter_context(patch.object(guard, "processes", return_value=[]))
            stack.enter_context(patch.object(guard, "listening", return_value=True))
            stack.enter_context(patch.object(guard, "fetch", side_effect=[
                {"data": {"qq": False}}, {"ready": True}]))
            stack.enter_context(patch.object(control.gateway, "read_settings", return_value={
                "provider": "napcat", "auto_attach": False, "allow_client_launch": False}))
            launch = stack.enter_context(patch.object(guard.subprocess, "Popen"))
            result = guard.check({}, dry_run=True)
            self.assertIn("手动连接", result["components"]["聊天账号"])
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
