"""模拟网页登录任务，检查启动范围、重复点击、账号隔离及通道真实性。"""

import importlib
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).parent/"修复代码"))
client = importlib.import_module("xiaojingyu_candidate_client")
control = importlib.import_module("xiaojingyu_chat_control")


class WebLoginTests(unittest.TestCase):
    def process(self, path=None, pid=111, args=None):
        process = Mock(pid=pid,info={"pid":pid,"name":"QQ.exe"})
        process.exe.return_value = str(path or client.CLIENT)
        process.cmdline.return_value = args or []
        process.create_time.return_value = 123.0
        return process

    def test_other_client_blocks_launch(self):
        process = self.process(r"C:\Program Files\Tencent\QQNT\QQ.exe")
        with patch.object(client.psutil,"process_iter",return_value=[process]), \
                patch.object(client.subprocess,"Popen") as launch:
            with self.assertRaises(client.ClientBlocked):
                client.current()
            launch.assert_not_called()

    def test_check_only_never_launches(self):
        with patch.object(client,"verify_files"), patch.object(client,"current",return_value=None), \
                patch.object(client.subprocess,"Popen") as launch:
            with self.assertRaisesRegex(client.ClientBlocked,"尚未打开"):
                client.open_once(False)
            launch.assert_not_called()

    def test_existing_candidate_reused(self):
        process = self.process()
        with patch.object(client,"verify_files"),patch.object(client,"current",return_value=process), \
                patch.object(client.subprocess,"Popen") as launch:
            self.assertEqual(client.open_once(True),(process,None))
            launch.assert_not_called()

    def test_pid_reuse_stops(self):
        with patch.object(client,"current",return_value=self.process()):
            with self.assertRaisesRegex(client.ClientBlocked,"进程已变化"):
                client.validate_process(111,124.0)

    def test_running_request_is_reused(self):
        task = SimpleNamespace(is_alive=lambda:True)
        with patch.object(control,"TASK",task),patch.object(control,"status",return_value={"phase":"launching"}), \
                patch.object(control.threading,"Thread") as thread:
            self.assertEqual(control.start("candidate_login")["phase"],"launching")
            thread.assert_not_called()

    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValueError):
            control.start("任意程序路径")

    def simulate(self, rows, *, exit_code=None, identity=None, clock=None):
        states, loads, checks = [], [], []
        process = self.process()
        launched = Mock(returncode=exit_code)
        launched.poll.return_value = exit_code
        def api(path, payload=None, token=None):
            if path == "/api/agreements":
                return {"consentRequired":False}
            if path == "/api/processes":
                return {"list":rows}
            if path.endswith("/load"):
                loads.append(path)
                return {"success":True}
            raise AssertionError(path)
        with ExitStack() as stack:
            stack.enter_context(patch.object(client,"open_once",return_value=(process,launched)))
            stack.enter_context(patch.object(client,"validate_process",return_value=process))
            stack.enter_context(patch.object(control.gateway,"auth",return_value="测试凭据"))
            stack.enter_context(patch.object(control.gateway,"management",side_effect=api))
            stack.enter_context(patch.object(control.gateway,"bridge_error",return_value=""))
            stack.enter_context(patch.object(control.gateway,"refresh_unidentified_account",side_effect=lambda rows,token:rows))
            stack.enter_context(patch.object(control,"save_state",side_effect=lambda phase,message,step=0:states.append((phase,step))))
            stack.enter_context(patch.object(control,"mark_connected",side_effect=lambda:states.append(("online",4))))
            stack.enter_context(patch.object(control,"identity",side_effect=identity or [False]*8))
            stack.enter_context(patch.object(control.time,"sleep"))
            if clock:
                stack.enter_context(patch.object(control.time,"monotonic",side_effect=clock))
            fake_checks = SimpleNamespace(start=lambda **kw:checks.append(kw))
            stack.enter_context(patch.dict(sys.modules,{"xiaojingyu_checks":fake_checks}))
            control.run("candidate_login")
        return states, loads, checks

    def test_launch_crash_does_not_load(self):
        states, loads, _ = self.simulate([],exit_code=0x80000003)
        self.assertEqual(states,[("launch_failed",1)])
        self.assertEqual(loads,[])

    def test_wrong_account_never_loaded(self):
        states, loads, checks = self.simulate([{"pid":111,"uin":"1443192477"}])
        self.assertEqual(states,[("attention",2)])
        self.assertEqual((loads,checks),([],[]))

    def test_logged_in_does_not_equal_online_and_only_loads_once(self):
        rows = [{"pid":111,"uin":"3768021466","status":"available"}]
        states, loads, checks = self.simulate(rows,identity=[False,False,True])
        self.assertEqual(loads,["/api/processes/111/load"])
        self.assertEqual(states,[('connecting',3),('connecting',3),('online',4)])
        self.assertEqual(checks,[{"force":True}])

    def test_unknown_account_waits_without_loading(self):
        states, loads, _ = self.simulate([{"pid":111,"uin":"0","status":"available"}],clock=[0,0,601])
        self.assertEqual(states,[("waiting_scan",2),("attention",2)])
        self.assertEqual(loads,[])


if __name__ == "__main__":
    unittest.main()
