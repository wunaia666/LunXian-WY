"""用隔离的本地裸仓库验证自动同步，不连接真实远程。"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


SCRIPT = Path(__file__).with_name("task_sync.py")
BRANCH = "codex/task-auto-sync"
RESULTS = []
ENV = dict(os.environ, PYTHONUTF8="1", GIT_CONFIG_NOSYSTEM="1")


def run(*args, cwd=None, expected=0):
    result = subprocess.run(list(map(str, args)), cwd=cwd, env=ENV,
                            capture_output=True, encoding="utf-8", errors="replace", timeout=90)
    if result.returncode != expected:
        raise AssertionError(f"验证命令返回码不符：{result.returncode}；{result.stdout}；{result.stderr}")
    return result.stdout.strip()


def record(name):
    RESULTS.append(name)
    print("通过：" + name, flush=True)


def verify(base):
    remote, repo, peer = (base / name for name in ("远程.git", "工作 仓库", "协作者"))
    empty_hooks = base / "空钩子"
    empty_hooks.mkdir()
    run("git", "init", "--bare", remote)
    run("git", "init", "-b", BRANCH, repo)

    def git(*args, location=repo, expected=0):
        return run("git", "-C", location, *args, expected=expected)

    def configure(location):
        git("config", "user.name", "自动化验证", location=location)
        git("config", "user.email", "verification@example.invalid", location=location)
        git("config", "core.hooksPath", empty_hooks.as_posix(), location=location)
        git("config", "commit.gpgsign", "false", location=location)

    def sync(*args, expected=0):
        return run(sys.executable, SCRIPT, "--repo", repo, "--branch", BRANCH,
                   *args, expected=expected)

    def remote_head():
        return git("rev-parse", "refs/heads/" + BRANCH, location=remote)

    configure(repo)
    (repo / "src").mkdir()
    source = repo / "src" / "任务.txt"
    source.write_text("初始内容\n", encoding="utf-8")
    git("add", "src")
    git("commit", "-m", "建立测试基线")
    git("remote", "add", "origin", remote.as_posix())
    git("push", "-u", "origin", BRANCH)

    source.write_text("任务完成\n", encoding="utf-8")
    (repo / "未完成.txt").write_text("保留在工作区\n", encoding="utf-8")
    sync("--commit", "--paths", "src", "--message", "自动化验证：完成任务")
    assert git("rev-parse", "HEAD") == remote_head()
    assert "未完成.txt" not in git("ls-tree", "-r", "--name-only", "HEAD")
    record("自动提交指定路径并推送，其他文件保持未跟踪")

    before = git("rev-parse", "HEAD")
    sync("--commit", "--paths", "src")
    assert git("rev-parse", "HEAD") == before
    record("重复执行不产生空提交")

    source.write_text("仍在编辑\n", encoding="utf-8")
    sync()
    assert git("rev-parse", "HEAD") == before
    git("add", "src")
    sync("--commit", "--paths", "src", expected=3)
    assert git("rev-parse", "HEAD") == before
    record("只推送模式不提交草稿，自动提交拒绝占用已有暂存区")
    git("commit", "-m", "人工完成暂存任务")
    sync()

    source.write_text("断网时完成的任务\n", encoding="utf-8")
    git("remote", "set-url", "origin", (base / "不存在的远程.git").as_posix())
    old_remote = remote_head()
    sync("--commit", "--paths", "src", expected=5)
    preserved = git("rev-parse", "HEAD")
    assert preserved != old_remote and remote_head() == old_remote
    git("remote", "set-url", "origin", remote.as_posix())
    sync()
    assert remote_head() == preserved
    record("远程不可用时保留本地提交，恢复后只补推，不重复提交")

    git("config", "remote.origin.mirror", "true")
    git("config", "push.followTags", "true")
    git("tag", "-a", "automation-test-tag", "-m", "不应被附带推送的测试标签")
    source.write_text("验证仅推送任务分支\n", encoding="utf-8")
    sync("--commit", "--paths", "src")
    assert git("show-ref", "--tags", location=remote, expected=1) == ""
    git("config", "--unset", "remote.origin.mirror")
    git("config", "--unset", "push.followTags")
    record("已有镜像和附带标签配置不会扩大推送范围")

    run("git", "clone", "--branch", BRANCH, remote, peer)
    configure(peer)
    (peer / "协作者.txt").write_text("协作者变动\n", encoding="utf-8")
    git("add", ".", location=peer)
    git("commit", "-m", "协作者提交", location=peer)
    git("push", location=peer)
    old_remote = remote_head()
    source.write_text("本地独立变动\n", encoding="utf-8")
    sync("--commit", "--paths", "src", expected=3)
    assert remote_head() == old_remote
    git("merge", "--no-edit", "FETCH_HEAD")
    sync()
    assert git("rev-parse", "HEAD") == remote_head()
    record("远程分叉时停止且不覆盖，人工合并后恢复推送")

    git("switch", "-c", "codex/other")
    sync(expected=3)
    git("switch", BRANCH)
    git("checkout", "--detach")
    sync(expected=3)
    git("switch", BRANCH)
    record("其他分支与分离指针状态均被拒绝")

    hooks = base / "测试钩子"
    hooks.mkdir()
    git("config", "core.hooksPath", hooks.as_posix())
    (hooks / "pre-commit").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8", newline="\n")
    source.write_text("检查不通过的任务\n", encoding="utf-8")
    before = remote_head()
    sync("--commit", "--paths", "src", expected=5)
    assert git("rev-parse", "HEAD") == before == remote_head()
    assert git("diff", "--cached", "--name-only")
    git("config", "core.hooksPath", empty_hooks.as_posix())
    git("commit", "-m", "检查修复后提交")
    sync()
    record("提交前检查失败时不推送，暂存内容保留供人工处理")

    # 实际安装示例钩子，验证人工提交触发推送和自动提交防递归。
    hook_text = SCRIPT.with_name("post-commit.example").read_text(encoding="utf-8")
    hook_text = hook_text.replace("C:/Users/14431/AppData/Local/Programs/Python/Python311/python.exe", Path(sys.executable).as_posix())
    hook_text = hook_text.replace("E:/Git/cmd/git.exe", Path(shutil.which("git")).as_posix())
    (hooks / "post-commit").write_text(hook_text, encoding="utf-8", newline="\n")
    (hooks / "pre-commit").unlink()
    git("config", "core.hooksPath", hooks.as_posix())
    source.write_text("人工提交触发钩子\n", encoding="utf-8")
    git("add", "src")
    git("commit", "-m", "验证提交后推送")
    assert git("rev-parse", "HEAD") == remote_head()
    source.write_text("自动提交跳过递归钩子\n", encoding="utf-8")
    sync("--commit", "--paths", "src")
    assert git("rev-parse", "HEAD") == remote_head()
    git("config", "core.hooksPath", empty_hooks.as_posix())
    record("提交后钩子实际推送成功，自动提交不会递归调用同步")

    # 两端修改同一文件，制造真实合并冲突。
    git("pull", "--ff-only", location=peer)
    (peer / "src" / "任务.txt").write_text("远程冲突内容\n", encoding="utf-8")
    git("add", "src", location=peer)
    git("commit", "-m", "远程冲突提交", location=peer)
    git("push", location=peer)
    source.write_text("本地冲突内容\n", encoding="utf-8")
    git("add", "src")
    git("commit", "-m", "本地冲突提交")
    git("fetch", "origin", BRANCH)
    git("merge", "--no-edit", "FETCH_HEAD", expected=1)
    sync(expected=3)
    git("merge", "--abort")
    record("真实合并冲突存在时停止同步")

    # 操作系统文件锁可阻止另一个同步进程进入。
    sys.path.insert(0, str(SCRIPT.parent))
    from task_sync import repository_lock
    common = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir"))
    with repository_lock(common / "task-sync.lock"):
        sync(expected=4)
    record("并发运行时由仓库锁拦截")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="git-sync-验证-") as directory:
        verify(Path(directory))
    summary = {"说明": "隔离的本地裸仓库集成验证，不涉及真实远程或计划任务注册", "通过数量": len(RESULTS), "通过项目": RESULTS}
    SCRIPT.with_name("验证结果.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("全部验证通过，共 " + str(len(RESULTS)) + " 项。")
