"""每次绘图使用独立进程，结束后自动释放显存。"""

import json
import sys
from pathlib import Path

# 计算运行时沿用绘图环境，额外依赖单独存放，避免混入语音环境的原生库。
sys.path.insert(0, r"E:\sss_test\local_media_packages")

import torch
from diffusers import AutoPipelineForImage2Image, AutoPipelineForText2Image
from PIL import Image, ImageOps


def main():
    """读取结构化任务，生成一张实际图片。"""
    task = json.loads(sys.stdin.read())
    output = Path(task["output"]).resolve()
    allowed = Path(r"E:\sss_test\dafeiyu_assets\generated").resolve()
    if not output.is_relative_to(allowed):
        raise ValueError("图片输出目录无效")
    output.parent.mkdir(parents=True, exist_ok=True)
    reference = None
    if task.get("reference_path"):
        reference_path = Path(task["reference_path"]).resolve()
        if (
            not reference_path.is_relative_to(allowed / "references")
            or not reference_path.is_file()
        ):
            raise ValueError("参考图目录无效")
        with Image.open(reference_path) as picture:
            reference = ImageOps.fit(picture.convert("RGB"), (512, 512))
    pipeline = (
        AutoPipelineForImage2Image
        if reference is not None
        else AutoPipelineForText2Image
    )
    pipe = pipeline.from_pretrained(
        r"E:\sss_test\models\sd-turbo",
        torch_dtype=torch.float16,
        variant="fp16",
        local_files_only=True,
    )
    pipe.enable_sequential_cpu_offload(gpu_id=0)
    pipe.set_progress_bar_config(disable=True)
    generator = torch.Generator(device="cpu").manual_seed(int(task["seed"]))
    result = pipe(
        prompt=str(task["prompt"])[:1200],
        **(
            {
                "image": reference,
                "strength": max(0.25, min(0.8, float(task.get("strength", 0.45)))),
            }
            if reference is not None
            else {"height": 512, "width": 512}
        ),
        num_inference_steps=4,
        guidance_scale=0.0,
        generator=generator,
    )
    result.images[0].save(output)
    print(json.dumps({"ok": True, "path": str(output)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
