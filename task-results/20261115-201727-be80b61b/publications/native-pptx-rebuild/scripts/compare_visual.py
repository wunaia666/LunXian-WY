"""生成同尺寸叠加、绝对差异、局部检查图与版本绑定的数值记录，不自动判定视觉达标。"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rgb(path):
    with Image.open(path) as image:
        background = Image.new("RGBA", image.size, "white")
        background.alpha_composite(image.convert("RGBA"))
        return background.convert("RGB")


def metrics(first, second, threshold):
    difference = np.abs(np.asarray(first).astype(np.int16) - np.asarray(second).astype(np.int16))
    return {"平均通道绝对差": float(difference.mean()), "最大通道差": int(difference.max()),
            "超过定位阈值的像素占比": float((difference.max(axis=2) > threshold).mean())}


def compare(source_path, rendered_path, pptx_path, output_dir, objects_path=None, crop_ids=(), threshold=12, audit_record=None):
    input_hashes = {str(Path(path).resolve()): digest(path) for path in (source_path, rendered_path, pptx_path)}
    if not 0 <= threshold <= 255:
        raise ValueError("差异定位阈值必须在0至255之间；它不是验收合格线。")
    source, rendered = rgb(source_path), rgb(rendered_path)
    if source.size != rendered.size:
        raise ValueError("尺寸不一致，必须重新原生导出；禁止自动缩放或配准掩盖错位。")
    provenance = "待确认：未提供原生导出检查记录"
    if audit_record is not None:
        evidence = json.loads(Path(audit_record).read_text(encoding="utf-8"))
        native = evidence.get("实际打开与原生检查", {})
        matched = [row for row in native.get("原尺寸对照", []) if row.get("渲染图摘要") == digest(rendered_path) and row.get("原图摘要") == digest(source_path)]
        if evidence.get("文件摘要") != digest(pptx_path) or not evidence.get("检查期间文件版本一致") or native.get("状态") != "已验证" or not matched:
            raise ValueError("导出记录、最终文件或对照图版本不一致，必须重新渲染和核验。")
        provenance = "已验证：原生导出记录与原图、渲染图及最终文件摘要一致"
    registry = json.loads(Path(objects_path).read_text(encoding="utf-8")) if objects_path else None
    regions = []
    if registry is not None:
        if registry.get("原图尺寸") != list(source.size):
            raise ValueError("对象登记中的原图尺寸与本次原图不一致。")
        if registry.get("原图摘要") and registry["原图摘要"] != digest(source_path):
            raise ValueError("对象登记对应其他原图版本。")
        if registry.get("最终文件摘要") and registry["最终文件摘要"] != digest(pptx_path):
            raise ValueError("对象登记对应其他最终文稿版本。")
        seen = set()
        for item in registry.get("对象", []):
            identifier = item.get("对象编号")
            if not isinstance(identifier, str) or not identifier or identifier in seen:
                raise ValueError("对象编号未填写或重复。")
            seen.add(identifier)
            box = item.get("原图坐标和尺寸", [])
            if len(box) != 4 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and np.isfinite(v) for v in box):
                raise ValueError(f"对象坐标未实测：{identifier}")
            x, y, width, height = box
            if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > source.width or y + height > source.height:
                raise ValueError(f"对象区域超出原图：{identifier}")
            bounds = (int(np.floor(x)), int(np.floor(y)), int(np.ceil(x + width)), int(np.ceil(y + height)))
            regions.append((identifier, bounds))
        if not set(crop_ids) <= seen:
            raise ValueError("请求放大的对象编号未出现在登记表中。")
    elif crop_ids:
        raise ValueError("局部放大需要对象登记文件。")
    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError("本轮对照目录非空，请换新目录，避免混用旧证据。")
    output_dir.mkdir(parents=True, exist_ok=True)
    small = output_dir / "_ai小图"
    small.mkdir()

    def save(image, stem):
        full = output_dir / f"{stem}.png"
        image.save(full)
        preview = image.copy()
        preview.thumbnail((1568, 1568), Image.Resampling.LANCZOS)
        preview.save(small / f"{stem}.jpg", quality=82, optimize=True)
        return str(full.resolve())

    difference = ImageChops.difference(source, rendered)
    # 差异图放大数值便于定位；原始差值另行保留，不作为自动合格判定。
    heat = Image.fromarray(np.minimum(np.asarray(difference).astype(np.uint16) * 4, 255).astype(np.uint8))
    side = Image.new("RGB", (source.width * 2, source.height))
    side.paste(source, (0, 0))
    side.paste(rendered, (source.width, 0))
    report = {"状态": "待确认", "说明": "已生成量化与图像证据；仍需局部视觉复核、差异修正和真实可编辑性测试。",
              "原图": str(Path(source_path).resolve()), "原图摘要": digest(source_path),
              "渲染图": str(Path(rendered_path).resolve()), "渲染图摘要": digest(rendered_path),
              "最终文件": str(Path(pptx_path).resolve()), "最终文件摘要": digest(pptx_path),
              "渲染来源核验": provenance,
              "像素尺寸": list(source.size), "差异定位阈值": threshold,
              "整页误差": metrics(source, rendered, threshold), "对象区域": [],
              "图像证据": {"并排": save(side, "并排对照"), "叠加": save(Image.blend(source, rendered, .5), "半透明叠加"),
                           "原始绝对差": save(difference, "原始绝对差"), "差异增强": save(heat, "差异增强")}}
    for index, (identifier, bounds) in enumerate(regions, 1):
        first, second = source.crop(bounds), rendered.crop(bounds)
        row = {"对象编号": identifier, "原图边界": bounds, "误差": metrics(first, second, threshold), "复核状态": "待确认"}
        if identifier in crop_ids:
            local = Image.new("RGB", (first.width * 2, first.height))
            local.paste(first, (0, 0))
            local.paste(second, (first.width, 0))
            # 从原尺寸裁出后放大，便于查看小字和边缘；不回写整页数值证据。
            if max(local.size) < 1200:
                scale = min(4, 1200 / max(local.size))
                local = local.resize((round(local.width * scale), round(local.height * scale)), Image.Resampling.NEAREST)
            row["局部并排"] = save(local, f"局部_{index:03d}")
        report["对象区域"].append(row)
    if any(digest(path) != before for path, before in input_hashes.items()):
        raise ValueError("对照期间输入版本变化，证据作废，必须重新生成。")
    (output_dir / "视觉对照记录.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description="对同尺寸原图与原生渲染图生成叠加和差异证据。", add_help=False)
    parser.add_argument("-h", "--help", action="help", help="显示帮助")
    parser.add_argument("source", type=Path, help="原始参考图")
    parser.add_argument("rendered", type=Path, help="原生导出的同尺寸图片")
    parser.add_argument("--pptx", type=Path, required=True, help="产生该渲染的最终演示文件")
    parser.add_argument("--output-dir", type=Path, required=True, help="本轮独立对照目录")
    parser.add_argument("--objects", type=Path, help="本页已经填写的对象登记文件")
    parser.add_argument("--crop-ids", nargs="*", default=[], help="需要生成局部放大图的对象编号")
    parser.add_argument("--threshold", type=int, default=12, help="仅供定位的像素差阈值，不是合格线")
    parser.add_argument("--audit-record", type=Path, help="同尺寸原生导出检查记录，用于验证文件版本一致")
    args = parser.parse_args()
    try:
        result = compare(args.source, args.rendered, args.pptx, args.output_dir, args.objects, args.crop_ids, args.threshold, args.audit_record)
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, f"对照未完成：{error}\n")
    print(f"已生成视觉证据，验收状态仍为{result['状态']}：{args.output_dir}")


if __name__ == "__main__":
    main()
