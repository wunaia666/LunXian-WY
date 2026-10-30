# -*- coding: utf-8 -*-
"""生成桌面语音试听页：复制音频到同目录，页内直接试听对照。"""
import json, shutil, sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
target = Path(manifest["target"])
target.mkdir(parents=True, exist_ok=True)
rows = []
for item in manifest["items"]:
    src = Path(item["path"])
    if not src.is_file():
        continue
    dst = target / src.name
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)
    rows.append({**item, "name": dst.name})

cards = []
for i, row in enumerate(rows):
    metrics = " · ".join(f"{k} {v}" for k, v in row.get("metrics", {}).items())
    cards.append(f"""
    <article class="card">
      <header><span class="index">{i+1:02d}</span><h2>{row['title']}</h2></header>
      <p class="desc">{row.get('desc','')}</p>
      <audio controls preload="metadata" src="{row['name']}"></audio>
      <p class="meta">{metrics}</p>
    </article>""")

html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{manifest.get('title','小鲸鱼语音试听')}</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:40px 24px 64px; background:#0f1419; color:#e6edf3;
         font:16px/1.7 "Microsoft YaHei", system-ui, sans-serif; }}
  main {{ max-width: 980px; margin: 0 auto; }}
  h1 {{ font-size: 30px; margin: 0 0 8px; letter-spacing: .5px; }}
  .lead {{ color:#8b98a5; margin: 0 0 28px; }}
  .card {{ background:#161b22; border:1px solid #232b36; border-radius:14px;
           padding:20px 22px 16px; margin-bottom:18px; }}
  .card header {{ display:flex; align-items:center; gap:12px; }}
  .index {{ font-size:13px; color:#5b9cf8; border:1px solid #2a3f5f;
            border-radius:6px; padding:2px 7px; }}
  h2 {{ font-size:19px; margin:0; font-weight:600; }}
  .desc {{ color:#9fb0c0; margin:10px 0 14px; }}
  audio {{ width:100%; height:42px; }}
  .meta {{ color:#6b7a89; font-size:13px; margin:10px 0 0; }}
  .note {{ border-left:3px solid #2f81f7; background:#121a24; padding:14px 18px;
           border-radius:6px; color:#a8b7c7; font-size:14px; margin-bottom:26px; }}
</style></head>
<body><main>
  <h1>{manifest.get('title','小鲸鱼语音试听')}</h1>
  <p class="lead">{manifest.get('lead','')}</p>
  <div class="note">{manifest.get('note','')}</div>
  {''.join(cards)}
</main></body></html>
"""
(target / "index.html").write_text(html, encoding="utf-8")
print(json.dumps({"页面": str(target / "index.html"), "音频数": len(rows)}, ensure_ascii=False))
