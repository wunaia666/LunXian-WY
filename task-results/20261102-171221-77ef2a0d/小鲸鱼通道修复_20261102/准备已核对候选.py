"""下载微软分发清单登记的腾讯官方候选，仅保存并核对摘要，不安装启动。"""

import hashlib
import json
import urllib.request
from pathlib import Path


ROOT = Path(__file__).parent
URL = "https://qqdl.gtimg.cn/qqfile/QQNT/9.9.33/release/497e2f1f/QQ_9.9.33_260813_x64_01.exe"
EXPECTED = "b25c0d3ce9df764074a9118d0ded927e1b2d7ebf60e306112e8df18a040ec492"


def main():
    folder = ROOT / "客户端候选_未安装"
    folder.mkdir(exist_ok=True)
    target = folder / "QQ_9.9.33_260813_x64_01.exe"
    temporary = target.with_suffix(".part")
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(URL, timeout=30) as response, temporary.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > 1024 * 1024 * 1024:
                raise RuntimeError("候选包大小超出限制")
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != EXPECTED:
        raise RuntimeError("候选包与微软分发清单摘要不符，未转为可用安装文件")
    temporary.replace(target)
    value = {"版本":"9.9.33.52230","文件":str(target),"字节数":size,
             "摘要":digest.hexdigest(),"摘要与微软分发清单一致":True,
             "来源":URL,"已安装":False,"已启动":False,"兼容性":"待实际验证"}
    (ROOT/"官方候选核对.local.json").write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(value,ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()
