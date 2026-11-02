"""验证组件失败不会冒充连接中、不会诱导重复登录、不会越权自动恢复。"""

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / "修复代码"))
gateway = importlib.import_module("qq_gateway_runtime")
probe = importlib.import_module("xiaojingyu_connection_probe")
control = importlib.import_module("xiaojingyu_chat_control")


def client(**extra):
    return {"pid": 3144, "uin": "0", "account": {"uin": gateway.ACCOUNT},
            "status": "available", "injected": False, **extra}


class BridgeFailureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "failure.json"
        self.patcher = patch.object(gateway, "BRIDGE_FAILURE", self.path)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.directory.cleanup()

    def test_native_error_has_priority_over_injected_flag(self):
        value = probe.inspect_rows([client(status="error", injected=True, error="首次连接超时")])
        self.assertEqual(value["phase"], "bridge_failed")
        self.assertIn("首次连接超时", value["message"])
        self.assertNotEqual(value["phase"], "online")

    def test_empty_native_error_still_means_failure(self):
        self.assertEqual(probe.inspect_rows([client(status="error")])["phase"], "bridge_failed")

    def test_loaded_without_error_remains_waiting_for_real_channel(self):
        self.assertEqual(probe.inspect_rows([client(injected=True)])["phase"], "waiting_bridge")

    def test_failure_persists_only_for_exact_process_lifetime(self):
        with patch.object(gateway.psutil, "Process", return_value=SimpleNamespace(create_time=lambda: 100.5)):
            gateway.remember_bridge_failure(client(), "初始化线程退出")
            self.assertEqual(gateway.bridge_error(client()), "初始化线程退出")
        with patch.object(gateway.psutil, "Process", return_value=SimpleNamespace(create_time=lambda: 101.5)):
            self.assertEqual(gateway.bridge_error(client()), "")

    def test_failure_does_not_leak_to_other_process_or_account(self):
        self.path.write_text(json.dumps({"account": gateway.ACCOUNT, "pid": 3144,
            "created_at": 100.5, "message": "初始化失败"}), encoding="utf-8")
        self.assertEqual(gateway.bridge_error(client(pid=4144)), "")
        self.assertEqual(gateway.bridge_error(client(account={"uin": "1443192477"})), "")

    def test_real_connected_process_is_not_overridden_by_old_failure(self):
        self.path.write_text("{}", encoding="utf-8")
        self.assertEqual(gateway.bridge_error(client(connected=True)), "")

    def test_malformed_failure_record_is_ignored(self):
        self.path.write_text("不完整记录", encoding="utf-8")
        self.assertEqual(gateway.bridge_error(client()), "")

    def test_background_gate_remains_before_any_process_operation(self):
        with patch.object(gateway, "read_settings", return_value={"provider": "snowluma", "auto_attach": False}), patch.object(gateway, "management") as api, patch.object(gateway, "node_processes") as processes:
            gateway.ensure()
        api.assert_not_called()
        processes.assert_not_called()

    def test_explicit_click_does_not_reload_known_failed_component(self):
        with patch.object(gateway, "read_settings", return_value={"provider": "snowluma"}), patch.object(gateway, "node_processes", return_value=[object()]), patch.object(gateway, "auth", return_value="测试凭据"), patch.object(gateway, "target_main_processes", return_value=[]), patch.object(gateway.psutil, "Process", return_value=SimpleNamespace(pid=3144, create_time=lambda: 100.5)), patch.object(gateway, "management", side_effect=[{"consentRequired": False}, {"list": [client(status="error", injected=True, error="初始化超时")]}]) as api:
            result = gateway.ensure(manual=True)
        self.assertEqual(result["phase"], "bridge_failed")
        self.assertEqual(api.call_count, 2)
        self.assertTrue(self.path.exists())

    def test_failed_click_does_not_start_thread_or_rewrite_settings(self):
        with patch.object(control, "TASK", None), patch.object(control, "identity", return_value=False), patch.object(probe, "snapshot", return_value={"phase": "bridge_failed", "message": "初始化失败"}), patch.object(control, "save_state", side_effect=lambda p,m: {"phase":p,"message":m}), patch.object(control.threading, "Thread") as thread, patch.object(gateway, "read_settings") as settings:
            result = control.start()
        self.assertEqual(result["phase"], "failed")
        thread.assert_not_called()
        settings.assert_not_called()

    def test_worker_stops_on_native_failure_without_retry_or_login_hint(self):
        with patch.object(control, "identity", return_value=False), patch.object(probe, "snapshot", return_value={"phase":"bridge_failed", "message":"初始化失败"}), patch.object(control, "save_state") as save, patch.object(gateway, "ensure") as ensure:
            control.run()
        save.assert_called_once_with("failed", "初始化失败")
        ensure.assert_not_called()

    def test_identified_account_never_receives_scan_hint_after_two_minutes(self):
        with patch.object(control, "identity", return_value=False), patch.object(probe, "snapshot", return_value={"phase":"waiting_bridge", "account":gateway.ACCOUNT}), patch.object(control, "save_state") as save, patch.object(control.time, "monotonic", side_effect=[0,121,121,601]), patch.object(control.time, "sleep"), patch.object(gateway, "ensure") as ensure:
            control.run()
        self.assertEqual(save.call_args_list[0].args[0], "waiting_bridge")
        self.assertNotIn("请在小鲸鱼登录窗口", save.call_args_list[0].args[1])
        self.assertEqual(save.call_args_list[-1].args[0], "failed")
        ensure.assert_not_called()

    def test_manual_identity_refresh_does_not_load_an_unknown_account(self):
        with patch.object(gateway.os, "listdir", return_value=[]), patch.object(gateway, "management", return_value={"success":True,"process":client()}) as api:
            rows = gateway.refresh_unidentified_account([client(account=None)], "测试凭据")
        self.assertEqual(rows[0]["account"]["uin"], gateway.ACCOUNT)
        api.assert_called_once_with("/api/processes/3144/refresh", {}, token="测试凭据")

    def test_identity_refresh_refuses_existing_pipe_or_personal_account(self):
        with patch.object(gateway.os, "listdir", return_value=["mojo.3144.control"]), patch.object(gateway, "management") as api:
            gateway.refresh_unidentified_account([client(account=None)], "测试凭据")
            gateway.refresh_unidentified_account([client(account={"uin":"1443192477"})], "测试凭据")
            gateway.refresh_unidentified_account([client(account=None),client(pid=4144,account=None)], "测试凭据")
        api.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
