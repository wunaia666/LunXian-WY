#!/usr/bin/env python3
"""任务完成后提交指定路径，并以普通推送同步指定分支。"""

import argparse
import contextlib
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys


class StopSync(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


@contextlib.contextmanager
def repository_lock(path):
    # 锁文件保留在磁盘；是否占锁由操作系统判断，进程退出后自动释放。
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise StopSync(4, "另一同步进程正在运行，本次跳过。")
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser(description=__doc__, add_help=False,
                                     usage="%(prog)s --repo 仓库目录 --branch 任务分支 [其他参数]")
    parser._optionals.title = "可选参数"
    parser.add_argument("-h", "--help", action="help", help="显示帮助并退出")
    parser.add_argument("--repo", required=True, help="仓库根目录")
    parser.add_argument("--branch", required=True, help="唯一允许同步的分支")
    parser.add_argument("--remote", default="origin", help="远程仓库名称")
    parser.add_argument("--git", default="git", help="版本控制程序路径")
    parser.add_argument("--commit", action="store_true", help="提交任务路径；默认只推送")
    parser.add_argument("--paths", nargs="+", help="相对仓库根目录的任务文件或目录")
    parser.add_argument("--message", default="自动提交：任务完成", help="提交说明")
    parser.add_argument("--timeout", type=int, default=60, help="单条命令最长秒数")
    options = parser.parse_args()
    logger = logging.getLogger("task_sync")
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler())
    repo = Path(options.repo).resolve()
    executable = shutil.which(options.git)
    if not executable or not repo.is_dir() or options.timeout < 1:
        raise StopSync(2, "程序路径、仓库目录或超时参数无效。")
    environment = os.environ.copy()
    environment.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never", AUTOSYNC_ACTIVE="1")
    environment.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=yes")

    def git(*arguments, allowed=(0,), failure=5, settings=()):
        command = [executable, "-C", str(repo)]
        for setting in settings:
            command.extend(["-c", setting])
        command.extend(arguments)
        creation = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        # 使用临时文件收集输出，避免大型命令输出耗尽内存。
        import tempfile
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(command, env=environment, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=output, **creation)
            try:
                process.wait(timeout=options.timeout)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run([os.path.join(os.environ["SystemRoot"], "System32", "taskkill.exe"),
                                    "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
                raise StopSync(5, "命令超时，已尝试结束该命令及其子进程；请检查仓库状态后重试。")
            output.seek(0, 2)
            size = output.tell()
            output.seek(max(0, size - 16384))
            result = output.read().decode("utf-8", errors="replace").strip()
        if process.returncode not in allowed:
            # 原始错误可能包含远程地址，只在本机控制台显示，不写入滚动日志。
            if result:
                print(result, file=sys.stderr)
            raise StopSync(failure, f"操作失败：{arguments[0]}，程序返回码：{process.returncode}。")
        return process.returncode, result

    _, root = git("rev-parse", "--show-toplevel", failure=2)
    if Path(root).resolve() != repo:
        raise StopSync(2, "必须指定仓库根目录，不能指定仓库子目录。")
    _, common = git("rev-parse", "--path-format=absolute", "--git-common-dir", failure=2)
    _, local = git("rev-parse", "--absolute-git-dir", failure=2)
    with repository_lock(Path(common) / "task-sync.lock"):
        handler = RotatingFileHandler(Path(local) / "task-sync.log", maxBytes=1048576,
                                      backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)
        try:
            git("check-ref-format", "--branch", options.branch, failure=2)
            code, current = git("symbolic-ref", "--quiet", "--short", "HEAD", allowed=(0, 1))
            if code or current != options.branch:
                raise StopSync(3, "当前分支不在许可范围，或当前处于分离指针状态。")
            if options.branch in ("main", "master"):
                raise StopSync(2, "示例仅允许任务分支，请先创建独立任务分支。")
            for state in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "REBASE_HEAD",
                          "rebase-merge", "rebase-apply", "sequencer", "BISECT_LOG", "index.lock"):
                _, location = git("rev-parse", "--git-path", state)
                target = Path(location)
                if not target.is_absolute():
                    target = repo / target
                if target.exists():
                    raise StopSync(3, "仓库正在执行其他操作或存在索引锁，请先处理完成。")
            _, unmerged = git("ls-files", "--unmerged")
            if unmerged:
                raise StopSync(3, "存在未解决冲突，停止同步。")
            _, fetch_urls = git("remote", "get-url", "--all", options.remote, failure=2)
            _, push_urls = git("remote", "get-url", "--push", "--all", options.remote, failure=2)
            if len(fetch_urls.splitlines()) != 1 or fetch_urls != push_urls:
                raise StopSync(2, "示例要求同一远程的拉取和推送地址一致，且各有一个地址。")
            if options.commit:
                if not options.paths:
                    raise StopSync(2, "自动提交必须明确指定任务路径。")
                paths = []
                for item in options.paths:
                    if Path(item).is_absolute():
                        raise StopSync(2, "任务路径必须是仓库内的相对路径。")
                    try:
                        relative = (repo / item).resolve().relative_to(repo).as_posix()
                    except ValueError:
                        raise StopSync(2, "任务路径不能超出仓库。")
                    if relative == "." or relative.split("/")[0].lower() == ".git":
                        raise StopSync(2, "请指定任务文件或子目录，不能选择整个仓库。")
                    paths.append(":(top,literal)" + relative)
                code, _ = git("diff", "--cached", "--quiet", allowed=(0, 1))
                if code:
                    raise StopSync(3, "暂存区已有改动，请先人工确认，避免混入其他任务。")
                git("add", "-A", "--", *paths)
                code, _ = git("diff", "--cached", "--quiet", allowed=(0, 1))
                if code:
                    # 保留已有提交检查钩子；提交后的示例钩子会通过环境标记避免递归。
                    git("commit", "-m", options.message)
                    logger.info("任务改动已提交。")
                else:
                    logger.info("指定路径没有新改动，继续检查未推送提交。")
            # 远程分支必须先由人工创建，避免分支名填错而创建意外分支。
            ref = "refs/heads/" + options.branch
            git("fetch", "--no-tags", options.remote, ref)
            _, remote_head = git("rev-parse", "FETCH_HEAD")
            _, local_head = git("rev-parse", "HEAD")
            if local_head == remote_head:
                logger.info("本地与远程提交一致，无需推送。")
                return 0
            code, _ = git("merge-base", "--is-ancestor", remote_head, local_head, allowed=(0, 1))
            if code:
                raise StopSync(3, "远程领先或双方已分叉；保留本地提交，请人工整合后重试。")
            _, current = git("symbolic-ref", "--quiet", "--short", "HEAD")
            _, latest = git("rev-parse", "HEAD")
            if current != options.branch or latest != local_head:
                raise StopSync(3, "运行期间分支或提交发生变化，本次停止。")
            # 固定本次提交对象，普通推送；远程并发更新仍由服务端拒绝。
            git("push", "--porcelain", "--no-force", "--no-mirror", "--no-follow-tags",
                "--recurse-submodules=no", options.remote, local_head + ":" + ref,
                settings=(f"remote.{options.remote}.mirror=false",))
            logger.info("推送成功，提交标识：%s", local_head)
            return 0
        except StopSync as error:
            logger.error("同步未完成；返回码：%s；%s", error.code, error)
            raise


if __name__ == "__main__":
    try:
        sys.exit(main())
    except StopSync as error:
        print(str(error), file=sys.stderr)
        sys.exit(error.code)
    except (OSError, subprocess.SubprocessError) as error:
        print("运行环境异常，请检查程序路径、权限和进程状态。", file=sys.stderr)
        sys.exit(2)
