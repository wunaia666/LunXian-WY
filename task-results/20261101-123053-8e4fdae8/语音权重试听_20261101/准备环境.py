"""从用户提供的便携包准备独立试音环境，原包与原权重保持不变。"""

import hashlib
import json
import shutil
import sys
import time
import zipfile
from pathlib import Path, PurePosixPath

folder = Path(__file__).resolve().parent
archive = Path(sys.argv[1])
voice_pack = Path(sys.argv[2])
engine = folder / "engine"
assets = folder / "assets"
engine.mkdir(exist_ok=True)
assets.mkdir(exist_ok=True)

with zipfile.ZipFile(archive) as package:
    files = [item for item in package.infolist() if not item.is_dir()]
    required = sum(item.file_size for item in files)
    if shutil.disk_usage(folder).free < required + 512 * 1024**2:
        raise RuntimeError("工作盘空间不足，未开始解压")
    started = time.monotonic()
    for index, item in enumerate(files, 1):
        pieces = PurePosixPath(item.filename).parts[1:]
        if not pieces or any(
            part in {".", ".."} or ":" in part or "\\" in part for part in pieces
        ):
            raise RuntimeError("压缩包包含不安全路径，已停止")
        target = engine.joinpath(*pieces)
        if not target.resolve().is_relative_to(engine.resolve()):
            raise RuntimeError("解压目标超出独立环境")
        target.parent.mkdir(parents=True, exist_ok=True)
        with package.open(item) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)
        if index % 5000 == 0:
            print(
                json.dumps(
                    {
                        "已准备文件": index,
                        "总文件": len(files),
                        "耗时秒": round(time.monotonic() - started),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

for original, name in [
    (voice_pack / "权重/manhui-e1.ckpt", "mansui.ckpt"),
    (voice_pack / "权重/manhui_e12_s420.pth", "mansui.pth"),
    (voice_pack / "参考音频/ref_concat.wav", "mansui_ref.wav"),
]:
    shutil.copy2(original, assets / name)
    if (
        hashlib.sha256(original.read_bytes()).digest()
        != hashlib.sha256((assets / name).read_bytes()).digest()
    ):
        raise RuntimeError("权重或参考音频复制校验失败")

models = [
    {
        "id": "mansui",
        "name": "满穗",
        "gpt": "assets/mansui.ckpt",
        "sovits": "assets/mansui.pth",
        "reference": "assets/mansui_ref.wav",
        "prompt": "我之前装成哑巴是怕被银沙认出来我怕他问的多了会起疑心你们不是把我们送去富贵人家",
    },
    {
        "id": "doro",
        "name": "便携包音色",
        "gpt": "engine/GPT_weights_v2Pro/doro-e15.ckpt",
        "sovits": "engine/SoVITS_weights_v2Pro/doro_e20_s1580.pth",
        "reference": "engine/ref/ref_doro_a.wav",
        "prompt": "环绕着闪动影子的电流追回那幽暗的老时光",
    },
]
for model in models:
    for key in ("gpt", "sovits", "reference"):
        path = folder / model[key]
        model[key + "_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with (folder / model["sovits"]).open("rb") as stream:
        if stream.read(2) != b"05":
            raise RuntimeError("声学权重并非预期的第二代专业版，未尝试转换")

(folder / "资源配置.local.json").write_text(
    json.dumps({"models": models}, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(
    json.dumps(
        {
            "状态": "独立环境与两组权重准备完成",
            "模型": [model["name"] for model in models],
        },
        ensure_ascii=False,
    ),
    flush=True,
)
