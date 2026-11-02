"""将真实记忆星图接入现有单页监控，保留列表、检索、来源、锁定和备份入口。"""

from pathlib import Path


def main():
    path = Path(__file__).resolve().parent / "monitor/dashboard.html"
    source = path.read_text(encoding="utf-8")
    start = source.index('<section id="page-memory"')
    end = source.index('<section id="page-voice"', start)
    memory = """<section id="page-memory" class="page" hidden aria-label="记忆星图">
<div class="panel"><div class="panel-head"><div><h2 style="margin-bottom:4px">把记住的事，连成一片星空</h2><p class="muted small" style="margin:0">来自本机记忆数据库，点击节点查看内容、来源与保存期限。</p></div><span id="memory-count" class="pill">读取中</span></div>
<div class="toolbar"><label class="grow">关键词、主题或来源<input id="memory-search" type="search" placeholder="例如：称呼、声音、共同经历"></label><label>分类<select id="memory-kind"><option value="">全部分类</option><option value="preference">偏好与个人事实</option><option value="event">共同经历</option><option value="plan">约定与计划</option><option value="browse">浏览记录</option></select></label><label>范围<select id="memory-state"><option value="all">全部记录</option><option value="active">当前有效</option><option value="locked">已锁定</option><option value="archived">过期历史</option></select></label></div>
<div class="memory-view-switch" role="group" aria-label="记忆查看方式"><button id="memory-mode-map" type="button" aria-pressed="true">记忆星图</button><button id="memory-mode-list" type="button" aria-pressed="false">记忆列表</button></div></div>
<div id="memory-map-view" class="memory-star-layout"><div class="memory-star-panel"><div class="memory-star-head"><div><h2>我们的记忆星图</h2><p id="star-summary" class="muted small" role="status" aria-live="polite">正在读取真实记忆…</p></div><span class="pill">本机保存</span></div>
<div class="star-tools" role="group" aria-label="星图缩放与移动"><button id="star-zoom-in" type="button" aria-label="放大星图">＋</button><button id="star-zoom-out" type="button" aria-label="缩小星图">－</button><button id="star-reset" type="button">重置视图</button><span class="star-tool-separator"></span><button id="star-left" type="button" aria-label="向左移动星图">左</button><button id="star-right" type="button" aria-label="向右移动星图">右</button><button id="star-up" type="button" aria-label="向上移动星图">上</button><button id="star-down" type="button" aria-label="向下移动星图">下</button></div>
<div class="star-canvas"><svg id="memory-star-svg" viewBox="0 0 1000 680" tabindex="0" role="group" aria-label="真实记忆关系星图，可用方向键移动，或切换记忆列表查看全部内容"></svg><div id="star-empty" class="star-empty" hidden>没有符合条件的记忆。可以清空关键词，或切换查看范围。</div></div>
<div class="star-legend" aria-label="星图图例"><span><i style="--dot:#8de7ad"></i>偏好与个人事实</span><span><i style="--dot:#8ec9de"></i>共同经历</span><span><i style="--dot:#f0d09a"></i>约定与计划</span><span><i style="--dot:#b7bfd0"></i>浏览记录</span><span><i class="star-ring"></i>已锁定</span></div>
<p class="star-help">拖动画布移动；聚焦画布后用方向键或滚轮操作，也可使用上方按钮。节点可用制表键选择。</p></div><div id="star-detail" class="panel star-inspector" aria-live="polite"></div></div>
<div id="memory-list-view" class="panel" hidden><div id="memory-list"></div><div class="pagination"><button id="memory-prev">上一页</button><span id="memory-page" class="muted small"></span><button id="memory-next">下一页</button></div></div><div id="memory-detail" class="panel" hidden></div>
<div class="two"><div class="panel"><div class="panel-head"><h2>记忆数据库</h2><span class="pill" id="database-integrity">读取中</span></div><div id="database-info"></div><div class="callout">个人事实和稳定偏好默认长期保存。锁定后不再到期，更正仍保留旧版本。浏览记录有有效期，过期历史仍可检索。每次对话只选取相关内容进入上下文。</div><button id="backup-memory" style="width:100%">备份记忆数据库</button><p id="backup-result" class="muted small" style="margin:12px 0 0"></p></div><div class="panel"><h3>连线与记忆整理</h3><p id="star-relation-note" class="memory-map-note">实线连接分类，虚线连接相同主题。</p><hr style="border:0;border-top:1px solid var(--line);margin:20px 0"><div id="memory-worker" class="muted small"></div><p class="muted small star-retention">记忆星图只读展示。查看节点不会让旧记忆过期、删除或重新整理。</p></div></div></section>
"""
    source = source[:start] + memory + source[end:]
    source = source.replace(
        "</style></head>",
        '</style><link rel="stylesheet" href="/memory-map.css"></head>',
        1,
    )
    source = source.replace(
        "<script>", '<script src="/memory-map.js"></script><script>', 1
    )
    source = source.replace(">记忆档案</button>", ">记忆星图</button>")
    source = source.replace("memory:['记忆档案'", "memory:['记忆星图'")
    old = "const d=await api('/api/memories?'+q);await database();"
    if source.count(old) != 1:
        raise RuntimeError("记忆刷新入口不唯一，未覆盖页面")
    source = source.replace(
        old,
        "const d=await api('/api/memories?'+q);await Promise.all([database(),window.whaleMemoryMap.update(q)]);",
    )
    source = source.replace("设为日常语音参数", "设为按需生成时的声音")
    source = source.replace(
        "日常合成已选用第十条声音的模型与参数；下方可继续试听新文字。",
        "需要语音时使用你认可的第十条声音。平时以文字为主，可在这里按需生成。",
    )
    source = source.replace("已用于日常语音", "已用于按需语音")
    source = source.replace(
        "日常合成沿用同一训练配对、参考对白和参数",
        "按需合成沿用同一训练配对、参考对白和参数",
    )
    path.write_text(source, encoding="utf-8")
    print("记忆星图、列表切换与按需语音说明已接入现有监控页面。")


if __name__ == "__main__":
    main()
