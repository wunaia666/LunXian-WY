"""安装任务结束补推通知，保留原有应用通知并备份配置。"""

import json
import os
from pathlib import Path
import sys
import tomllib

from publish_task import DEFAULT_SETTINGS, save_json


def main():
    settings = json.loads(DEFAULT_SETTINGS.read_text(encoding="utf-8"))
    state = Path(settings["state"])
    state.mkdir(parents=True, exist_ok=True)
    codex_directory = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    config = codex_directory / "config.toml"
    original_bytes = config.read_bytes()
    original = original_bytes.decode("utf-8-sig")
    parsed = tomllib.loads(original)
    command = [settings["python"], str(Path(__file__).with_name("notify_wrapper.py"))]
    if parsed.get("notify") == command:
        print("任务结束补推通知已经配置。")
        return
    backup = state / "config.before-auto-upload.toml"
    if not backup.exists():
        backup.write_bytes(original_bytes)
    save_json(state / "previous-notify.json", parsed.get("notify", []))
    lines = original.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.lstrip().startswith("notify")
                  and line.lstrip()[len("notify"):].lstrip().startswith("=")), None)
    replacement = "notify = " + json.dumps(command, ensure_ascii=False) + "\n"
    if start is None:
        updated = replacement + original
    else:
        end = start + 1
        while end <= len(lines):
            try:
                value = tomllib.loads("".join(lines[start:end]))
                if "notify" in value:
                    break
            except tomllib.TOMLDecodeError:
                pass
            end += 1
        if end > len(lines):
            raise RuntimeError("无法准确定位原通知配置，已停止修改。")
        updated = "".join(lines[:start]) + replacement + "".join(lines[end:])
    desired = dict(parsed, notify=command)
    if tomllib.loads(updated) != desired:
        raise RuntimeError("配置校验失败，已停止修改。")
    temporary = config.with_name("config.task-upload.tmp")
    temporary.write_text(updated, encoding="utf-8")
    os.replace(temporary, config)
    print("任务结束补推通知已安装，原有通知已保留。")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
