"""供现有静默守护调用，只恢复用户已选的多萝本地语音服务。"""

import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from xiaojingyu_voice_profile import ROOT, approved_profile  # noqa: E402


def main():
    profile = approved_profile()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open("http://127.0.0.1:9880/health", timeout=3) as response:
            health = json.load(response)
        if health.get("engine") != "gptsovits":
            raise RuntimeError("语音端口仍由旧引擎占用，需要完成受控切换")
        if health.get("phase") == "failed":
            raise RuntimeError("已选声音加载失败，请检查服务日志")
        print("已选声音服务正在运行或加载。")
        return
    except urllib.error.URLError:
        pass
    engine_root = Path(profile["engine_root"])
    log = engine_root / "approved_doro_service.log"
    log.parent.mkdir(exist_ok=True)
    startup = subprocess.STARTUPINFO()
    startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    with log.open("ab") as stream:
        process = subprocess.Popen(
            [
                str(engine_root / "runtime/python.exe"),
                "-B",
                "-u",
                "-X",
                "utf8",
                str(ROOT / "tools/xiaojingyu_gptsovits_server.py"),
            ],
            cwd=engine_root,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            startupinfo=startup,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    print("已静默启动用户选定的声音服务，进程：" + str(process.pid))


if __name__ == "__main__":
    main()
