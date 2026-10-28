"""将已经完成并检查通过的任务代码制作快照，自动提交并上传。"""

import argparse
from datetime import datetime
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

from task_sync import repository_lock, StopSync


DEFAULT_SETTINGS = Path(__file__).with_name("upload_settings.json")
CODE_EXTENSIONS = {".py", ".ps1", ".sh", ".bat", ".cmd", ".js", ".mjs", ".cjs", ".ts",
                   ".tsx", ".jsx", ".html", ".htm", ".css", ".scss", ".sass", ".less",
                   ".vue", ".svelte", ".json", ".toml", ".yaml", ".yml", ".xml", ".sql",
                   ".rs", ".go", ".c", ".cpp", ".cc", ".h", ".hpp", ".cs", ".java",
                   ".kt", ".swift", ".rb", ".php", ".r", ".jl", ".lua", ".md", ".txt"}
EXCLUDED_PARTS = {".git", ".task-upload", "repositories", "node_modules", "__pycache__", ".venv"}
SECRET_PATTERN = re.compile(rb"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,}|sk-(?:proj-)?[A-Za-z0-9_-]{35,}")


def save_json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


class Publisher:
    def __init__(self, settings):
        self.settings = json.loads(Path(settings).read_text(encoding="utf-8-sig"))
        self.source = Path(self.settings["source"]).resolve()
        self.repo = Path(self.settings["repository"]).resolve()
        self.state = Path(self.settings["state"]).resolve()
        for directory in (self.state, self.state / "pending", self.state / "completed", self.state / "snapshots"):
            directory.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger("task_publisher." + str(self.state))
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = RotatingFileHandler(self.state / "auto-upload.log", maxBytes=1048576,
                                          backupCount=2, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            self.logger.addHandler(handler)

    def close(self):
        for handler in list(self.logger.handlers):
            handler.close()
            self.logger.removeHandler(handler)

    def git(self, *arguments):
        environment = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never")
        result = subprocess.run([self.settings["git"], "-C", str(self.repo), *arguments],
                                env=environment, stdin=subprocess.DEVNULL, capture_output=True,
                                encoding="utf-8", errors="replace", timeout=60)
        if result.returncode:
            raise StopSync(5, "仓库检查命令失败，请查看本机认证或仓库状态。")
        return result.stdout.strip()

    def queue(self, name, files):
        # 调用本入口即表示本次任务已完成并通过项目所需检查。
        now = datetime.now().astimezone()
        identifier = now.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
        snapshot = self.state / "snapshots" / identifier
        content = []
        for item in dict.fromkeys(files):
            path = (self.source / item).resolve()
            try:
                relative = path.relative_to(self.source)
            except ValueError:
                raise StopSync(2, "任务文件必须位于当前工作区内。")
            parts = {part.lower() for part in relative.parts}
            if parts & EXCLUDED_PARTS or any(part.startswith(".env") for part in parts):
                raise StopSync(2, "所选路径包含本地状态、依赖目录或环境凭据文件。")
            if path.suffix.lower() not in CODE_EXTENSIONS or not path.is_file():
                raise StopSync(2, "请明确列出任务代码或必要说明文件，不能选择整个目录或二进制产物。")
            if path.name.lower() in {"credentials.json", "secrets.json", "auth.json", "id_rsa", "id_ed25519"}:
                raise StopSync(2, "不能上传认证文件。")
            if path.stat().st_size > 5 * 1024 * 1024:
                raise StopSync(2, "单个代码文件超过五兆字节，请先确认上传范围。")
            data = path.read_bytes()
            if b"\0" in data[:4096] or SECRET_PATTERN.search(data):
                raise StopSync(2, "文件可能包含二进制内容或访问凭据，已停止本次入队。")
            content.append((relative, data))
        if not content:
            raise StopSync(2, "任务没有可上传的代码文件。")
        snapshot.mkdir()
        records = []
        for relative, data in content:
            target = snapshot / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            records.append({"路径": relative.as_posix(), "校验值": hashlib.sha256(data).hexdigest()})
        manifest = {"任务标识": identifier, "任务名称": name, "完成时间": now.isoformat(), "文件": records}
        save_json(snapshot / "任务记录.json", manifest)
        # 快照全部写完才发布完成标记，定时补推只处理已有完成标记。
        save_json(self.state / "pending" / (identifier + ".json"), manifest)
        self.logger.info("已登记完成任务：%s，文件数：%s", identifier, len(records))
        return identifier

    def flush(self):
        with repository_lock(self.state / "upload.lock"):
            pending = sorted((self.state / "pending").glob("*.json"))
            if not pending:
                return 0
            if Path(self.git("rev-parse", "--show-toplevel")).resolve() != self.repo:
                raise StopSync(2, "归档目录不是独立仓库。")
            if self.git("remote", "get-url", "origin") != self.settings["remote_url"]:
                raise StopSync(2, "归档远程地址与指定地址不一致。")
            if self.git("symbolic-ref", "--short", "HEAD") != self.settings["branch"]:
                raise StopSync(3, "归档仓库分支发生变化，请先恢复任务结果分支。")
            for item in pending:
                manifest = json.loads(item.read_text(encoding="utf-8"))
                identifier = manifest["任务标识"]
                if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[a-f0-9]{8}", identifier):
                    raise StopSync(2, "任务标识无效。")
                snapshot = self.state / "snapshots" / identifier
                destination = self.repo / "task-results" / identifier
                for record in manifest["文件"]:
                    relative = Path(record["路径"])
                    source = (snapshot / relative).resolve()
                    if not source.is_relative_to(snapshot.resolve()):
                        raise StopSync(2, "快照路径无效。")
                    if hashlib.sha256(source.read_bytes()).hexdigest() != record["校验值"]:
                        raise StopSync(3, "完成后的代码快照发生变化，停止上传。")
                    target = destination / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                save_json(destination / "任务记录.json", manifest)
                environment = dict(os.environ, PYTHONUTF8="1", AUTOSYNC_ACTIVE="1")
                command = [self.settings["python"], str(Path(__file__).with_name("task_sync.py")),
                           "--git", self.settings["git"], "--repo", str(self.repo),
                           "--branch", self.settings["branch"], "--remote", "origin", "--commit",
                           "--paths", "task-results/" + identifier,
                           "--message", "完成任务：" + manifest["任务名称"]]
                result = subprocess.run(command, env=environment, capture_output=True,
                                        encoding="utf-8", errors="replace", timeout=240)
                if result.returncode:
                    self.logger.error("上传未完成：%s；返回码：%s；%s", identifier, result.returncode,
                                      (result.stdout + result.stderr)[-4000:])
                    raise StopSync(result.returncode, "本次任务已保留在本地队列，等待补推或处理失败原因。")
                manifest["提交标识"] = self.git("rev-parse", "HEAD")
                save_json(self.state / "completed" / item.name, manifest)
                # 完成记录先持久化，随后移除待处理标记；重试不会重复创建相同提交。
                item.unlink()
                save_json(self.state / "last-upload.json", manifest)
                self.logger.info("任务上传成功：%s；提交：%s", identifier, manifest["提交标识"])
                print("任务上传成功：" + manifest["提交标识"])
            return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", default=str(DEFAULT_SETTINGS))
    commands = parser.add_subparsers(dest="command", required=True)
    complete = commands.add_parser("complete", help="完成任务并立即上传")
    complete.add_argument("--name", required=True)
    complete.add_argument("--files", required=True, nargs="+")
    complete.add_argument("--queue-only", action="store_true")
    commands.add_parser("flush", help="补推已完成的任务")
    options = parser.parse_args()
    publisher = Publisher(options.settings)
    try:
        if options.command == "complete":
            identifier = publisher.queue(options.name, options.files)
            print("任务已登记：" + identifier)
            if options.queue_only:
                return 0
        return publisher.flush()
    except (StopSync, OSError, subprocess.SubprocessError, ValueError, KeyError) as error:
        publisher.logger.error("上传流程未完成：%s", error)
        print(str(error), file=sys.stderr)
        return getattr(error, "code", 2)
    finally:
        publisher.close()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
