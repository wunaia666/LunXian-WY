"""用原引擎声纹模型比较候选片段，分数只作排查，不替代用户音色验收。"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="比较候选声线，诊断分数不代表听感验收")
    parser.add_argument(
        "--scan-dialogue", action="store_true", help="扫描新增动画的对白时间窗"
    )
    args = parser.parse_args()
    folder = Path(__file__).resolve().parent
    root = Path(r"E:\sss\语音权重试听_20261101\engine")
    os.chdir(root)
    sys.path.insert(0, str(root / "GPT_SoVITS"))
    import numpy as np
    import soundfile as sf
    import torch
    from sv import SV
    from torchaudio.functional import resample

    torch.set_num_threads(4)
    model = SV("cpu", False)

    def embedding(path):
        signal, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
        return embed_signal(signal.mean(1), sample_rate)

    def embed_signal(signal, sample_rate):
        signal = torch.from_numpy(signal.copy()).unsqueeze(0)
        if sample_rate != 16000:
            signal = resample(signal, sample_rate, 16000)
        if signal.shape[-1] < 16000:
            raise RuntimeError("候选有效声音过短")
        signal = signal / signal.abs().max().clamp_min(1e-8) * 0.8
        vector = model.compute_embedding3(signal).reshape(-1).cpu().numpy()
        return vector / max(float(np.linalg.norm(vector)), 1e-8)

    anchor_path = folder / "参考候选/01_背景抑制参考.wav"
    anchor = embedding(anchor_path)
    if args.scan_dialogue:
        windows = []
        for identifier in ("7654195128684482171", "7655688156221590836"):
            source_folder = folder / "同作者素材" / identifier
            source = json.loads(
                (source_folder / "原视频提取记录.json").read_text(encoding="utf-8")
            )
            transcript = json.loads(
                (source_folder / "完整音轨识别.local.json").read_text(encoding="utf-8")
            )
            path = source_folder / "原始素材" / source["完整音轨文件"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != source["音轨摘要"]:
                raise RuntimeError("扫描音轨与原始记录不符")
            signal, rate = sf.read(str(path), dtype="float32")
            for row in transcript["片段"]:
                start, end = row["起始秒"], row["结束秒"]
                if not 1.3 <= end - start <= 8:
                    continue
                # 已明确标出的生日歌不当成说话候选。
                if identifier == "7654195128684482171" and 28.3 <= start < 38.4:
                    continue
                vector = embed_signal(
                    signal[round(start * rate) : round(end * rate)], rate
                )
                windows.append(
                    {
                        "作品编号": identifier,
                        "起始秒": start,
                        "结束秒": end,
                        "自动识别": row["文字"],
                        "诊断余弦": round(float(np.dot(anchor, vector)), 4),
                    }
                )
        windows.sort(key=lambda row: -row["诊断余弦"])
        (folder / "同作者对白声线扫描.local.json").write_text(
            json.dumps(windows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "对白窗数": len(windows),
                    "优先核对": windows[:8],
                    "边界": "短句、唱歌与说话差异会影响分数；排序仅帮助定位，不能证明同一声线",
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return
    paths = sorted((folder / "同作者说话候选").glob("*.wav"))
    paths.extend(sorted((folder / "试听音频").glob("*.wav")))
    paths.append(
        Path(
            r"E:\QQ\doro语音合成_便携版.zip\doro语音合成_便携版\doro语音合成\ref\ref_doro_b.wav"
        )
    )
    records = []
    for path in paths:
        score = float(np.dot(anchor, embedding(path)))
        records.append(
            {
                "文件": path.name,
                "与指定视频原声的诊断余弦": round(score, 4),
                "音频摘要": hashlib.sha256(path.read_bytes()).hexdigest(),
                "用途": "相对比较与排除明显不同角色，不代表音色验收",
            }
        )
    result = {
        "锚点": anchor_path.name,
        "锚点摘要": hashlib.sha256(anchor_path.read_bytes()).hexdigest(),
        "比较": records,
        "限制": "唱歌与说话、背景声和情绪均影响分数；同作者与同角色画面不能证明是同一声线",
    }
    (folder / "候选声线诊断.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
