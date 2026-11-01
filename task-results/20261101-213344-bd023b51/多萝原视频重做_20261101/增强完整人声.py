"""复用本机已存在的人声增强模型处理完整音轨，残差不宣称是纯伴奏。"""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf


def main():
    folder = Path(__file__).resolve().parent
    checkpoint = Path(
        r"E:\sss_test\clearvoice_work\checkpoints\MossFormer2_SE_48K\last_best_checkpoint.pt"
    )
    if not checkpoint.is_file() or checkpoint.stat().st_size != 221552019:
        raise RuntimeError("本机现有人声增强权重缺失或大小异常，不自动替换")
    before = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    work = folder / "work"
    output = folder / "处理素材"
    work.mkdir(exist_ok=True)
    output.mkdir(exist_ok=True)
    source = folder / "原始素材/7500493303280946470_完整原音.wav"
    input_path = work / "完整输入48k.wav"
    subprocess.run(
        [
            r"E:\sss_test\apps\ShareX\ffmpeg.exe",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-ac",
            "1",
            "-ar",
            "48000",
            str(input_path),
        ],
        check=True,
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    os.chdir(r"E:\sss_test\clearvoice_work")
    from clearvoice import ClearVoice

    model = ClearVoice(task="speech_enhancement", model_names=["MossFormer2_SE_48K"])
    print("正在使用本机现有权重增强完整人声。", flush=True)
    enhanced = model(input_path=str(input_path), online_write=False)
    enhanced_path = output / "完整增强人声.wav"
    model.write(enhanced, output_path=str(enhanced_path))
    signal, sample_rate = sf.read(str(enhanced_path), dtype="float32", always_2d=True)
    original, source_rate = sf.read(str(input_path), dtype="float32", always_2d=True)
    if sample_rate != source_rate or abs(len(signal) - len(original)) > 480:
        raise RuntimeError("增强音轨时长或采样率与完整输入不符")
    length = min(len(signal), len(original))
    residual = original[:length].mean(1) - signal[:length].mean(1)
    sf.write(
        str(output / "增强残差_非纯伴奏.wav"), residual, sample_rate, subtype="PCM_16"
    )
    # 后续制作参考只读取这个明确标注为增强结果的统一入口。
    if np.max(np.abs(signal)) < 0.0001:
        raise RuntimeError("增强结果近乎静音")
    if hashlib.sha256(checkpoint.read_bytes()).hexdigest() != before:
        raise RuntimeError("现有人声增强权重在处理期间变化")
    report = {
        "完整输入秒数": round(len(original) / source_rate, 3),
        "完整输出秒数": round(len(signal) / sample_rate, 3),
        "增强模型": "本机已有的四万八千赫兹人声增强模型",
        "增强权重摘要": before,
        "输出": enhanced_path.name,
        "输出摘要": hashlib.sha256(enhanced_path.read_bytes()).hexdigest(),
        "说明": "这是降噪与背景抑制结果，不能宣称已完全分离伴奏或去除原唱韵律",
        "可选音乐分离模型": "下载过慢已停止；没有把未完成下载记作分离成功",
    }
    (folder / "完整人声增强记录.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
