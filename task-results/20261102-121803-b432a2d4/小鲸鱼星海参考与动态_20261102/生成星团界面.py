"""接入参考作品启发的三维星团及小鲸鱼动态素材，保留现有数据接口。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main():
    monitor = ROOT / "monitor"
    path = monitor / "dashboard.html"
    text = path.read_text(encoding="utf-8")
    if 'data-design-version="constellation-v3"' not in text:
        text = text.replace(
            'data-design-version="deep-ocean-v2"',
            'data-design-version="constellation-v3"',
        )
        text = text.replace("v=20261102-2", "v=20261102-3")
        text = text.replace(
            '<div class="character-window"><img src="/assets/character.jpg" width="1024" height="1024" alt="蓝发小鲸鱼向你伸出手"></div>',
            '<div class="character-window animated-character"><div class="whale-float"><div class="whale-sprite" role="img" aria-label="会眨眼的小鲸鱼向你招手"></div></div></div>',
        )
        start = text.index('<div class="star-canvas">')
        end = text.index('<svg id="memory-star-svg"', start)
        text = (
            text[:start]
            + text[start:end].replace(
                '<div class="star-canvas">',
                '<div class="star-canvas"><canvas id="memory-space-canvas" aria-hidden="true"></canvas>',
            )
            + text[end:]
        )
        text = text.replace(
            "真实记忆关系星图，连线连接所属分类和相同主题，可用方向键移动，也可切换列表",
            "真实记忆三维星团，拖动旋转，方向按钮及键盘可调整视角，也可切换列表",
        )
        text = text.replace(
            'id="star-motion" type="button" aria-pressed="true">动效已开',
            'id="star-motion" type="button" aria-pressed="true">自动巡游',
        )
        text = text.replace("星图图例", "星团图例")
        start = text.index('<div class="star-legend"')
        end = text.index('</div><p class="star-help">', start)
        text = (
            text[:start]
            + '<div class="star-legend" aria-label="星团图例"><span>亮点：真实记忆</span><span><i class="star-ring"></i>锁定珍藏</span><span class="legend-line">光线：主题或关键词关联</span><span>细碎星尘：背景装饰</span>'
            + text[end:]
        )
        start = text.index('<p class="star-help">')
        end = text.index("</p>", start)
        text = (
            text[:start]
            + '<p class="star-help">拖动旋转三维星海，滚轮或按钮缩放；按住上档键可拖动平移。放大会显示较小星团的名称，节点也可用制表键选择。'
            + text[end:]
        )
        text = text.replace("鲸语航线 · 记忆回响", "三维记忆星团 · 循着回声探索")
        text = text.replace(
            "点亮一颗记忆 · 跟随它的航线", "旋转视角 · 看见记忆之间的联系"
        )
        text = text.replace("<h3>连线与记忆整理</h3>", "<h3>星团依据与记忆整理</h3>")
        text = text.replace("<span>真实关联</span>", "<span>星团关联</span>")
        text = text.replace(
            "<span>锁定珍藏</span></div></div></div>",
            "<span>锁定珍藏</span></div></div></div>",
        )
        gallery = """<section id="whale-gallery" class="whale-gallery" aria-label="小鲸鱼新图与动态展示"><div class="section-label"><div><div class="hero-kicker">把小鲸鱼，带进日常</div><h2>今天的小鲸鱼，也会动了。</h2></div><button id="whale-animations" type="button" aria-pressed="true">暂停角色动效</button></div><div class="whale-gallery-grid"><article class="whale-art-card"><div class="whale-art-stage"><div class="whale-float"><div class="whale-sprite" role="img" aria-label="小鲸鱼四帧眨眼招手动画"></div></div></div><h3>招招手，眨眨眼</h3><p>四帧角色图，配合轻轻漂浮的动作。</p><a href="/assets/whale-blink.png" download="小鲸鱼_四帧眨眼.png">保存透明四帧图</a></article><article class="whale-art-card"><div class="whale-art-stage hug-stage"><img class="whale-breathe" src="/assets/whale-hug.png" width="1254" height="1254" loading="lazy" alt="小鲸鱼抱着浅青色鲸鱼抱枕"></div><h3>抱着鲸鲸，陪你一会儿</h3><p>透明立绘，搭配舒缓的呼吸动效。</p><a href="/assets/whale-hug.png" download="小鲸鱼_抱鲸立绘.png">保存透明立绘</a></article><article class="whale-art-card starry-art-card"><div class="whale-art-stage"><img class="whale-scene" src="/assets/whale-starry.png" width="1672" height="941" loading="lazy" alt="小鲸鱼骑着发光鲸鱼，伸手触碰星光"></div><h3>带着记忆，游进星海</h3><p>全新场景插画，星海随画面轻轻移动。</p><a href="/assets/whale-starry.png" download="小鲸鱼_星海场景.png">保存场景原图</a></article></div><p class="muted small">角色动效为逐帧眨眼及网页动画；可随时暂停，并遵循系统减少动态效果设置。</p></section>"""
        text = text.replace(
            '<div class="panel"><div class="panel-head"><h2>连接与数据检查',
            gallery + '<div class="panel"><div class="panel-head"><h2>连接与数据检查',
            1,
        )
        text = text.replace(
            "</body>",
            """<script>
const characterMotion=matchMedia('(prefers-reduced-motion: reduce)');
function setCharacterMotion(paused){document.body.classList.toggle('whale-visual-paused',paused);const button=document.getElementById('whale-animations');button.textContent=paused?'播放角色动效':'暂停角色动效';button.setAttribute('aria-pressed',String(!paused))}
document.getElementById('whale-animations').onclick=()=>setCharacterMotion(!document.body.classList.contains('whale-visual-paused'));
characterMotion.addEventListener('change',()=>setCharacterMotion(characterMotion.matches));setCharacterMotion(characterMotion.matches);
</script></body>""",
        )
    path.write_text(text, encoding="utf-8")
    path = monitor / "memory-map.css"
    styles = path.read_text(encoding="utf-8")
    extra = (ROOT / "星团与角色样式.css").read_text(encoding="utf-8")
    if "三维星团主视图" not in styles:
        path.write_text(styles + "\n" + extra, encoding="utf-8")
    path = monitor / "monitor.py"
    text = path.read_text(encoding="utf-8").replace(
        'allowed = {"character.jpg", "happy.png", "sleepy.png"}',
        'allowed = {"character.jpg", "happy.png", "sleepy.png", "whale-blink.png", "whale-hug.png", "whale-starry.png"}',
    )
    path.write_text(text, encoding="utf-8")
    print("三维星团页面、三组新素材入口和角色动效已接入独立副本。")


if __name__ == "__main__":
    main()
