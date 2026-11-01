"""保存同作者动画的真实对白切片，保留出处，不将角色画面当成同声线证明。"""

import hashlib
import json
import subprocess
import wave
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    folder = Path(__file__).resolve().parent
    output = folder / "同作者说话候选"
    output.mkdir(exist_ok=True)
    references = []
    for identifier, name, start, end, text in (
        (
            "7693925369702878499",
            "01_粉色角色_选择台词.wav",
            13.30,
            16.95,
            "小孩子才做选择，我全都要。",
        ),
        (
            "7693925369702878499",
            "02_粉色角色_不好玩台词.wav",
            17.45,
            20.80,
            "不好玩，还是不好玩。",
        ),
        (
            "7654195128684482171",
            "04_生日动画_睁眼台词.wav",
            18.05,
            21.35,
            "主人，你可以睁眼了。",
        ),
    ):
        source_folder = folder / "同作者素材" / identifier
        metadata = json.loads(
            (source_folder / "原视频提取记录.json").read_text(encoding="utf-8")
        )
        source = source_folder / "原始素材" / metadata["完整音轨文件"]
        if (
            metadata["作品编号"] != identifier
            or metadata["作者"] != "卖唱的doro"
            or digest(source) != metadata["音轨摘要"]
        ):
            raise RuntimeError("同作者原始音轨的来源或摘要不符")
        destination = output / name
        subprocess.run(
            [
                r"E:\sss_test\apps\ShareX\ffmpeg.exe",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-ss",
                str(start),
                "-t",
                str(end - start),
                "-ar",
                "32000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(destination),
            ],
            check=True,
        )
        with wave.open(str(destination), "rb") as stream:
            duration = stream.getnframes() / stream.getframerate()
        if abs(duration - (end - start)) > 0.01 or not 3 <= duration <= 10:
            raise RuntimeError("对白片段时长异常或不符合原引擎参考限制")
        references.append(
            {
                "文件": name,
                "作品编号": identifier,
                "作品地址": metadata["作品地址"],
                "源音频摘要": metadata["音轨摘要"],
                "起始秒": start,
                "结束秒": end,
                "秒数": round(duration, 3),
                "文字": text,
                "摘要": digest(destination),
                "类型": "同作者动画中的真实对白，未调速、未变调，声线待核对",
            }
        )
    result = {
        "作者": "卖唱的doro",
        "参考": references,
        "声线状态": "同作者动画中确实存在对白，但各角色与用户指定原唱是否同一声线尚未确认",
        "用途": "独立对照试听，不能直接纳入日常语音或作为训练合格数据",
    }
    (folder / "真实对白参考记录.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
