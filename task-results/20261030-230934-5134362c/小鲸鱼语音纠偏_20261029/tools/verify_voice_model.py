# -*- coding: utf-8 -*-
"""回迁模型自检：文件齐全、能加载、显存够用、能出声、和指定原声的差距。

在 WSL 内运行，例：
  python /mnt/e/sss_test/tools/verify_voice_model.py --engine cosyvoice3 \
      --model-dir /home/lun-xian/models/Fun-CosyVoice3-0.5B-2512
只读检查，不改动日常配置，试听文件写到 dafeiyu_assets/audio/voice_diag/migration。
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "6")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

HOME = os.path.expanduser("~")
REPO = os.environ.get("COSY_REPO", os.path.join(HOME, "CosyVoice"))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "third_party", "Matcha-TTS"))

REFERENCE = Path("/mnt/e/sss_test/dafeiyu_assets/audio/_cosy_ref/ref_douyin_link_7689724715246372473.wav")
OUT = Path("/mnt/e/sss_test/dafeiyu_assets/audio/voice_diag/migration")
REQUIRED = {
    "cosyvoice2": ["cosyvoice2.yaml", "campplus.onnx", "speech_tokenizer_v2.onnx", "llm.pt", "flow.pt", "hift.pt"],
    "cosyvoice3": ["cosyvoice3.yaml", "campplus.onnx", "speech_tokenizer_v3.onnx", "llm.pt", "flow.pt", "hift.pt", "CosyVoice-BlankEN"],
}
MIN_FREE_VRAM_MB = 2200


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def main() -> int:
    parser = argparse.ArgumentParser(description="回迁语音模型自检")
    parser.add_argument("--engine", choices=["cosyvoice2", "cosyvoice3"], default="cosyvoice3")
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--probe", default="老爸，你回来啦！")
    parser.add_argument("--no-synth", action="store_true")
    parser.add_argument("--no-load", action="store_true", help="只核对文件，不加载模型（不占显存）")
    args = parser.parse_args()

    model_dir = Path(args.model_dir)
    report = {"model_dir": str(model_dir), "engine": args.engine, "checks": [], "ok": True}

    if not model_dir.is_dir():
        report["checks"].append({"item": "目录存在", "ok": False, "detail": "目录不存在"})
        report["ok"] = False
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 2

    for name in REQUIRED[args.engine]:
        path = model_dir / name
        if not path.exists():
            report["checks"].append({"item": name, "ok": False, "detail": "缺失"})
            report["ok"] = False
        else:
            size = path.stat().st_size if path.is_file() else sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
            report["checks"].append({"item": name, "ok": True, "detail": human(size)})

    yaml_name = "cosyvoice3.yaml" if args.engine == "cosyvoice3" else "cosyvoice2.yaml"
    yaml_path = model_dir / yaml_name
    if yaml_path.is_file():
        head = yaml_path.read_text(encoding="utf-8", errors="ignore")[:400]
        report["yaml_head"] = head.splitlines()[:6]

    if args.no_load:
        report["checks"].append({"item": "跳过加载", "ok": True, "detail": "只核对文件"})
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0 if report["ok"] else 1

    import torch
    if not torch.cuda.is_available():
        report["ok"] = False
        report["checks"].append({"item": "CUDA", "ok": False, "detail": "不可用"})
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 3
    free_before = int(torch.cuda.mem_get_info()[0] / 1048576)
    report["vram_free_before_mb"] = free_before
    if free_before < MIN_FREE_VRAM_MB:
        report["ok"] = False
        report["checks"].append({"item": "显存余量", "ok": False, "detail": f"{free_before}MB，请先停掉服务或模拟器"})
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 4

    from cosyvoice.cli.cosyvoice import CosyVoice2, CosyVoice3
    torch.set_num_threads(6)
    started = time.time()
    try:
        if args.engine == "cosyvoice3":
            model = CosyVoice3(str(model_dir), fp16=True)
        else:
            model = CosyVoice2(str(model_dir), load_jit=False, load_trt=False, fp16=True)
        model.model.llm.half()
        model.model.flow.half()
        torch.cuda.empty_cache()
    except Exception as error:
        report["ok"] = False
        report["checks"].append({"item": "模型加载", "ok": False, "detail": f"{type(error).__name__}: {error}"})
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 5
    used, free = [int(v / 1048576) for v in torch.cuda.mem_get_info()]
    report["load_s"] = round(time.time() - started, 1)
    report["vram_used_mb"] = int((torch.cuda.get_device_properties(0).total_memory - free) / 1048576)
    report["vram_free_after_mb"] = int(free / 1048576)
    report["checks"].append({"item": "模型加载", "ok": True, "detail": f"{report['load_s']}s，显存余 {report['vram_free_after_mb']}MB"})

    if not args.no_synth:
        OUT.mkdir(parents=True, exist_ok=True)
        import numpy as np
        import soundfile as sf
        import librosa
        target = OUT / "回迁自检.wav"
        try:
            if args.engine == "cosyvoice3":
                prompt = "You are a helpful assistant. 用自然轻松的语气说。<|endofprompt|>"
                pieces = [i["tts_speech"].detach().float().cpu() for i in model.inference_instruct2(args.probe, prompt, str(REFERENCE), stream=False)]
            else:
                pieces = [i["tts_speech"].detach().float().cpu() for i in model.inference_instruct2(args.probe, "用自然轻松的语气说", str(REFERENCE), stream=False)]
            audio = torch.cat(pieces, dim=1).squeeze(0).numpy()
            sf.write(str(target), audio, model.sample_rate, subtype="PCM_16")
            f0, _, _ = librosa.pyin(librosa.resample(audio, orig_sr=model.sample_rate, target_sr=16000), fmin=60, fmax=1000, sr=16000, frame_length=1024)
            valid = f0[~np.isnan(f0)]
            emb_ref = model.frontend._extract_spk_embedding(str(REFERENCE)).detach().float().cpu().numpy().reshape(-1)
            emb_out = model.frontend._extract_spk_embedding(str(target)).detach().float().cpu().numpy().reshape(-1)
            cos = float(np.dot(emb_ref, emb_out) / (np.linalg.norm(emb_ref) * np.linalg.norm(emb_out) + 1e-12))
            report["sample"] = {"file": str(target), "dur": round(len(audio) / model.sample_rate, 2),
                                "f0_median": round(float(np.median(valid)), 1) if len(valid) else None,
                                "cosine_vs_reference": round(cos, 4)}
            report["checks"].append({"item": "试合成", "ok": True, "detail": json.dumps(report["sample"], ensure_ascii=False)})
        except Exception as error:
            report["ok"] = False
            report["checks"].append({"item": "试合成", "ok": False, "detail": f"{type(error).__name__}: {error}"})

    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())