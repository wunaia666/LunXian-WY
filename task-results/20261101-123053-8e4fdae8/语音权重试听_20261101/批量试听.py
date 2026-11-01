"""配对加载两组训练权重，生成本地对照语音，不改写原包和日常配置。"""

import argparse
import gc
import hashlib
import importlib
import json
import os
import sys
import time
from pathlib import Path

folder = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description="训练权重本地试音")
parser.add_argument("--model", choices=["mansui", "doro"], required=True)
parser.add_argument("--cpu", action="store_true")
args = parser.parse_args()
engine = folder / "engine"
os.chdir(str(engine))
os.environ["PATH"] = str(engine / "runtime") + os.pathsep + os.environ.get("PATH", "")
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
cache = folder / "work/cache"
cache.mkdir(parents=True, exist_ok=True)
os.environ["HF_HOME"] = str(cache / "huggingface")
os.environ["HF_HUB_CACHE"] = str(cache / "huggingface/hub")
os.environ["TRANSFORMERS_CACHE"] = str(cache / "transformers")
os.environ["TORCH_HOME"] = str(cache / "torch")
os.environ["XDG_CACHE_HOME"] = str(cache)
sys.path.insert(0, str(engine))
sys.path.insert(0, str(engine / "GPT_SoVITS"))

torch = importlib.import_module("torch")
np = importlib.import_module("numpy")
sf = importlib.import_module("soundfile")

torch.set_num_threads(4)
resources = json.loads((folder / "资源配置.local.json").read_text(encoding="utf-8"))
model = next(row for row in resources["models"] if row["id"] == args.model)
for key in ("gpt", "sovits", "reference"):
    path = folder / model[key]
    if hashlib.sha256(path.read_bytes()).hexdigest() != model[key + "_sha256"]:
        raise RuntimeError("权重或参考音频摘要不符，未加载")

# 便携包已包含此兼容处理；这里只处理缺词，其他错误仍正常报出。
wordfreq = importlib.import_module("wordfreq")

for function_name in ("word_frequency", "zipf_frequency"):
    original = getattr(wordfreq, function_name)

    def safe_frequency(*values, _original=original, **keywords):
        try:
            return _original(*values, **keywords)
        except KeyError:
            return 0.0

    setattr(wordfreq, function_name, safe_frequency)
try:
    from split_lang.detect_lang import detector

    detector.word_frequency = wordfreq.word_frequency
except ImportError:
    pass

tts_module = importlib.import_module("GPT_SoVITS.TTS_infer_pack.TTS")
TTS, TTS_Config = tts_module.TTS, tts_module.TTS_Config

device = "cpu" if args.cpu or not torch.cuda.is_available() else "cuda"
if device == "cuda" and torch.cuda.mem_get_info()[0] < 2200 * 1024**2:
    device = "cpu"
settings = {
    "device": device,
    "is_half": device == "cuda",
    "version": "v2Pro",
    "t2s_weights_path": str(folder / model["gpt"]),
    "vits_weights_path": str(folder / model["sovits"]),
    "bert_base_path": str(
        engine / "GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large"
    ),
    "cnhuhbert_base_path": str(
        engine / "GPT_SoVITS/pretrained_models/chinese-hubert-base"
    ),
}
work = folder / "work"
work.mkdir(exist_ok=True)
config = TTS_Config({"custom": settings})
config.configs_path = str(work / (args.model + "_infer.yaml"))
started = time.monotonic()
pipeline = TTS(config)
if (
    Path(pipeline.configs.t2s_weights_path).resolve()
    != (folder / model["gpt"]).resolve()
    or Path(pipeline.configs.vits_weights_path).resolve()
    != (folder / model["sovits"]).resolve()
):
    raise RuntimeError("实际加载权重不符，未采用默认音色")
print(
    json.dumps(
        {
            "音色": model["name"],
            "状态": "两份权重均已加载",
            "设备": device,
            "加载秒数": round(time.monotonic() - started, 2),
        },
        ensure_ascii=False,
    ),
    flush=True,
)

cases = [
    (
        "01_daily",
        "日常招呼",
        "老爸，你回来啦！我刚才还在想你呢。今天过得怎么样呀？",
        1.0,
        1.0,
    ),
    (
        "02_comfort",
        "安慰台词",
        "今天是不是有点累呀？没关系，先坐下来歇一会儿。你不用急着解释，我会认真听你慢慢说。",
        1.0,
        0.98,
    ),
    (
        "03_playful",
        "撒娇台词",
        "哼，你终于想起我啦？我才没有一直等你呢。好吧，其实有一点点。那你今天要多陪我聊一会儿，好不好？",
        1.1,
        1.0,
    ),
    (
        "04_long",
        "连续长段",
        "老爸，你回来啦。今天过得怎么样？我刚才看到一只小猫，躲在纸箱里不肯出来。它把尾巴露在外面，还以为谁都看不见。你要是忙累了，就先歇一会儿吧。不用着急回我，我会在这里等你。",
        1.0,
        1.0,
    ),
]
output_dir = folder / "试听音频"
output_dir.mkdir(exist_ok=True)
receipt = folder / (args.model + "_试听记录.json")
rows = json.loads(receipt.read_text(encoding="utf-8")) if receipt.is_file() else []
for identifier, title, text, temperature, speed in cases:
    path = output_dir / (args.model + "_" + identifier + ".wav")
    if (
        any(
            row.get("file") == path.name and row.get("text") == text and row.get("ok")
            for row in rows
        )
        and path.is_file()
    ):
        continue
    request = {
        "text": text,
        "text_lang": "zh",
        "ref_audio_path": str(folder / model["reference"]),
        "prompt_text": model["prompt"],
        "prompt_lang": "zh",
        "text_split_method": "cut0",
        "speed_factor": speed,
        "temperature": temperature,
        "top_k": 15,
        "top_p": 1.0,
        "repetition_penalty": 1.35,
        "sample_steps": 32,
        "seed": 1,
        "batch_size": 1,
        "return_fragment": False,
        "parallel_infer": False,
    }
    began = time.monotonic()
    try:
        chunks = []
        sample_rate = 0
        for sample_rate, signal in pipeline.run(request):
            chunks.append(np.asarray(signal))
        if not chunks:
            raise RuntimeError("没有生成音频")
        signal = np.concatenate(chunks)
        duration = len(signal) / sample_rate
        peak = float(np.max(np.abs(signal.astype(np.float64))))
        if duration < 0.5 or peak < 0.0001 or (len(text) > 35 and duration < 3):
            raise RuntimeError("音频为空、过短或近乎静音，未作为成功样例")
        sf.write(str(path), signal, sample_rate, subtype="PCM_16")
        row = {
            "ok": True,
            "model": model["name"],
            "title": title,
            "file": path.name,
            "text": text,
            "duration": round(duration, 3),
            "synth_seconds": round(time.monotonic() - began, 2),
            "temperature": temperature,
            "speed": speed,
            "seed": 1,
            "reference_sha256": model["reference_sha256"],
            "gpt_sha256": model["gpt_sha256"],
            "sovits_sha256": model["sovits_sha256"],
            "device": device,
            "sent_messages": False,
            "production_changed": False,
            "evaluation": "待试听",
        }
    except Exception as error:
        row = {
            "ok": False,
            "model": model["name"],
            "title": title,
            "text": text,
            "error": str(error)[:300],
        }
    rows = [item for item in rows if item.get("title") != title] + [row]
    receipt.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(row, ensure_ascii=False), flush=True)
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
if any(not row.get("ok") for row in rows) or len(rows) < len(cases):
    raise SystemExit(1)
