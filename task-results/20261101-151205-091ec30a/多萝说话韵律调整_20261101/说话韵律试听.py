"""保留乙参考音色，关闭参考发声序列续写，比较两种语义权重。"""

import argparse
import gc
import hashlib
import importlib
import json
import os
import sys
import time
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description="乙参考说话韵律本地对照")
    parser.add_argument(
        "--semantic", choices=["trained", "base", "guided"], required=True
    )
    parser.add_argument("--length", choices=["short", "long", "all"], default="all")
    parser.add_argument("--cpu", action="store_true")
    args = parser.parse_args()
    folder = Path(__file__).resolve().parent
    resources = json.loads((folder / "资源配置.local.json").read_text(encoding="utf-8"))
    engine = Path(resources["engine_root"]).resolve()
    model = resources["models"][0]
    semantic_key = "gpt" if args.semantic == "trained" else "base_gpt"
    for key in (semantic_key, "sovits", "reference"):
        if sha256(Path(model[key])) != model[key + "_sha256"]:
            raise RuntimeError("权重或乙参考摘要不一致，停止生成")
    os.chdir(str(engine))
    os.environ["PATH"] = (
        str(engine / "runtime") + os.pathsep + os.environ.get("PATH", "")
    )
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    cache = folder / "work/cache"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(cache / "huggingface")
    os.environ["HF_HUB_CACHE"] = str(cache / "huggingface/hub")
    os.environ["TRANSFORMERS_CACHE"] = str(cache / "transformers")
    os.environ["TORCH_HOME"] = str(cache / "torch")
    sys.path.insert(0, str(engine))
    sys.path.insert(0, str(engine / "GPT_SoVITS"))
    torch = importlib.import_module("torch")
    np = importlib.import_module("numpy")
    sf = importlib.import_module("soundfile")
    torch.set_num_threads(4)

    # 沿用便携包的缺词兼容处理；不屏蔽其他加载错误。
    wordfreq = importlib.import_module("wordfreq")
    for name in ("word_frequency", "zipf_frequency"):
        original = getattr(wordfreq, name)

        def safe_frequency(*values, _original=original, **keywords):
            try:
                return _original(*values, **keywords)
            except KeyError:
                return 0.0

        setattr(wordfreq, name, safe_frequency)
    try:
        from split_lang.detect_lang import detector

        detector.word_frequency = wordfreq.word_frequency
    except ImportError:
        pass

    from GPT_SoVITS.TTS_infer_pack.TTS import TTS, TTS_Config

    device = "cpu" if args.cpu or not torch.cuda.is_available() else "cuda"
    if device == "cuda" and torch.cuda.mem_get_info()[0] < 2200 * 1024**2:
        device = "cpu"
    work = folder / "work"
    work.mkdir(exist_ok=True)
    settings = {
        "device": device,
        "is_half": device == "cuda",
        "version": "v2Pro",
        "t2s_weights_path": model[semantic_key],
        "vits_weights_path": model["sovits"],
        "bert_base_path": str(
            engine / "GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large"
        ),
        "cnhuhbert_base_path": str(
            engine / "GPT_SoVITS/pretrained_models/chinese-hubert-base"
        ),
    }
    config = TTS_Config({"custom": settings})
    config.configs_path = str(work / (args.semantic + "_infer.yaml"))
    pipeline = TTS(config)
    if (
        Path(pipeline.configs.t2s_weights_path).resolve()
        != Path(model[semantic_key]).resolve()
        or Path(pipeline.configs.vits_weights_path).resolve()
        != Path(model["sovits"]).resolve()
        or pipeline.configs.use_vocoder
    ):
        raise RuntimeError("加载权重或版本不符，停止生成")

    infer_calls = []
    guided_semantic = None
    guide = None
    if args.semantic == "guided":
        guide_row = next(
            row
            for row in json.loads(
                (folder / "base_试听记录.json").read_text(encoding="utf-8")
            )
            if row.get("file") == "02_基础语义_保留乙音色.wav" and row.get("ok")
        )
        guide_path = folder / "试听音频" / guide_row["file"]
        if sha256(guide_path) != guide_row["audio_sha256"]:
            raise RuntimeError("同音色引导短句发生变化")
        pipeline.set_ref_audio(model["reference"])
        original_spec = pipeline.prompt_cache["refer_spec"][0]
        pipeline._set_prompt_semantic(str(guide_path))
        guided_semantic = pipeline.prompt_cache["prompt_semantic"].clone()
        if (
            pipeline.prompt_cache["refer_spec"][0] is not original_spec
            or pipeline.prompt_cache["ref_audio_path"] != model["reference"]
        ):
            raise RuntimeError("同音色引导替换了乙参考音色，停止生成")
        guide = {
            "file": guide_path.name,
            "sha256": guide_row["audio_sha256"],
            "text": guide_row["text"],
        }
    # 引擎每次运行都会重新选择入口，因此检查实际使用的串行批次方法。
    original_infer = pipeline.t2s_model.model.infer_panel_naive_batched

    def checked_infer(*values, **keywords):
        prompt = values[2] if len(values) > 2 else keywords.get("prompts")
        if guided_semantic is None:
            if prompt is not None:
                raise RuntimeError("参考发声序列仍被送入语义生成，停止生成")
            evidence = "未传入"
        else:
            if prompt is None or not torch.equal(prompt[0], guided_semantic):
                raise RuntimeError("语义引导并非约定的同音色短句")
            evidence = "仅同音色短句引导，未传入乙参考发声序列"
        predicted, lengths = original_infer(*values, **keywords)
        # 无参考模式返回的零是保留全部序列的截取索引，不是生成长度。
        infer_calls.append(
            {"参考发声序列": evidence, "引擎截取索引": [int(n) for n in lengths]}
        )
        return predicted, lengths

    pipeline.t2s_model.model.infer_panel_naive_batched = checked_infer
    cases = [
        ("short", "同句短语", "老爸，你回来啦！我刚才还在想你呢。今天过得怎么样呀？"),
        (
            "long",
            "连续长段",
            "老爸，你回来啦。今天过得怎么样？我刚才看到一只小猫，躲在纸箱里不肯出来。"
            "它把尾巴露在外面，还以为谁都看不见。你要是忙累了，就先歇一会儿吧。"
            "不用着急回我，我会在这里等你。",
        ),
    ]
    output = folder / "试听音频"
    output.mkdir(exist_ok=True)
    receipt = folder / (args.semantic + "_试听记录.json")
    rows = json.loads(receipt.read_text(encoding="utf-8")) if receipt.is_file() else []
    source_sha = sha256(Path(__file__).resolve())
    engine_sha = sha256(engine / "GPT_SoVITS/TTS_infer_pack/TTS.py")
    for length, title, text in cases:
        if args.length != "all" and args.length != length:
            continue
        filename = {
            ("trained", "short"): "01_原权重_关闭韵律续写.wav",
            ("base", "short"): "02_基础语义_保留乙音色.wav",
            ("trained", "long"): "03_原权重_长段.wav",
            ("base", "long"): "04_基础语义_长段.wav",
            ("guided", "short"): "05_同音色说话引导_短句.wav",
            ("guided", "long"): "06_同音色说话引导_长段.wav",
        }[(args.semantic, length)]
        path = output / filename
        request = {
            "text": text,
            "text_lang": "zh",
            "ref_audio_path": model["reference"],
            "prompt_text": guide["text"] if guide else "",
            "prompt_lang": "zh",
            "text_split_method": "cut5",
            "speed_factor": 1.0,
            "temperature": 0.8,
            "top_k": 15,
            "top_p": 1.0,
            "repetition_penalty": 1.35,
            "seed": 1,
            "batch_size": 1,
            "return_fragment": False,
            "parallel_infer": False,
            "fragment_interval": 0.18,
        }
        signature = {
            "request": request,
            "gpt_sha256": model[semantic_key + "_sha256"],
            "sovits_sha256": model["sovits_sha256"],
            "reference_sha256": model["reference_sha256"],
            "script_sha256": source_sha,
            "engine_sha256": engine_sha,
            "semantic_guide": guide,
        }
        input_sha = hashlib.sha256(
            json.dumps(signature, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if path.is_file() and any(
            row.get("ok")
            and row.get("input_sha256") == input_sha
            and row.get("audio_sha256") == sha256(path)
            for row in rows
        ):
            continue
        infer_calls.clear()
        began = time.monotonic()
        try:
            chunks = []
            sample_rate = 0
            for sample_rate, signal in pipeline.run(request):
                chunks.append(np.asarray(signal))
            if not chunks or not infer_calls:
                raise RuntimeError("没有实际生成语音")
            signal = np.concatenate(chunks)
            duration = len(signal) / sample_rate
            if duration < 1 or np.max(np.abs(signal.astype(np.float64))) < 2:
                raise RuntimeError("生成结果过短或近乎静音")
            sf.write(str(path), signal, sample_rate, subtype="PCM_16")
            row = {
                "ok": True,
                "file": filename,
                "title": title,
                "text": text,
                "semantic": args.semantic,
                "semantic_name": {
                    "trained": "原训练语义权重",
                    "base": "便携包自带基础语义权重",
                    "guided": "基础语义权重与同音色说话引导",
                }[args.semantic],
                "semantic_guide": guide,
                "duration": round(duration, 3),
                "synth_seconds": round(time.monotonic() - began, 2),
                "device": device,
                "reference_file": "ref_doro_b.wav",
                "gpt_sha256": model[semantic_key + "_sha256"],
                "sovits_sha256": model["sovits_sha256"],
                "reference_sha256": model["reference_sha256"],
                "input_sha256": input_sha,
                "audio_sha256": sha256(path),
                "request": request,
                "infer_calls": list(infer_calls),
                "production_changed": False,
                "sent_messages": False,
                "evaluation": "待试听，不代表已消除唱腔",
            }
        except Exception as error:
            row = {"ok": False, "file": filename, "error": str(error)[:300]}
        rows = [item for item in rows if item.get("file") != filename] + [row]
        receipt.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(row, ensure_ascii=False), flush=True)
        gc.collect()
        if device == "cuda":
            torch.cuda.empty_cache()
    expected = 2 if args.length == "all" else 1
    selected = [
        row
        for row in rows
        if args.length == "all"
        or row.get("title") == {"short": "同句短语", "long": "连续长段"}[args.length]
    ]
    if len(selected) < expected or any(not row.get("ok") for row in selected):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
