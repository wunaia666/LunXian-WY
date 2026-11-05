"""在已核对的完整图册上另制省略重复子女名单的版本，保持人物框和接线位置。"""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path

import build_concise_genealogy as concise_rules
from build_concise_genealogy import omit_summary
from build_fulltext_genealogy import wrap
from build_genealogy_presentation import write_presentation
from build_household_atlas import CELL


def main():
    parser=argparse.ArgumentParser(description="另制省略重复子女数量及名单的可编辑图册")
    parser.add_argument("--layout",required=True,type=Path)
    parser.add_argument("--out",required=True,type=Path)
    parser.add_argument("--clean-introductions",action="store_true",help="去掉制作说明，进一步省略普通子女摘要，逐户另存")
    parser.add_argument("--external-review",action="store_true",help="图内不显示核查字样和说明，另交审核文件")
    args=parser.parse_args()
    layout=json.loads(args.layout.read_text(encoding="utf-8"))
    concise_rules.SUMMARY=re.compile(r"(?:夫妇|夫妻)?(?<![收未无])(?:生育|育|生)(?:"+concise_rules.COUNTS+r"(?:子女|[子女男]))+(?:[：:][^。；;）)]*)?")
    pages=copy.deepcopy(layout["pages"])
    changes=[]
    for page in pages:
        scale=page["scale"]
        if args.clean_introductions:
            page["atoms"]=[a for a in page["atoms"] if a.get('person_record') or a['kind']!='text' or not (a.get('text','').startswith('依据《总》逐户编排') or a.get('text','').startswith('配偶下置，不另计一代'))]
        if args.external_review:
            page['atoms']=[a for a in page['atoms'] if a.get('person_record') or a['kind']!='text' or not any(word in a.get('text','') for word in ['待核','须核','需核'])]
        for atom in page["atoms"]:
            rid=atom.get("person_record")
            if not rid:
                continue
            original=layout["profiles"][rid]
            titles=[copy.deepcopy(p) for p in atom["paragraphs"] if p["bold"]]
            body=[]
            for value in original["body"]:
                if args.external_review:
                    person=layout['original_records'][rid]
                    is_review=any(word in value for word in ['待核','须核','需核','待确认','待核实'])
                    if value.startswith(('待核','核对注','上代归属待核')) or (is_review and value in person.get('notes',[])):
                        changes.append({'记录':rid,'移至独立审核文件':value})
                        continue
                    chunks=re.split(r'(?<=[。；;])',value)
                    kept=[]
                    for chunk in chunks:
                        if any(word in chunk for word in ['待核','须核','需核','待确认','待核实']) or (is_review and value.startswith('原记') and not any(word in chunk for word in ['嫁','葬','居住'])):
                            changes.append({'记录':rid,'移至独立审核文件':chunk})
                        else:
                            kept.append(chunk)
                    value=''.join(kept)
                    if not value:
                        continue
                # 特殊亲属关系、婚嫁去向及尚未核定的资料须完整保留。
                protected=any(word in value for word in ["待核","过继","过嗣","收养","嗣业","为嗣","领养","长女嫁","次女嫁","三女嫁"])
                value=value if protected else omit_summary(value,rid,changes)
                if args.clean_introductions and not any(word in value for word in ['待核','须核','需核']):
                    # 混有过继、婚嫁等事实时仅移去普通数量，特殊关系原句保留。
                    ordinary=re.compile(r'(?:夫妇|夫妻)?(?<![收未无])(?:生育|育|生)(?:'+concise_rules.COUNTS+r'(?:子女|[子女男]))+')
                    def remove_count(match):
                        changes.append({'记录':rid,'删除':match.group(),'另保留':'特殊关系及其他原文'})
                        return ''
                    value=ordinary.sub(remove_count,value)
                    value=re.sub(r'[（(][：:，,；;]+','（',value)
                    value=re.sub(r'^原记[，,；;：:]?','',value)
                    value=value.strip('，,；;：: ')
                value=re.sub(r"[（(]\s*[）)]","",value)
                if value:
                    body.extend({"text":s,"size":17*scale,"bold":False,"leading":24*scale,"align":"left"} for s in wrap(value,page.get("person_width",CELL),17))
            atom["paragraphs"]=titles+body
            atom["text"]="\n".join(p["text"] for p in atom["paragraphs"])
            assert sum(p["leading"] for p in atom["paragraphs"])<=atom["h"]+1, ("文字精简后超出原框",rid)
    args.out.mkdir(parents=True,exist_ok=True)
    target=args.out/("村志系谱图_人物介绍版_可编辑.pptx" if args.clean_introductions else "村志系谱图_一户一图_省略重复子女名单.pptx")
    write_presentation(pages,layout["width"],layout["height"],target)
    if args.clean_introductions:
        folder=args.out/'逐户可编辑文件'
        folder.mkdir(exist_ok=True)
        for house in layout['households']:
            safe=re.sub(r'[<>:"/\\|?*]','',house['家族'])
            write_presentation([p for p in pages if p['house_id']==house['户号']],layout['width'],layout['height'],folder/(house['户号']+'_'+safe+'.pptx'))
        layout['pages']=pages
        (args.out/'人物介绍版版面.json').write_text(json.dumps(layout,ensure_ascii=False),encoding='utf-8')
    (args.out/"精简版删除依据.json").write_text(json.dumps(changes,ensure_ascii=False,indent=2),encoding="utf-8")
    print("精简版已生成，人物框、姓名、坐标和关系线不变；省略重复摘要",len(changes),"处。")


if __name__=="__main__":
    main()
