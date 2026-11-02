"""验证手动登录识别、账号隔离和只读状态查询，不连接真实客户端。"""

import sys
import importlib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / "修复代码"))
gateway = importlib.import_module("qq_gateway_runtime")
probe = importlib.import_module("xiaojingyu_connection_probe")


def client(pid=3144, account="3768021466", **extra):
    return {
        "pid": pid,
        "uin": "0",
        "account": {"uin": account, "nickname": "测试账号"},
        "status": "available",
        "injected": False,
        **extra,
    }


class ConnectionIdentityTests(unittest.TestCase):
    def test_manual_client_without_startup_arguments_is_recognized(self):
        self.assertEqual(gateway.verified_target_rows([client()])[0]["pid"], 3144)
        self.assertEqual(probe.inspect_rows([client()])["phase"], "client_ready")

    def test_recognized_client_is_never_reported_as_robot_online(self):
        value = probe.inspect_rows([client()])
        self.assertFalse(value["bridge_loaded"])
        self.assertNotEqual(value["phase"], "online")

    def test_conflicting_identity_is_not_a_valid_target(self):
        self.assertEqual(gateway.verified_target_rows([client(uin="1443192477")]), [])

    def test_personal_account_is_not_a_valid_target(self):
        self.assertEqual(
            gateway.verified_target_rows([client(account="1443192477")]), []
        )
        self.assertEqual(
            probe.inspect_rows([client(account="1443192477")])["phase"],
            "account_mismatch",
        )

    def test_unknown_and_duplicate_clients_are_blocked(self):
        self.assertEqual(
            probe.inspect_rows([client(account="0")])["phase"], "client_unknown"
        )
        self.assertEqual(
            probe.inspect_rows([client(), client(pid=1234)])["phase"], "ambiguous"
        )

    def test_only_explicit_manual_request_can_connect_confirmed_account(self):
        replies = [
            {"consentRequired": False},
            {"list": [client(), client(pid=9999, account="1443192477")]},
            {"success": True},
        ]
        with (
            patch.object(
                gateway,
                "read_settings",
                return_value={"provider": "snowluma", "auto_attach": False},
            ),
            patch.object(gateway, "node_processes", return_value=[object()]),
            patch.object(gateway, "auth", return_value="测试凭据"),
            patch.object(gateway, "target_main_processes", return_value=[]),
            patch.object(
                gateway.psutil,
                "Process",
                side_effect=lambda pid: SimpleNamespace(pid=pid),
            ),
            patch.object(gateway, "management", side_effect=replies) as api,
            patch.object(gateway, "hidden_start") as launch,
        ):
            result = gateway.ensure(manual=True)
        self.assertEqual(result["进程"], 3144)
        self.assertEqual(api.call_args.args[0], "/api/processes/3144/load")
        launch.assert_not_called()

    def test_background_never_uses_manual_login_as_automatic_authorization(self):
        with (
            patch.object(
                gateway,
                "read_settings",
                return_value={"provider": "snowluma", "auto_attach": False},
            ),
            patch.object(gateway, "management") as api,
            patch.object(gateway, "node_processes") as processes,
        ):
            self.assertIn("手动启动模式", gateway.ensure()["状态"])
        api.assert_not_called()
        processes.assert_not_called()

    def test_unknown_existing_client_does_not_load_or_launch(self):
        with (
            patch.object(
                gateway, "read_settings", return_value={"provider": "snowluma"}
            ),
            patch.object(gateway, "node_processes", return_value=[object()]),
            patch.object(gateway, "auth", return_value="测试凭据"),
            patch.object(gateway, "target_main_processes", return_value=[]),
            patch.object(
                gateway,
                "management",
                side_effect=[
                    {"consentRequired": False},
                    {"list": [client(account="0")]},
                    {"success": True, "process": client(account="0")},
                ],
            ) as api,
            patch.object(gateway, "hidden_start") as launch,
        ):
            self.assertIn("未成功核实", gateway.ensure(manual=True)["状态"])
        self.assertEqual(api.call_count, 3)
        launch.assert_not_called()

    def test_snapshot_queries_only_processes_and_reuses_cached_authentication(self):
        with (
            patch.object(probe, "CACHE", None),
            patch.object(probe, "TOKEN", ""),
            patch.object(gateway, "auth", return_value="本机测试凭据") as authenticate,
            patch.object(
                gateway, "management", return_value={"list": [client()]}
            ) as api,
            patch.object(gateway, "ensure") as connect,
        ):
            self.assertEqual(probe.snapshot()["phase"], "client_ready")
            self.assertEqual(probe.snapshot()["phase"], "client_ready")
        authenticate.assert_called_once()
        api.assert_called_once_with("/api/processes", token="本机测试凭据")
        connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
