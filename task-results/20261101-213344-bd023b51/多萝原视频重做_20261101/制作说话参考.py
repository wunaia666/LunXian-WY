"""从完整增强人声制作背景抑制参考和说话韵律实验参考，始终保留原声。"""

import hashlib
import json
import subprocess
from pathlib import Path

import librosa
import numpy as np
import pyworld
import soundfile as sf
import torch
import whisper
from scipy.interpolate import interp1d
from whisper.timing import find_alignment
from whisper.tokenizer import get_tokenizer


def pitch_shape(position, tone):
    if tone == 1:
        return 1.6 - 0.2 * position
    if tone == 2:
        return -1.8 + 4.0 * position
    if tone == 3:
        return np.interp(position, [0, 0.65, 1], [-1.8, -3.8, -0.7])
    if tone == 4:
        return 2.3 - 5.0 * position
    return -0.8 - position


def main():
    folder = Path(__file__).resolve().parent
    source = folder / "处理素材/完整增强人声.wav"
    data, sample_rate = sf.read(str(source), dtype="float64", always_2d=True)
    audio = librosa.resample(data.mean(1), orig_sr=sample_rate, target_sr=32000)
    sample_rate = 32000
    reference_text = "就算全世界离开你，还有一个我来陪。"
    analysis = json.loads((folder / "原声分析结果.json").read_text(encoding="utf-8"))
    words = analysis["分段"][0]["词位置"] + analysis["分段"][1]["词位置"]
    boundaries = []
    for word in words:
        text = word["文字"].strip()
        for index in range(len(text)):
            start = word["起始秒"] + (word["结束秒"] - word["起始秒"]) * index / len(
                text
            )
            end = word["起始秒"] + (word["结束秒"] - word["起始秒"]) * (
                index + 1
            ) / len(text)
            boundaries.append((start, end))
    characters = "就算全世界离开你还有一个我来陪"
    tones = [4, 4, 2, 4, 4, 2, 1, 3, 2, 3, 2, 4, 3, 2, 2]
    if len(boundaries) != len(characters):
        raise RuntimeError("参考片段字数与自动定位不符，不能盲目重整")
    end_time = boundaries[-1][1]
    clean = np.ascontiguousarray(audio[: round(end_time * sample_rate)])
    peak = np.max(np.abs(clean))
    if peak < 0.0001:
        raise RuntimeError("分离参考近乎静音")
    clean *= min(2.0, 0.9 / peak)
    # 以净化后的声音对齐已知台词，避免把混合伴奏下的错字时间直接用于改声调。
    torch.set_num_threads(4)
    align_model = whisper.load_model(
        r"E:\sss_test\models\whisper\base.pt", device="cpu"
    )
    tokenizer = get_tokenizer(multilingual=True, language="zh", task="transcribe")
    audio16k = librosa.resample(clean, orig_sr=sample_rate, target_sr=16000).astype(
        np.float32
    )
    mel = whisper.log_mel_spectrogram(whisper.pad_or_trim(audio16k))
    alignment = find_alignment(
        align_model, tokenizer, tokenizer.encode(characters), mel, len(audio16k) // 160
    )
    aligned = []
    aligned_text = ""
    for word in alignment:
        text = word.word.strip()
        aligned_text += text
        for index in range(len(text)):
            aligned.append(
                (
                    word.start + (word.end - word.start) * index / len(text),
                    word.start + (word.end - word.start) * (index + 1) / len(text),
                )
            )
    if aligned_text != characters or len(aligned) != len(characters):
        raise RuntimeError("已知台词对齐不完整，未把错位参考继续用于生成")
    edges = (
        [0.0]
        + [
            (aligned[index - 1][1] + aligned[index][0]) / 2
            for index in range(1, len(aligned))
        ]
        + [end_time]
    )
    boundaries = list(zip(edges[:-1], edges[1:]))
    if any(end - start < 0.03 for start, end in boundaries):
        raise RuntimeError("已知台词对齐产生异常短音节，需要核对")
    del align_model
    output = folder / "参考候选"
    output.mkdir(exist_ok=True)
    clean_path = output / "01_背景抑制参考.wav"
    sf.write(str(clean_path), clean, sample_rate, subtype="PCM_16")
    frame_period = 5.0
    f0, times = pyworld.harvest(
        clean, sample_rate, f0_floor=150, f0_ceil=1000, frame_period=frame_period
    )
    f0 = pyworld.stonemask(clean, f0, times, sample_rate)
    voiced = f0[f0 > 0]
    if len(voiced) < 0.1 * len(f0):
        raise RuntimeError("人声基频提取不足，未盲目生成说话参考")
    median = float(np.median(voiced))
    spectrum = pyworld.cheaptrick(clean, f0, times, sample_rate)
    aperiodic = pyworld.d4c(clean, f0, times, sample_rate, threshold=0.0)
    source_positions = []
    new_pitches = []
    silence_indices = []
    timing = []
    cursor = 0.0
    for index, ((start, end), character, tone) in enumerate(
        zip(boundaries, characters, tones)
    ):
        duration = end - start
        positions = np.arange(0, duration, frame_period / 1000)
        duration = len(positions) * frame_period / 1000
        # 此阶段保留原始音节时长，避免不准的定位压坏辅音。
        onset = min(0.05, (end - start) * 0.2)
        ending = min(0.035, (end - start) * 0.15)
        mapped = np.interp(
            positions,
            [0, onset, duration - ending, duration],
            [start, start + onset, end - ending, end],
        )
        original_f0 = np.interp(mapped, times, f0)
        semitones = (
            pitch_shape(positions / duration, tone)
            + 0.3
            - 0.6 * index / len(characters)
        )
        target_f0 = median * 2 ** (semitones / 12)
        target_f0[original_f0 < 1] = 0
        source_positions.extend(mapped.tolist())
        new_pitches.extend(target_f0.tolist())
        timing.append(
            {
                "字": character,
                "声调": tone,
                "原起始秒": round(start, 3),
                "原结束秒": round(end, 3),
                "新起始秒": round(cursor, 3),
                "新时长秒": duration,
            }
        )
        cursor += duration
        if index == 7:
            pause_frames = 28
            silence_indices.extend(
                range(len(source_positions), len(source_positions) + pause_frames)
            )
            source_positions.extend([end] * pause_frames)
            new_pitches.extend([0.0] * pause_frames)
            cursor += pause_frames * frame_period / 1000
    source_positions = np.asarray(source_positions)
    new_pitches = np.ascontiguousarray(new_pitches, dtype=np.float64)
    new_spectrum = np.ascontiguousarray(
        interp1d(times, spectrum, axis=0, fill_value="extrapolate")(source_positions)
    )
    new_spectrum[silence_indices] = 1e-12
    new_aperiodic = np.ascontiguousarray(
        np.clip(
            interp1d(times, aperiodic, axis=0, fill_value="extrapolate")(
                source_positions
            ),
            0.001,
            1,
        )
    )
    reconstructed = pyworld.synthesize(
        new_pitches, new_spectrum, new_aperiodic, sample_rate, frame_period
    )
    reconstructed *= min(1.0, 0.92 / max(float(np.max(np.abs(reconstructed))), 1e-8))
    speech_path = output / "02_说话韵律实验参考.wav"
    work = folder / "work"
    work.mkdir(exist_ok=True)
    intermediate = work / "保留发音细节的声调重整.wav"
    sf.write(str(intermediate), reconstructed, sample_rate, subtype="PCM_16")
    subprocess.run(
        [
            r"E:\sss_test\apps\ShareX\ffmpeg.exe",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(intermediate),
            "-af",
            "atempo=1.6",
            str(speech_path),
        ],
        check=True,
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    reconstructed, _ = sf.read(str(speech_path), dtype="float64")
    for item in timing:
        item["新起始秒"] = round(item["新起始秒"] / 1.6, 3)
        item["新时长秒"] = round(item["新时长秒"] / 1.6, 3)
    result = {
        "参考文字": reference_text,
        "文字依据": "前两句采用用户分享文案；自动识别中的春字依照分享文案校为全字",
        "源音频摘要": hashlib.sha256(source.read_bytes()).hexdigest(),
        "原声位置": [0.0, end_time],
        "原人声音高中位数": round(median, 2),
        "时间处理": "完整保留音节细节完成声调重整后，再统一使用不改变音高的变速；首版逐音节过度压缩已撤出候选",
        "定位方式": "净化人声对已知分享台词的声学对齐，不把此对齐当作独立吐字识别通过",
        "参考": [
            {
                "文件": clean_path.name,
                "秒数": round(len(clean) / sample_rate, 3),
                "摘要": hashlib.sha256(clean_path.read_bytes()).hexdigest(),
                "类型": "背景抑制后的原唱参考，不宣称是说话",
            },
            {
                "文件": speech_path.name,
                "秒数": round(len(reconstructed) / sample_rate, 3),
                "摘要": hashlib.sha256(speech_path.read_bytes()).hexdigest(),
                "类型": "同一段人声的音节时长与声调重整实验，不是提取到的真实说话录音",
            },
        ],
        "音节定位": timing,
        "局限": "字级定位来自自动识别；音高重整会影响自然度和情绪，需要试听验证，不据此宣布去唱腔完成",
    }
    (folder / "参考制作记录.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "音节定位"},
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
