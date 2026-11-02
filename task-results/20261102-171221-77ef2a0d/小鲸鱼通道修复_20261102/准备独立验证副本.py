"""只解压腾讯官方文件到独立目录，不执行安装、不改原目录、不启动客户端。"""

import hashlib
import json
import subprocess
from pathlib import Path, PureWindowsPath

import pefile


ROOT = Path(__file__).parent
DESTINATION = Path(r"E:\sss\小鲸鱼QQ兼容验证")
ARCHIVE = ROOT / "客户端候选_未安装/内部只读核对/官方资源_101.7z"
INSTALLER = ROOT / "客户端候选_未安装/QQ_9.9.33_260813_x64_01.exe"
EXPECTED = "b25c0d3ce9df764074a9118d0ded927e1b2d7ebf60e306112e8df18a040ec492"
EXTRACTOR = r"C:\Program Files\Bandizip\bz.exe"


def command(arguments, timeout):
    return subprocess.run([EXTRACTOR,*arguments],capture_output=True,timeout=timeout,
                          check=True,creationflags=subprocess.CREATE_NO_WINDOW)


def main():
    if hashlib.sha256(INSTALLER.read_bytes()).hexdigest() != EXPECTED:
        raise RuntimeError("官方包摘要不符")
    if DESTINATION.exists():
        raise RuntimeError("独立目录已经存在，停止覆盖")
    # 压缩资源直接取自已核对的官方安装包，不信任来源不明的缓存文件。
    package = pefile.PE(str(INSTALLER), fast_load=True)
    package.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
    resources = [item for item in package.DIRECTORY_ENTRY_RESOURCE.entries if str(item.name) == "MSI"]
    payloads = [item for group in resources for item in group.directory.entries if item.id == 101]
    if len(payloads) != 1:
        raise RuntimeError("官方包内压缩资源结构不符")
    resource = payloads[0].directory.entries[0].data.struct
    payload = package.get_data(resource.OffsetToData, resource.Size)
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    if not ARCHIVE.exists() or hashlib.sha256(ARCHIVE.read_bytes()).digest() != hashlib.sha256(payload).digest():
        ARCHIVE.write_bytes(payload)
    entries = command(["l","-list:s","-consolemode:utf8",str(ARCHIVE)],30).stdout.decode("utf-8").splitlines()
    for name in entries:
        if not name.strip():
            continue
        path = PureWindowsPath(name)
        if path.is_absolute() or ".." in path.parts or path.parts[0] != "Files":
            raise RuntimeError("官方压缩包内存在预期外路径")
    DESTINATION.mkdir(parents=True)
    command(["x","-y","-consolemode:utf8","-o:"+str(DESTINATION),str(ARCHIVE)],180)
    files = DESTINATION / "Files"
    package = json.loads((files/"versions/9.9.33-52230/resources/app/package.json").read_text(encoding="utf-8"))
    if package["version"] != "9.9.33-52230" or not (files/"QQ.exe").exists():
        raise RuntimeError("独立副本的版本文件不完整")
    config = files / "versions/config.json"
    if not config.exists():
        config.write_text(json.dumps({"baseVersion":"9.9.33-52230","curVersion":"9.9.33-52230",
            "prevVersion":"","onErrorVersions":[],"buildId":"52230","unzipRetryCount":0},
            ensure_ascii=False,indent=2),encoding="utf-8")
    value = {"入口":str(files/"QQ.exe"),"版本":package["version"],"已核对压缩条目":len(entries),
             "覆盖原安装":False,"启动客户端":False,"兼容性":"尚待用户手动启动后实际验证"}
    (ROOT/"独立副本准备结果.local.json").write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(value,ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()
