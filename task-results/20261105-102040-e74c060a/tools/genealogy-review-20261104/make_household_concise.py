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
    args=parser.parse_args()
    layout=json.loads(args.layout.read_text(encoding="utf-8"))
    concise_rules.SUMMARY=re.compile(r"(?:夫妇|夫妻)?(?<![收未无])(?:生育|育|生)(?:"+concise_rules.COUNTS+r"(?:子女|[子女男]))+(?:[：:][^。；;）)]*)?")
    pages=copy.deepcopy(layout["pages"])
    changes=[]
    for page in pages:
        scale=page["scale"]
        for atom in page["atoms"]:
            rid=atom.get("person_record")
            if not rid:
                continue
            original=layout["profiles"][rid]
            titles=[copy.deepcopy(p) for p in atom["paragraphs"] if p["bold"]]
            body=[]
            for value in original["body"]:
                # 特殊亲属关系、婚嫁去向及尚未核定的资料须完整保留。
                protected=any(word in value for word in ["待核","过继","过嗣","收养","嗣业","为嗣","领养","长女嫁","次女嫁","三女嫁"])
                value=value if protected else omit_summary(value,rid,changes)
                value=re.sub(r"[（(]\s*[）)]","",value)
                if value:
                    body.extend({"text":s,"size":17*scale,"bold":False,"leading":24*scale,"align":"left"} for s in wrap(value,CELL,17))
            atom["paragraphs"]=titles+body
            atom["text"]="\n".join(p["text"] for p in atom["paragraphs"])
            assert sum(p["leading"] for p in atom["paragraphs"])<=atom["h"]+1, ("文字精简后超出原框",rid)
    args.out.mkdir(parents=True,exist_ok=True)
    target=args.out/"村志系谱图_一户一图_省略重复子女名单.pptx"
    write_presentation(pages,layout["width"],layout["height"],target)
    (args.out/"精简版删除依据.json").write_text(json.dumps(changes,ensure_ascii=False,indent=2),encoding="utf-8")
    print("精简版已生成，人物框、姓名、坐标和关系线不变；省略重复摘要",len(changes),"处。")


if __name__=="__main__":
    main()
