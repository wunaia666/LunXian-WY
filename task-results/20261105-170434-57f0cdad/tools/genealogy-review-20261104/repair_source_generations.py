"""依主稿代次修正未接父母的人物，并重排其所在房支。"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile

from lxml import etree

import reflow_genealogy_a4 as native
from build_fulltext_genealogy import wrap
from build_household_atlas import Household


NS = native.NS
TAG = '{' + NS['a'] + '}'


def shape_record(shape):
    return shape.find('p:nvSpPr/p:cNvPr', NS).get('descr', '').removeprefix('原文记录：')


def shape_text(shape):
    return ''.join(etree.XPath('.//a:t/text()', namespaces=NS)(shape))


def compact(text):
    return re.sub(r'\s+', '', text)


def extract_profile(shape, cell):
    source = shape.findall('p:txBody/a:p', NS)
    headings, body = [], []
    for paragraph in source:
        text = ''.join(paragraph.xpath('./a:r/a:t/text()', namespaces=NS))
        properties = paragraph.find('a:pPr', NS)
        if properties is not None and properties.get('algn') == 'ctr' and not body:
            runs = []
            for run in paragraph.findall('a:r', NS):
                label = run.findtext('a:t', namespaces=NS)
                if label:
                    bold = run.find('a:rPr', NS).get('b') == '1'
                    runs.append((label, 28 if bold else 19, bold))
            headings.append({'text': text, 'size': 28, 'bold': True, 'align': 'center', 'leading': 38, 'runs': runs})
        elif text:
            body.append(text)
    # 原文称谓单列，叙述按新的人物框重新折行。
    separated = body[:1] + [''.join(body[1:])] if body else []
    paragraphs = headings + [{'text': line, 'size': 19, 'bold': False, 'align': 'left', 'leading': 28}
                             for value in separated for line in wrap(value, cell-10, 19)]
    assert compact(''.join(p['text'] for p in paragraphs)) == compact(shape_text(shape))
    return {'paragraphs': paragraphs, 'height': sum(p['leading'] for p in paragraphs)+12, 'source_paras': []}


def serialize(decks, pages, original_xml, width, height, target):
    native.W, native.H = width, height
    deck = native.new_deck()
    for item in pages:
        if item.get('unchanged_xml'):
            slide = deck.slides.add_slide(deck.slide_layouts[6])
            element = copy.deepcopy(original_xml[item['old_page']].find('p:cSld/p:spTree', NS))
            old = slide._element.find('p:cSld/p:spTree', NS)
            old.getparent().replace(old, element)
            for shape in slide._element.xpath('.//p:sp'):
                body = shape.find('p:txBody', NS)
                if body is not None and shape_text(shape).isdigit():
                    nodes = shape.xpath('.//a:t')
                    nodes[0].text = str(item['global_page'])
        else:
            slide = deck.slides.add_slide(deck.slide_layouts[6])
            for atom in item['atoms']:
                if atom['kind'] == 'line':
                    native.line(slide, atom['x1'], atom['y1'], atom['x2'], atom['y2'])
                    continue
                values = atom.get('paragraphs', [dict(atom, leading=atom['size']*1.3)])
                paragraphs = []
                for p in values:
                    runs = p.get('runs', [(p['text'], p['size'], p['bold'])])
                    paragraphs.append({'runs': runs, 'align': p.get('align', atom['align']), 'leading': p['leading']})
                native.text(slide, atom['x'], atom['y'], atom['w'], atom['h']+2, paragraphs, atom.get('person_record'))
        slide.notes_slide.notes_text_frame.text = ''
    deck.save(target)
    return deck


class CorrectedHouse(Household):
    def __init__(self, house, records, assigned, profiles, notes, contexts, generation_updates, cell):
        super().__init__(house, records, assigned, profiles, notes, True, True, cell)
        self.layout_only = {}
        for r in self.people:
            if r in generation_updates:
                self.generation[r] = generation_updates[r]
        # 已有子女随修正后的上代递推，避免只改一个标签。
        def descend(r):
            for child in self.kids[r]:
                self.generation[child] = self.generation[r]+1
                descend(child)
        for r in self.roots:
            descend(r)
        for child, anchor in contexts.items():
            if child not in self.people:
                continue
            assert not self.people[child].get('parent')
            assert anchor in self.people and self.generation[child] > self.generation[anchor]
            self.layout_only[child] = anchor
            self.parent[child] = anchor
            self.kids[anchor].append(child)
            self.kids[anchor].sort(key=lambda rid: (self.people[rid].get('order', self.people[rid]['para']), rid))
            self.roots.remove(child)

    def render(self, page, number):
        rendered = super().render(page, number)
        scale = rendered['scale']
        for atom in rendered['atoms']:
            for p in atom.get('paragraphs', []):
                if 'runs' in p:
                    p['runs'] = [(text, size*scale, bold) for text, size, bold in p['runs']]
        # 版面归组只负责将记载放回所属段落，直接亲属线必须有底稿依据。
        rendered['atoms'] = [a for a in rendered['atoms'] if a['kind'] != 'line' and
                             (a.get('person_record') or (a.get('text', '') not in ('嗣', '继', '出养', '待核') and
                              not a.get('text', '').startswith(('依据《总》', '配偶下置', '图例：'))))]
        rendered['connections'] = []
        boxes = rendered['boxes']
        def line(x, y, a, b):
            if abs(x-a)+abs(y-b) > .01:
                rendered['atoms'].append({'kind':'line','x1':x,'y1':y,'x2':a,'y2':b,'width':1.25*scale,'dashed':False})
        for r in page['members']:
            kids = [c for c in self.kids[r] if c in page['members'] and self.people[c].get('parent') == r]
            if not kids:
                continue
            x = boxes[r]['center']
            family = [r, *self.people[r]['spouses']]
            start = max(boxes[t]['y']+boxes[t]['h'] for t in family)+7*scale
            y = boxes[kids[0]]['y']-46*scale
            assert y > start
            centers = [boxes[c]['center'] for c in kids]
            line(x,start,x,y)
            line(min([x]+centers),y,max([x]+centers),y)
            for c in kids:
                line(boxes[c]['center'],y,boxes[c]['center'],boxes[c]['y']-9*scale)
                kind = self.people[c].get('edge_kind','亲子')
                rendered['connections'].append({'parent':r,'child':c,'kind':kind})
                label = '继' if '继亲' in kind else '嗣' if '承嗣' in kind or '收养' in kind else '出养' if '出养' in kind else ''
                if label:
                    rendered['atoms'].append({'kind':'text','text':label,'x':boxes[c]['center']+6*scale,'y':y+5*scale,
                                              'w':55*scale,'h':19*scale,'size':12*scale,'bold':False,'align':'center'})
        return rendered


def main():
    parser = argparse.ArgumentParser(description='按主稿修复代次并保留源图文字')
    for name in ('layout','presentation','corrections','out'):
        parser.add_argument('--'+name,required=True,type=Path)
    args = parser.parse_args()
    layout = json.loads(args.layout.read_text(encoding='utf-8'))
    updates = json.loads(args.corrections.read_text(encoding='utf-8'))
    records = layout['original_records']
    args.out.mkdir(parents=True,exist_ok=True)
    contexts = {r:v['context'] for r,v in updates.items()}
    generations = {r:v['generation'] for r,v in updates.items()}
    affected = {layout['assigned'][r] for r in updates}
    source_shapes, originals, house_notes, titles = {}, {}, defaultdict(list), {}
    with ZipFile(args.presentation) as package:
        for p in layout['pages']:
            root = etree.fromstring(package.read(f'ppt/slides/slide{p["global_page"]}.xml'))
            originals[p['global_page']] = root
            for shape in root.xpath('./p:cSld/p:spTree/p:sp',namespaces=NS):
                r = shape_record(shape)
                value = shape_text(shape)
                if r in records:
                    if r in source_shapes:
                        assert compact(shape_text(source_shapes[r])) == compact(value)
                    source_shapes[r] = shape
                elif '系谱图' in value:
                    titles[p['house_id']] = re.sub(r'（本户第\d+[／/]\d+页）$','',value).removesuffix('系谱图')
                elif not(re.fullmatch(r'第.+代',value) or value.isdigit() or value in ('嗣','继','出养')) and value:
                    if value not in house_notes[p['house_id']]:
                        house_notes[p['house_id']].append(value)
    profiles = {r:extract_profile(shape,240) for r,shape in source_shapes.items()}
    pages, reference = [], []
    for house in layout['households']:
        h = house['户号']
        old = [p for p in layout['pages'] if p['house_id'] == h]
        new = []
        if h in affected:
            definition = {'id':h,'title':titles[h]}
            notes = [{'text':value} for value in house_notes[h]]
            model = CorrectedHouse(definition,records,layout['assigned'],profiles,notes,contexts,generations,240)
            model.plan()
            for i,p in enumerate(model.pages,1):
                p['global_page'] = len(pages)+i
                rendered = model.render(p,i)
                new.append(rendered)
        else:
            new = [{'house_id':h,'global_page':len(pages)+i,'old_page':p['global_page'],'unchanged_xml':True} for i,p in enumerate(old,1)]
        pages.extend(new)
        for p in old:
            reference.append([h,house['家族'],p['global_page'],'、'.join(str(v['global_page']) for v in new)])
    target = args.out/'村志系谱图_按主稿修正世代_可编辑.pptx'
    serialize(None,pages,originals,layout['width'],layout['height'],target)
    folder = args.out/'逐户可编辑文件'
    folder.mkdir(exist_ok=True)
    for house in layout['households']:
        h = house['户号']
        serialize(None,[p for p in pages if p['house_id']==h],originals,layout['width'],layout['height'],
                  folder/(h+'_'+re.sub(r'[<>:"/\\|?*]','',house['家族'])+'.pptx'))
    with (args.out/'修正前后页码对照.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['户号','家族','原图页','修正后本户图页'])
        writer.writerows(reference)
    (args.out.parent/'修正版面核对.json').write_text(json.dumps({'pages':pages,'updates':updates},ensure_ascii=False),encoding='utf-8')
    print('已重排',len(affected),'户，全册',len(pages),'页。')


if __name__ == '__main__':
    main()
