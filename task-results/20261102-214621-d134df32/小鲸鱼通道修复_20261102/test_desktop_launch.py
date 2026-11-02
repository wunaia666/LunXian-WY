"""核对普通桌面启动、进程树分组与旧失败状态，不实际启动客户端。"""

import base64
import json
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent / "修复代码"))
import xiaojingyu_candidate_client as client
import xiaojingyu_chat_control as control


def process(pid, parent=1, arguments=None):
    result = Mock(pid=pid, info={"pid": pid, "name": "QQ.exe"})
    result.exe.return_value = str(client.CLIENT)
    result.ppid.return_value = parent
    result.cmdline.return_value = arguments or []
    return result


class DesktopTests(unittest.TestCase):
    def test_one_process_tree_is_one_client(self):
        main = process(100)
        helper = process(101, 100)
        renderer = process(102, 101, ["--type=renderer"])
        with patch.object(client.psutil, "process_iter", return_value=[helper, renderer, main]):
            self.assertIs(client.current(), main)

    def test_independent_roots_are_still_blocked(self):
        with patch.object(client.psutil, "process_iter", return_value=[process(100), process(200)]):
            with self.assertRaisesRegex(client.ClientBlocked, "多个验证副本主进程"):
                client.current()

    def test_orphan_children_never_trigger_launch(self):
        with patch.object(client.psutil, "process_iter", return_value=[process(102, 1, ["--type", "utility"])]):
            with self.assertRaisesRegex(client.ClientBlocked, "退出中的进程"):
                client.current()

    def test_launch_only_uses_fixed_desktop_task(self):
        reply = SimpleNamespace(returncode=0, stdout=json.dumps({"state": "Running"}))
        with patch.object(client.subprocess, "run", return_value=reply) as run:
            client.desktop_task(run=True)
        arguments = run.call_args.args[0]
        script = base64.b64decode(arguments[-1]).decode("utf-16-le")
        self.assertIn(str(client.CLIENT), script)
        self.assertIn("Start-ScheduledTask -InputObject $task", script)
        self.assertIn("'Limited'", script)
        self.assertIn("'Interactive'", script)
        self.assertIn("$owner -ne $identity.User.Value", script)
        self.assertNotIn("Register-ScheduledTask", script)

    def test_task_configuration_failure_has_no_direct_launch_fallback(self):
        with patch.object(client.subprocess, "run", return_value=SimpleNamespace(returncode=1)), \
                patch.object(client.subprocess, "Popen") as launch:
            with self.assertRaises(client.ClientBlocked):
                client.desktop_task(run=True)
            launch.assert_not_called()

    def simulate(self, currents, task_states):
        with ExitStack() as stack:
            stack.enter_context(patch.object(client, "verify_files"))
            stack.enter_context(patch.object(client, "current", side_effect=currents))
            task = stack.enter_context(patch.object(client, "desktop_task", side_effect=task_states))
            stack.enter_context(patch.object(client.time, "time", return_value=1000))
            stack.enter_context(patch.object(client.time, "monotonic", side_effect=[0, 0, 13]))
            stack.enter_context(patch.object(client.time, "sleep"))
            result = client.open_once(True)
        return result, task

    def test_new_process_is_returned_after_single_desktop_request(self):
        main = process(100)
        (actual, receipt), task = self.simulate([None, main], [{}])
        self.assertIs(actual, main)
        self.assertIs(receipt.process, main)
        self.assertEqual(task.call_count, 1)
        task.assert_called_once_with(run=True)

    def test_desktop_crash_before_enumeration_is_reported(self):
        with self.assertRaisesRegex(client.ClientLaunchFailed, "0x80000003"):
            self.simulate([None, None], [{}, {"at": "1970-01-01T00:16:40+00:00", "state": "Ready", "result": 0x80000003}])

    def test_old_multiple_process_warning_becomes_past_failure(self):
        old = {"phase": "attention", "message": "检测到多个验证副本主进程，已停止连接，避免选错窗口。", "at": 1}
        with patch.object(control.STATE.__class__, "read_text", return_value=json.dumps(old)), \
                patch.object(client, "current", return_value=None):
            value = control.status()
        self.assertEqual(value["phase"], "launch_failed")
        self.assertIn("当前这些进程均已退出", value["message"])
        self.assertEqual(value["previous_message"], old["message"])

    def test_initializing_process_is_not_reported_as_scan_ready(self):
        with patch.object(client, "open_once", return_value=(process(100), None)), \
                patch.object(client, "validate_process"), \
                patch.object(control.gateway, "auth", return_value="测试凭据"), \
                patch.object(control.gateway, "management", side_effect=[{}, {"list": []}]), \
                patch.object(control, "identity", return_value=False), \
                patch.object(control.time, "monotonic", side_effect=[0, 0, 601]), \
                patch.object(control.time, "sleep"), patch.object(control, "save_state") as save:
            control.run("candidate_login")
        self.assertEqual(save.call_args_list[0].args[0], "starting")
        self.assertNotIn("扫码", save.call_args_list[0].args[1])


if __name__ == "__main__":
    unittest.main()
