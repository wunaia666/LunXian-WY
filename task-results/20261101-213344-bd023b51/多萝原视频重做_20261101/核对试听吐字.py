"""自动转写试听供漏字排查，不能用转写正确代替音色、唱腔或情绪验收。"""

import hashlib
import json
from pathlib import Path

import librosa
import torch
import whisper


def main():
    folder = Path(__file__).resolve().parent
    receipt = folder / "试听吐字核对.local.json"
    previous = (
        json.loads(receipt.read_text(encoding="utf-8")) if receipt.is_file() else []
    )
    cached = {row["音频摘要"]: row for row in previous}
    cases = []
    for name in (
        "原视频重做试听记录.json",
        "训练权重组合试听记录.json",
        "真实对白原配对试听记录.json",
        "生日对白原配对试听记录.json",
    ):
        metadata = json.loads((folder / name).read_text(encoding="utf-8"))
        cases.extend(metadata["试听"])
    torch.set_num_threads(4)
    model = None
    checked = []
    for row in cases:
        path = folder / "试听音频" / row["文件"]
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha != row["音频摘要"]:
            raise RuntimeError("试听音轨与来源记录不符")
        if sha in cached:
            checked.append(cached[sha])
            continue
        if model is None:
            model = whisper.load_model(
                r"E:\sss_test\models\whisper\base.pt", device="cpu"
            )
        audio, _ = librosa.load(str(path), sr=16000, mono=True)
        result = model.transcribe(
            audio,
            language="zh",
            fp16=False,
            temperature=0,
            condition_on_previous_text=False,
        )
        item = {
            "文件": row["文件"],
            "音频摘要": sha,
            "预期文字": row["文案"],
            "自动识别": result.get("text", ""),
            "分段对数概率": [round(s["avg_logprob"], 3) for s in result["segments"]],
            "结论边界": "仅用于人工排查漏字；同音字、漏识别和识别幻觉均可能存在，听感待用户验收",
        }
        checked.append(item)
        receipt.write_text(
            json.dumps(checked, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(item, ensure_ascii=False), flush=True)
    receipt.write_text(
        json.dumps(checked, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
