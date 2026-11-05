"""把现有可编辑系谱图按横向办公纸重排，保留用户改过的文字和原有关系。"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
from PIL import ImageFont
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Pt

NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
W, H = 297 * 72 / 25.4, 210 * 72 / 25.4
LEFT, RIGHT, TOP = 71, 25, 66
GAP, ROW = 11, 24
BODY, NAME, ALIAS = 11, 15, 11.5
CELL_WIDTHS = (148, 124, 176, 108, 206, 240, 290, 350, 430, 580, 700)
COLOR = RGBColor.from_string('111827')
GEN = re.compile(r'^第[一二三四五六七八九十百]+代$')


def compact(text):
    return re.sub(r'\s+', '', text)


@lru_cache(maxsize=None)
def font(size, bold):
    return ImageFont.truetype('simhei.ttf' if bold else 'simsun.ttc', round(size * 8))


@lru_cache(maxsize=65536)
def width(text, size, bold):
    return font(size, bold).getlength(text) / 8 * 1.105


def wrap(text, size, bold, available):
    parts = re.findall(r'\d{4}(?:年(?:\d{1,2}月(?:\d{1,2}日)?)?)?|[a-zA-Z]+|.', text)
    tokens = []
    for part in parts:
        if part in '，。；：、）】》！？' and tokens:
            tokens[-1] += part
        else:
            tokens.append(part)
    result, line = [], ''
    for token in tokens:
        if line and width(line + token, size, bold) > available:
            result.append(line)
            line = ''
        line += token
    if line:
        result.append(line)
    assert compact(''.join(result)) == compact(text)
    return result


def read_slide(package, number):
    slide = etree.fromstring(package.read(f'ppt/slides/slide{number}.xml'))
    people, notes, titles = {}, [], []
    for shape in slide.xpath('./p:cSld/p:spTree/p:sp', namespaces=NS):
        tag = shape.find('p:nvSpPr/p:cNvPr', NS).get('descr', '')
        paragraphs = []
        for paragraph in shape.xpath('./p:txBody/a:p', namespaces=NS):
            text = ''.join(paragraph.xpath('./a:r/a:t/text()|./a:fld/a:t/text()', namespaces=NS))
            align = paragraph.find('a:pPr', NS)
            if text:
                paragraphs.append((align.get('algn') if align is not None else None, text))
        text = ''.join(t for _, t in paragraphs)
        if not text:
            continue
        if tag.startswith('原文记录：'):
            rid = tag[5:]
            assert rid not in people
            index = next((i for i, (a, _) in enumerate(paragraphs) if a != 'ctr'), len(paragraphs))
            people[rid] = (''.join(t for _, t in paragraphs[:index]), tuple(t for _, t in paragraphs[index:]))
            assert people[rid][0], ('人物姓名行未识别', number, rid)
        elif '系谱图' in text and not titles:
            titles.append(re.sub(r'（本户第\d+[／/]\d+页）$', '', text))
        elif not (GEN.fullmatch(text) or text.isdigit() or text in ('继', '嗣', '出养')):
            notes.append(text)
    assert len(titles) == 1
    return people, notes, titles[0]


def paragraph(text, size, bold=False, align='left', leading=None):
    return {'runs': [(text, size, bold)], 'align': align, 'leading': leading or size * 1.29}


def profile(heading, old_body, role, cell):
    # 小名保持同一行；未具名说明较长时仍可分行，正文一律重新折行。
    match = re.fullmatch(r'(.+?)([（(][^）)]+[）)])', heading)
    room = cell - 8
    if match and match[2] not in ('（名未载）', '（未具名）'):
        if width(match[1], NAME, True) + width(match[2], ALIAS, False) > room:
            return None
        title = [{'runs': [(match[1], NAME, True), (match[2], ALIAS, False)], 'align': 'center', 'leading': 20}]
    else:
        title = [paragraph(s, NAME, True, 'center', 20) for s in wrap(heading, NAME, True, room)]
    role_line = bool(old_body and role and compact(old_body[0]) == compact(role))
    body = ([old_body[0]] if role_line else []) + [''.join(old_body[role_line:])]
    for t in body:
        title.extend(paragraph(s, BODY, leading=14.5) for s in wrap(t, BODY, False, room))
    assert compact(''.join(t for p in title for t, _, _ in p['runs'])) == compact(heading + ''.join(old_body))
    return title, sum(p['leading'] for p in title) + 4


class SourcePage:
    def __init__(self, page, people, notes, title, records):
        self.page, self.people, self.notes, self.title, self.records = page, people, notes, title, records
        self.members = set(page['members'])
        assert set(people) == set(page['record_ids'])
        self.partners = defaultdict(list)
        self.kids = defaultdict(list)
        self.parents, self.edges = {}, {}
        self.positions = {r: b['x'] for r, b in page['boxes'].items()}
        for e in page['connections']:
            p, c = e['parent'], e['child']
            assert c not in self.parents
            self.kids[p].append(c)
            self.parents[c] = p
            self.edges[p, c] = e
        for pair in page['marriages']:
            self.partners[pair['person']].append(pair['spouse'])
        for p in self.kids:
            self.kids[p].sort(key=lambda r: self.positions[r])
        self.roots = sorted(self.members - self.parents.keys(), key=lambda r: self.positions[r])
        generation = [(a['y'], a['text']) for a in page['atoms'] if not a.get('person_record') and GEN.fullmatch(a.get('text', ''))]
        self.gens = {r: min(generation, key=lambda g: abs(g[0] - page['boxes'][r]['y'])) for r in self.members}
        self.profiles = {}
        for cell in CELL_WIDTHS:
            self.profiles[cell] = {r: profile(*v, records[r].get('role', ''), cell) for r, v in people.items()}
        self.note_lines = [s for t in notes for s in wrap(t, 10.5, False, W-2*RIGHT-9)]

    def order(self, r):
        yield r
        for child in self.kids[r]:
            yield from self.order(child)

    def dimensions(self, members, cell):
        info = self.profiles[cell]
        units = {r: [r, *self.partners[r]] for r in members}
        if any(info[t] is None for group in units.values() for t in group):
            return None
        heights = {r: sum(info[t][1] for t in group) + 7*(len(group)-1) for r, group in units.items()}
        def combine(groups):
            xs, contours = {}, {}
            for coords, bounds in groups:
                shift = max((contours[g][1]+GAP-l for g,(l,_) in bounds.items() if g in contours), default=0)
                xs.update({r: x+shift for r,x in coords.items()})
                for g,(l,h) in bounds.items():
                    lo, hi = contours.get(g, (float('inf'), -float('inf')))
                    contours[g] = (min(lo,l+shift), max(hi,h+shift))
            return xs, contours
        def tree(r):
            kids = [c for c in self.kids[r] if c in members]
            xs, contours = combine(tree(c) for c in kids)
            x = (xs[kids[0]]+xs[kids[-1]])/2 if kids else cell/2
            xs[r] = x
            contours[self.gens[r]] = (x-cell/2, x+cell/2)
            return xs, contours
        roots = sorted((r for r in members if self.parents.get(r) not in members), key=lambda r: self.positions[r])
        xs, contours = combine(tree(r) for r in roots)
        l, h = min(v[0] for v in contours.values()), max(v[1] for v in contours.values())
        extent = h-l
        if extent > W-LEFT-RIGHT:
            return None
        ys, y = {}, TOP
        for gen in sorted(contours):
            ys[gen] = y
            y += max(heights[r] for r in members if self.gens[r] == gen)+ROW
        x_offset = LEFT+(W-LEFT-RIGHT-extent)/2-l
        return {r: x+x_offset for r,x in xs.items()}, ys, units, heights, y-ROW

    def fit(self, members, notes):
        floor = H-37-(13.5*len(self.note_lines)+12 if notes and self.note_lines else 0)
        for cell in CELL_WIDTHS:
            layout = self.dimensions(members, cell)
            if layout and layout[-1] <= floor:
                return cell, layout
        return None

    def plan(self):
        full = self.fit(self.members, True)
        if full:
            return [(self.members, full)]
        # 按原图左右顺序遍历房支；跨页时把父母作为接续，确保原线至少完整出现一次。
        pages, group, fit = [], set(), None
        for root in self.roots:
            for r in self.order(root):
                unit = {r}
                if r in self.parents:
                    unit.add(self.parents[r])
                layout = self.fit(group | unit, not pages)
                if layout:
                    group |= unit
                    fit = layout
                else:
                    assert group and fit, ('单支超过页面容量', self.page['global_page'], r)
                    pages.append((group, fit))
                    group = unit
                    fit = self.fit(group, False)
                    assert fit, ('亲子最小单元超过页面容量', self.page['global_page'], r)
        pages.append((group, fit))
        assert set().union(*(members for members, _ in pages)) == self.members
        assert all(any(p in m and c in m for m, _ in pages) for p,c in self.edges)
        return pages


def text(slide, x, y, w, h, paragraphs, rid=None):
    assert x >= 0 and y >= 0 and x+w <= W+.01 and y+h <= H+.01
    shape = slide.shapes.add_textbox(Pt(x), Pt(y), Pt(w), Pt(h))
    shape.name = '人物信息' if rid else '世系标注'
    shape._element.nvSpPr.cNvPr.set('descr', '原文记录：'+rid if rid else '世系图标注')
    f = shape.text_frame
    f.margin_left = f.margin_right = f.margin_top = f.margin_bottom = 0
    f.word_wrap = False
    f.vertical_anchor = MSO_ANCHOR.TOP
    for i, line in enumerate(paragraphs):
        p = f.paragraphs[0] if i == 0 else f.add_paragraph()
        p.alignment = {'left': PP_ALIGN.LEFT, 'center': PP_ALIGN.CENTER, 'right': PP_ALIGN.RIGHT}[line['align']]
        p.space_before = p.space_after = Pt(0)
        p.line_spacing = Pt(line['leading'])
        for content, size, bold in line['runs']:
            run = p.add_run()
            run.text = content
            run.font.name = '黑体' if bold else '宋体'
            run.font.size = Pt(size)
            run.font.bold = bold
            run.font.color.rgb = COLOR
            east = OxmlElement('a:ea')
            east.set('typeface', run.font.name)
            run._r.get_or_add_rPr().append(east)


def line(slide, x, y, a, b):
    if (x, y) == (a, b):
        return
    shape = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Pt(x), Pt(y), Pt(a), Pt(b))
    shape.name = '亲属关系连线'
    shape.line.width = Pt(.8)
    shape.line.color.rgb = COLOR


def new_deck():
    deck = Presentation()
    deck.slide_width, deck.slide_height = Pt(W), Pt(H)
    deck.core_properties.author = ''
    deck.core_properties.last_modified_by = ''
    deck.core_properties.title = '村志系谱图·横向办公纸大字版'
    return deck


def render(deck, source, group, fit, notes, global_page, house_page, house_total, old_part, old_total):
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    cell, (xs, ys, units, heights, bottom) = fit
    title = [paragraph(s, 21, True, 'center', 25) for s in wrap(source.title, 21, True, W-2*RIGHT-10)]
    assert len(title) <= 2
    text(slide, RIGHT, 12, W-2*RIGHT, len(title)*25+3, title)
    for gen,y in ys.items():
        text(slide, 22, y+3, 44, 17, [paragraph(gen[1], 10.5, True, leading=14)])
    for p in sorted(group, key=lambda r: (source.gens[r], xs[r])):
        x, y = xs[p], ys[source.gens[p]]
        children = [c for c in source.kids[p] if c in group]
        if not children:
            continue
        child_y = ys[source.gens[children[0]]]
        joint = child_y-13
        assert joint > y+heights[p]+2
        centers = [xs[c] for c in children]
        line(slide,x,y+heights[p]+2,x,joint)
        line(slide,min([x]+centers),joint,max([x]+centers),joint)
        for c in children:
            assert ys[source.gens[c]] == child_y
            line(slide,xs[c],joint,xs[c],child_y-2)
            edge = source.edges[p,c]
            kind = edge['kind']
            label = '' if edge['pending'] else '继' if '继亲' in kind else '嗣' if '承嗣' in kind or '收养' in kind else '出养' if '出养' in kind else ''
            if label:
                text(slide,xs[c]+4,joint+1,30,14,[paragraph(label,10,leading=12)])
    for r in sorted(group, key=lambda r: (source.gens[r], xs[r])):
        x, y = xs[r]-cell/2+4, ys[source.gens[r]]
        for person in units[r]:
            paragraphs, height = source.profiles[cell][person]
            text(slide,x,y,cell-8,height,paragraphs,person)
            y += height+7
    if notes and source.note_lines:
        text(slide, RIGHT, H-38-13.5*len(source.note_lines),W-2*RIGHT,13.5*len(source.note_lines)+3,
             [paragraph(t,10.5,leading=13.5) for t in source.note_lines])
    label = f'本户第{house_page}／{house_total}页　原图第{source.page["global_page"]}页'
    if old_total > 1:
        label += f'（{old_part}／{old_total}）'
    label += f'　全册第{global_page}页'
    text(slide, RIGHT, H-29, W-2*RIGHT, 17,[paragraph(label,10.5,False,'right',14)])


def main():
    parser = argparse.ArgumentParser(description='按可编辑原图重排横向办公纸大字版')
    for key in ('layout', 'source', 'out'):
        parser.add_argument('--'+key, required=True, type=Path)
    args = parser.parse_args()
    data = json.loads(args.layout.read_text(encoding='utf-8'))
    plans = defaultdict(list)
    with ZipFile(args.source) as package:
        for page in data['pages']:
            source = SourcePage(page, *read_slide(package, page['global_page']), data['original_records'])
            parts = source.plan()
            plans[page['house_id']].extend((source, m, fit, k, len(parts)) for k,(m,fit) in enumerate(parts,1))
    deck = new_deck()
    args.out.mkdir(parents=True, exist_ok=True)
    folder = args.out/'逐户可编辑文件'
    folder.mkdir(exist_ok=True)
    mapping = []
    global_page = 0
    for house in data['households']:
        h = house['户号']
        independent = new_deck()
        for n,(source, group, fit, part, count) in enumerate(plans[h],1):
            global_page += 1
            for output in (deck, independent):
                render(output, source, group, fit, part == 1, global_page, n, len(plans[h]), part, count)
            mapping.append([source.page['global_page'],global_page,h,house['家族'],n,len(plans[h])])
        name = re.sub(r'[<>:"/\\|?*]', '', house['家族'])
        independent.save(folder/(h+'_'+name+'.pptx'))
    deck.save(args.out/'村志系谱图_横向办公纸大字版_可编辑.pptx')
    with (args.out/'旧版与大字版页码对照.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['原图页','大字版全册页','户号','家族','大字版户内页','该户总页数'])
        writer.writerows(mapping)
    print('大字版页数',global_page,'户数',len(plans),'保持单页的户数',sum(len(v)==1 for v in plans.values()))


if __name__ == '__main__':
    main()
