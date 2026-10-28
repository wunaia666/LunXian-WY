"""保留原有任务结束通知，并补推已经完成的任务快照。"""

import json
from pathlib import Path
import subprocess
import sys

from publish_task import DEFAULT_SETTINGS, Publisher


def main():
    raw = sys.argv[-1] if len(sys.argv) > 1 else "{}"
    try:
        notification = json.loads(raw)
    except ValueError:
        return 0
    settings = json.loads(DEFAULT_SETTINGS.read_text(encoding="utf-8"))
    previous = Path(settings["state"]) / "previous-notify.json"
    # 原有通知需要保持运行，不能因上传失败而丢失桌面通知。
    if previous.exists():
        command = json.loads(previous.read_text(encoding="utf-8"))
        if command:
            try:
                subprocess.run([*command, raw], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=20)
            except (OSError, subprocess.SubprocessError):
                pass
    if notification.get("type") != "agent-turn-complete":
        return 0
    cwd = notification.get("cwd")
    if not cwd or not Path(cwd).resolve().is_relative_to(Path(settings["source"]).resolve()):
        return 0
    if Path(cwd).resolve().is_relative_to(Path(settings["repository"]).resolve()):
        return 0
    publisher = Publisher(DEFAULT_SETTINGS)
    publisher.logger.info("收到任务结束事件，检查已完成任务队列。")
    try:
        return publisher.flush()
    except Exception as error:
        publisher.logger.error("任务结束补推失败：%s", error)
        return getattr(error, "code", 2)
    finally:
        publisher.close()


if __name__ == "__main__":
    sys.exit(main())
