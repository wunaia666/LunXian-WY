"""沿用现有功能和接口，将控制台重构为小鲸鱼深海主题。"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BASE = Path(r"E:\sss\小鲸鱼记忆星图_20261101\monitor\dashboard.html")

SYMBOLS = """<svg class="whale-definitions" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><defs>
<linearGradient id="whale-body" x1="0" y1="0" x2=".85" y2="1"><stop stop-color="#b9f5ed"/><stop offset=".5" stop-color="#58c6d7"/><stop offset="1" stop-color="#23879c"/></linearGradient>
<linearGradient id="whale-belly" x2="0" y2="1"><stop stop-color="#effcf5"/><stop offset="1" stop-color="#a3e2df"/></linearGradient>
<symbol id="whale-mark" viewBox="0 0 200 150">
<path d="M144 78c8-19 25-27 43-20-1 17-9 28-23 31 17 2 25 11 24 25-22 4-36-6-45-20" fill="#3c9eaf" stroke="#9fe4df" stroke-width="2"/>
<path d="M21 73c4-30 29-47 63-43 35 4 57 23 69 52-13 30-45 48-83 43-32-4-53-25-49-52Z" fill="url(#whale-body)"/>
<path d="M23 89c30 13 77 17 124-3-13 27-43 43-77 39-24-3-41-15-47-36Z" fill="url(#whale-belly)"/>
<path d="M78 85c-1 18 8 32 29 35 2-17-7-29-23-36" fill="#328fa4" stroke="#9bdad9" stroke-width="1.5"/>
<path d="M66 32c-4-13-1-22 9-27 11 11 12 20 8 27" fill="#64c6d0"/>
<path d="M34 87q12 10 24 0" fill="none" stroke="#1b576e" stroke-width="3" stroke-linecap="round"/>
<circle cx="43" cy="69" r="5.5" fill="#123952"/><circle cx="44.5" cy="67" r="1.8" fill="#fff"/>
<ellipse cx="39" cy="80" rx="8" ry="3.5" fill="#e7a4a0" opacity=".7"/>
<path d="m104 50 3-5 3 5 6 1-5 4 1 6-5-3-5 3 1-6-5-4Z" fill="#d8fcf4"/>
<circle cx="102" cy="18" r="4" fill="#9ae8df"/><circle cx="115" cy="7" r="2.5" fill="#c9fff4"/>
</symbol>
<symbol id="icon-home" viewBox="0 0 24 24"><path d="m3 10 9-7 9 7v10H3Z M9 20v-7h6v7"/></symbol>
<symbol id="icon-memory" viewBox="0 0 24 24"><path d="m6 5 12 2 1 12-14-2Z M6 5l-1 12 13-10 M12 12l7 7"/><circle cx="6" cy="5" r="2"/><circle cx="18" cy="7" r="2"/><circle cx="5" cy="17" r="2"/><circle cx="19" cy="19" r="2"/></symbol>
<symbol id="icon-voice" viewBox="0 0 24 24"><path d="M4 10v4m4-8v12m4-15v18m4-15v12m4-8v4"/></symbol>
<symbol id="icon-computer" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4"/></symbol>
<symbol id="icon-chats" viewBox="0 0 24 24"><path d="M21 12a8 8 0 0 1-9 8H4l-1 2V12a9 9 0 0 1 18 0Z M7 10h10m-10 4h6"/></symbol>
<symbol id="icon-context" viewBox="0 0 24 24"><path d="m12 3 9 5-9 5-9-5Z M3 12l9 5 9-5M3 16l9 5 9-5"/></symbol>
<symbol id="icon-logs" viewBox="0 0 24 24"><path d="M5 3h14v18H5Z M8 7h8m-8 5h8m-8 5h5"/></symbol>
<symbol id="icon-arrow" viewBox="0 0 24 24"><path d="M5 12h14m-6-6 6 6-6 6"/></symbol>
<symbol id="icon-lock" viewBox="0 0 24 24"><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 4v3"/></symbol>
<symbol id="icon-refresh" viewBox="0 0 24 24"><path d="M20 8a8 8 0 1 0 0 8M20 3v5h-5"/></symbol>
</defs></svg>"""


def icon(name, class_name="ui-icon"):
    return f'<svg class="{class_name}" aria-hidden="true"><use href="#icon-{name}"></use></svg>'


def whale(class_name="whale-mark"):
    return f'<svg class="{class_name}" viewBox="0 0 200 150" aria-hidden="true"><use href="#whale-mark"></use></svg>'


def main():
    text = BASE.read_text(encoding="utf-8")
    text = text.replace(
        "<title>小鲸鱼 · 陪伴控制台</title>", "<title>小鲸鱼 · 深海陪伴舱</title>"
    )
    text = text.replace(
        "<body>", '<body data-design-version="deep-ocean-v2">' + SYMBOLS
    )
    text = text.replace('/memory-map.css"', '/memory-map.css?v=20261102-2"')
    text = text.replace('/memory-map.js"', '/memory-map.js?v=20261102-2"')
    start = text.index("<aside>")
    end = text.index('<main id="main">', start)
    nav = "".join(
        f'<button data-page="{page}"'
        + (' aria-current="page"' if page == "home" else "")
        + f'>{icon(page if page != "memory" else "memory")}<span class="nav-label">{label}</span><span class="nav-dot" aria-hidden="true"></span></button>'
        for page, label in (
            ("home", "我的小鲸鱼"),
            ("memory", "记忆星海"),
            ("voice", "声音工作台"),
            ("computer", "电脑画面"),
            ("chats", "聊天记录"),
            ("context", "本轮上下文"),
            ("logs", "运行日志"),
        )
    )
    sidebar = f"""<aside class="ocean-sidebar"><a class="brand" href="#home" aria-label="回到小鲸鱼首页"><span class="brand-mark">{whale()}</span><div><strong>小鲸鱼</strong><small>属于我们的陪伴空间</small></div></a>
<div class="nav-caption">陪伴观测舱</div><nav aria-label="控制台栏目">{nav}</nav>
<div class="whale-dock" aria-hidden="true">{whale("dock-whale")}<span class="dock-wave"></span><p>重要的事，<br>我会好好记住。</p></div>
<div class="aside-foot"><span class="local-indicator"></span>本机陪伴空间<br><span id="updated">等待核对状态</span></div></aside>"""
    text = text[:start] + sidebar + text[end:]
    text = re.sub(
        r"<header>.*?</header>",
        f"""<header class="ocean-header"><div><div class="eyebrow">小鲸鱼 <span>／</span> 陪伴观测舱</div><h1 id="page-title">我的小鲸鱼</h1><p class="muted small" id="page-subtitle">连接她，看看她记住的事，听听她的声音。</p></div><div class="header-actions"><span class="space-tag">{icon("lock")}本机空间</span><button id="pause" aria-pressed="false">暂停更新</button><button id="refresh" aria-label="刷新当前页面数据">{icon("refresh")}<span>刷新</span></button></div></header>""",
        text,
        count=1,
        flags=re.S,
    )
    start = text.index('<div class="stats">')
    end = text.index('<section id="page-home"', start)
    stats = '<div class="stats ocean-stats">'
    for name, identifier, content, sub_id, sub in (
        ("小鲸鱼连接", "account-status", "读取中", "account-sub", "等待核对真实连接"),
        ("记忆已入海", "memory-total", "—", "memory-sub", "保存在本机数据库"),
        ("陪伴服务", "robot-status", "读取中", "", "真实服务状态"),
        ("最近一次对话请求", "request-time", "尚无新请求", "", "以实际请求记录为准"),
    ):
        stats += (
            f'<div class="stat"><small>{name}</small><strong id="{identifier}">{content}</strong><div class="sub"'
            + (f' id="{sub_id}"' if sub_id else "")
            + f">{sub}</div></div>"
        )
    text = text[:start] + stats + "</div>" + text[end:]
    start = text.index('<div class="hero">')
    end = text.index(
        '<div class="panel"><div class="panel-head"><h2>连接与数据检查', start
    )
    home = f"""<div class="hero ocean-hero"><div class="hero-copy"><div class="hero-kicker"><span></span>给每一天，留一点温柔</div><h2>有一只小鲸鱼，<br>把你的故事<br><em>藏进了深海。</em></h2><p>聊天的回声、想记住的约定，还有偶尔响起的声音。<br class="desktop-break">在这里，慢慢积攒属于我们的日常。</p><div class="hero-buttons"><button class="primary login-trigger">登录小鲸鱼</button><button class="check-trigger">检查本地数据</button></div><p class="small" id="start-note">从这里启动小鲸鱼专用账号，扫码或验证由你完成。</p></div>
<figure class="hero-art"><div class="portal-grid" aria-hidden="true"></div><div class="portal-ring ring-one" aria-hidden="true"></div><div class="portal-ring ring-two" aria-hidden="true"></div><div class="hero-orbit-label" aria-hidden="true">陪伴有迹 · 记忆有光</div><div class="character-window"><img src="/assets/character.jpg" width="1024" height="1024" alt="蓝发小鲸鱼向你伸出手"></div><span class="ocean-bubble bubble-one" aria-hidden="true"></span><span class="ocean-bubble bubble-two" aria-hidden="true"></span><span class="ocean-bubble bubble-three" aria-hidden="true"></span><div class="hero-whale">{whale()}</div><figcaption><span>小鲸鱼的深海小屋</span><strong>慢慢来，我一直在。</strong></figcaption></figure>
<div class="hero-depth" aria-hidden="true"><span>陪伴</span><span>记忆</span><span>回声</span></div></div>
<div class="ocean-shortcuts"><button data-open-page="memory">{icon("memory")}<span><strong>潜入记忆星海</strong><small>看看我们的故事如何相连</small></span>{icon("arrow")}</button><button data-open-page="voice">{icon("voice")}<span><strong>听一段她的声音</strong><small>平时文字，需要时偶尔生成</small></span>{icon("arrow")}</button><button data-open-page="computer">{icon("computer")}<span><strong>看看她眼中的电脑</strong><small>真实画面与最近操作记录</small></span>{icon("arrow")}</button></div>"""
    text = text[:start] + home + text[end:]
    start = text.index('<div class="panel">', text.index('<section id="page-memory"'))
    end = text.index('<div id="memory-list-view"', start)
    memory = f"""<div class="memory-overview"><div class="memory-heading"><div class="hero-kicker">{whale("tiny-whale")}每一段记忆，都有回声</div><h2>我们的记忆，<em>正在相连。</em></h2><p>沿着一条光路，找回那些被认真记住的日常。</p></div><div class="memory-tally"><div><strong id="star-count-all">—</strong><span>真实记忆</span></div><div><strong id="star-count-links">—</strong><span>真实关联</span></div><div><strong id="star-count-pinned">—</strong><span>锁定珍藏</span></div></div></div>
<div class="memory-filterbar"><label class="memory-search-label"><span class="sr-only">关键词、主题或来源</span>{icon("memory")}<input id="memory-search" type="search" placeholder="搜索一段记忆、一个主题…"></label><label><span class="sr-only">记忆分类</span><select id="memory-kind"><option value="">全部星域</option><option value="preference">偏好与个人事实</option><option value="event">共同经历</option><option value="plan">约定与计划</option><option value="browse">浏览记录</option></select></label><label><span class="sr-only">记忆范围</span><select id="memory-state"><option value="all">全部记忆</option><option value="active">当前有效</option><option value="locked">锁定珍藏</option><option value="archived">过期历史</option></select></label><div class="memory-view-switch" role="group" aria-label="记忆查看方式"><button id="memory-mode-map" type="button" aria-pressed="true">星图</button><button id="memory-mode-list" type="button" aria-pressed="false">列表</button></div><span id="memory-count" class="sr-only">读取中</span></div>
<div id="memory-map-view" class="memory-star-layout"><div class="memory-star-panel"><div class="memory-star-head"><div><div class="map-overline"><span class="signal-dot"></span>小鲸鱼的记忆星海</div><p id="star-summary" role="status" aria-live="polite">正在读取真实记忆…</p></div><div class="star-head-actions"><button id="star-labels" type="button" aria-pressed="false">展开标签</button><button id="star-motion" type="button" aria-pressed="true">动效已开</button><button id="star-fullscreen" type="button">沉浸星海</button></div></div>
<div class="star-canvas"><div class="map-coordinate coordinate-top" aria-hidden="true">鲸语航线 · 记忆回响</div><svg id="memory-star-svg" viewBox="0 0 1200 760" tabindex="0" role="group" aria-label="真实记忆关系星图，连线连接所属分类和相同主题，可用方向键移动，也可切换列表"></svg><div id="star-empty" class="star-empty" hidden>{whale("empty-whale")}<strong>这片星海还很安静</strong><span>没有符合条件的记忆，试试其他关键词或查看范围。</span></div>
<div class="star-tools" role="group" aria-label="星图缩放与移动"><button id="star-zoom-in" type="button" aria-label="放大星图">＋</button><button id="star-zoom-out" type="button" aria-label="缩小星图">－</button><button id="star-reset" type="button">归航</button><span class="star-tool-separator"></span><button id="star-left" type="button" aria-label="向左移动星图">←</button><button id="star-right" type="button" aria-label="向右移动星图">→</button><button id="star-up" type="button" aria-label="向上移动星图">↑</button><button id="star-down" type="button" aria-label="向下移动星图">↓</button></div><div class="map-coordinate coordinate-bottom" aria-hidden="true">点亮一颗记忆 · 跟随它的航线</div></div>
<div class="star-legend" aria-label="星图图例"><span><i style="--dot:var(--memory-preference)"></i>偏好</span><span><i style="--dot:var(--memory-event)"></i>经历</span><span><i style="--dot:var(--memory-plan)"></i>约定</span><span><i style="--dot:var(--memory-browse)"></i>浏览</span><span><i class="star-ring"></i>锁定</span><span class="legend-line">连线即真实关联</span></div><p class="star-help">拖动画布或使用移动按钮；聚焦画布后可用方向键，制表键可选择记忆。点选节点会点亮它到小鲸鱼的路径。</p></div><div id="star-detail" class="panel star-inspector" aria-live="polite"></div></div>"""
    text = text[:start] + memory + text[end:]
    text = text.replace(
        "memory:['记忆星图','有来源、有修订，也能查到更早的记录。']",
        "memory:['记忆星海','每一段记忆，都能循着回声找到来处。']",
    )
    text = text.replace(
        "</body>",
        """<script>
document.querySelectorAll('[data-open-page]').forEach(button => {
  button.addEventListener('click', () => document.querySelector('nav button[data-page="'+button.dataset.openPage+'"]').click());
});
document.querySelector('.brand').addEventListener('click', event => {
  event.preventDefault();document.querySelector('nav button[data-page="home"]').click();
});
</script></body>""",
    )
    target = ROOT / "monitor/dashboard.html"
    target.write_text(text, encoding="utf-8")
    print("深海主题页面已生成，原有七个栏目及功能入口已保留。")


if __name__ == "__main__":
    main()
