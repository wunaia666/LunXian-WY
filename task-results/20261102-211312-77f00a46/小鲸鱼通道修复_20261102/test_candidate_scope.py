"""验证副本范围检查必须先于任何连接动作，不能误选原安装。"""

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location("candidate_connection", ROOT / "验证本轮连接.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CandidateScopeTest(unittest.TestCase):
    def process(self, path, created=123.0):
        process = Mock()
        process.exe.return_value = path
        process.create_time.return_value = created
        return process

    def test_original_client_rejected(self):
        process = self.process(r"C:\Program Files\Tencent\QQNT\QQ.exe")
        with patch.object(MODULE.gateway.psutil,"Process",return_value=process):
            with self.assertRaisesRegex(RuntimeError,"不是获准验证副本"):
                MODULE.verify_candidate_process(900)

    def test_candidate_accepted(self):
        with patch.object(MODULE.gateway.psutil,"Process",return_value=self.process(str(MODULE.CANDIDATE))):
            self.assertEqual(MODULE.verify_candidate_process(900),123.0)

    def test_pid_reused_rejected(self):
        with patch.object(MODULE.gateway.psutil,"Process",return_value=self.process(str(MODULE.CANDIDATE),124.0)):
            with self.assertRaisesRegex(RuntimeError,"进程已变化"):
                MODULE.verify_candidate_process(900,123.0)

    def test_wrong_client_stops_before_management(self):
        process = self.process(r"C:\Program Files\Tencent\QQNT\QQ.exe")
        with patch.object(MODULE.gateway.psutil,"Process",return_value=process), \
                patch.object(MODULE.gateway,"auth") as auth, \
                patch("sys.argv",["验证本轮连接.py","--pid","900"]):
            with self.assertRaisesRegex(RuntimeError,"不是获准验证副本"):
                MODULE.main()
            auth.assert_not_called()


if __name__ == "__main__":
    unittest.main()
