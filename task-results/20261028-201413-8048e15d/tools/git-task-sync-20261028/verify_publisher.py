"""在隔离仓库中验证任务快照、断线重试和范围限制。"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from publish_task import Publisher
from task_sync import StopSync, repository_lock


def run(*arguments, cwd=None, expected=0):
    result = subprocess.run(list(map(str, arguments)), cwd=cwd, capture_output=True,
                            encoding="utf-8", errors="replace", timeout=90,
                            env=dict(os.environ, PYTHONUTF8="1"))
    assert result.returncode == expected, (result.returncode, result.stdout, result.stderr)
    return result.stdout.strip()


def main():
    checks = []
    with tempfile.TemporaryDirectory(prefix="任务上传验证-") as temporary:
        base = Path(temporary)
        source, repo, remote, state = [base / name for name in ("源文件", "归档", "远程.git", "状态")]
        source.mkdir()
        hooks = base / "空钩子"
        hooks.mkdir()
        run("git", "init", "--bare", remote)
        run("git", "init", "-b", "codex/task-results", repo)
        for key, value in (("user.name", "验证"), ("user.email", "test@example.invalid"),
                           ("core.hooksPath", str(hooks)), ("commit.gpgsign", "false")):
            run("git", "-C", repo, "config", key, value)
        (repo / "index.html").write_text("原有网页", encoding="utf-8")
        run("git", "-C", repo, "add", "index.html")
        run("git", "-C", repo, "commit", "-m", "原有项目")
        run("git", "-C", repo, "remote", "add", "origin", remote)
        run("git", "-C", repo, "push", "-u", "origin", "codex/task-results")
        settings = base / "settings.json"
        config = {"source": str(source), "repository": str(repo), "state": str(state),
                  "remote_url": str(remote), "branch": "codex/task-results",
                  "python": sys.executable, "git": shutil.which("git")}
        settings.write_text(json.dumps(config), encoding="utf-8")
        publisher = Publisher(settings)
        file = source / "代码.py"
        file.write_text("print(1)\n", encoding="utf-8")
        (source / "草稿.py").write_text("未完成", encoding="utf-8")
        identifier = publisher.queue("快照验证", ["代码.py"])
        file.write_text("print(2)\n", encoding="utf-8")
        publisher.flush()
        archived = repo / "task-results" / identifier
        assert (archived / "代码.py").read_text(encoding="utf-8") == "print(1)\n"
        assert not (archived / "草稿.py").exists()
        assert (repo / "index.html").read_text(encoding="utf-8") == "原有网页"
        checks.append("仅上传已完成任务快照，后续编辑和其他草稿不混入，原有网页保持完整")
        before = run("git", "-C", repo, "rev-parse", "HEAD")
        publisher.flush()
        assert before == run("git", "-C", repo, "rev-parse", "HEAD")
        checks.append("重复回调不产生重复提交")
        for name in (".env", "credentials.json", "产物.docx", "../越界.py"):
            try:
                publisher.queue("拒绝范围验证", [name])
                raise AssertionError("错误路径未被拒绝")
            except StopSync as error:
                assert error.code == 2
        checks.append("凭据文件、文档产物和越界路径被拒绝")
        identifier = publisher.queue("断线补推验证", ["代码.py"])
        missing = base / "未连接.git"
        run("git", "-C", repo, "remote", "set-url", "origin", missing)
        publisher.settings["remote_url"] = str(missing)
        try:
            publisher.flush()
            raise AssertionError("远程不可用时未报错")
        except StopSync:
            pass
        assert (state / "pending" / (identifier + ".json")).exists()
        preserved = run("git", "-C", repo, "rev-parse", "HEAD")
        run("git", "-C", repo, "remote", "set-url", "origin", remote)
        publisher.settings["remote_url"] = str(remote)
        publisher.flush()
        assert preserved == run("git", "-C", repo, "rev-parse", "HEAD")
        assert not (state / "pending" / (identifier + ".json")).exists()
        checks.append("断线时保留提交与完成标记，恢复后补推同一提交")
        with repository_lock(state / "upload.lock"):
            try:
                publisher.flush()
                raise AssertionError("并发锁未生效")
            except StopSync as error:
                assert error.code == 4
        checks.append("回调与定时补推之间的并发锁生效")
        publisher.close()
    Path(__file__).with_name("上传器验证结果.json").write_text(
        json.dumps({"通过数量": len(checks), "通过项目": checks}, ensure_ascii=False, indent=2), encoding="utf-8")
    for check in checks:
        print("通过：" + check, flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
