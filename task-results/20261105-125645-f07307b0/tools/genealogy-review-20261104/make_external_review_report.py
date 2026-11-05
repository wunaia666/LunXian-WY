"""把图外审核事项写成带具体原因、原文和核查问题的独立文件。"""

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

from docx import Document
from docx.shared import Mm, Pt
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill


def explanation(item, person, records):
    reason = item['待审核事项']
    raw = person['raw']
    name = person['name']
    parent = records.get(person.get('owner') or person.get('parent'), {})
    status = '需人工确认'
    if person.get('continuation_of') or ('上代归属待核' in reason and person.get('owner') and not person.get('issues')):
        return ('断行误提取已纠正', '已纠正，留档说明',
                '此前把子女名单的跨段续行误识别为独立人物，生成了不适用的“上代归属待核”附注。原稿上下两段实际组成同一句名单。现已归回配偶资料框，相关附注不再属于真实亲属疑点。',
                '本项仅留存整理纠错依据，不要求用户另认定一个人物或上代。')
    if '不能随张氏材料一并删除' in reason:
        return ('分户范围说明', '已按主稿分户，留档说明',
                '此人为刘氏住户，原稿与张氏同段出现容易在按姓分户时被误并或漏掉。这是资料整理范围问题，现已独立保留；该附注本身不证明其亲属关系存在冲突。',
                '如需调整分户范围，可核对该户是否应独立制图；无需仅因与张氏同段而删人。')
    if '卒年早于生年' in reason or '卒年早于' in reason:
        years=re.search(r'((?:1[6-9]|20)\d{2})年?[—－-]+((?:1[6-9]|20)\d{2})',re.sub(r'\s+','',raw))
        detail=f'原文将生年记作{years[1]}年、卒年记作{years[2]}年，卒年比生年早{int(years[1])-int(years[2])}年。' if years else reason
        return ('生卒年份矛盾',status,detail+'这组年份在时间顺序上不能同时成立，但仅凭当前材料无法判定是出生年、死亡年还是数字书写有误，不能自行调换或补改。',
                f'请确认{name}正确的出生年和卒年，或提供碑文、旧谱、户籍等可核对依据；若仍不能确认，原始年份继续留档。')
    if '生年相差-' in reason:
        return ('上下代生年矛盾',status,
                reason.replace('待核：','')+'。按当前接续，上代为'+parent.get('name','原列上代')+'。下代出生早于所接上代，当前年份和普通亲子接法不能同时成立；也可能牵涉继亲、收养或原稿误记。年龄仅能提示矛盾，不能据此改挂人物。',
                '请分别核实两人的出生年，并明确关系为生身、继亲还是承嗣；如是继亲或收养，请写清生身父母与嗣父母。')
    if any(s in reason for s in ['是否同人','另记','另见','另一人或别名','两种原记并存']):
        return ('姓名异写或同人对应',status,
                reason.replace('待核：','')+' 名单和人物正文属于不同记载位置，写法不同可能来自笔误、曾用名或另一位成员。现有资料不足以排除这些情况，因此不能直接更名、合并，或凭此新增一个确定人物。',
                '请逐一确认两种姓名是否指同一人；如是，请指定正式姓名并注明别名或原文异写；如不是，请补充各自父母、配偶及排行。')
    if '新版' in reason or '版本差异' in reason:
        return ('不同版本归属冲突',status,
                reason.replace('待核：','')+' 当前图册按用户指定的《总》接续，采用主稿是编排依据，不等于两个版本的事实冲突已经解决。不能用另一版重复记载自行合并或另增一支。',
                '请核实本人乳名、生年、配偶及子女是否对应同人，再明确生父、生母、嗣父或共同收养者；说明两个版本分别记错了哪里或各自指什么关系。')
    if any(s in reason for s in ['代际','接续待核','上代衔接','曾祖父','高祖父']):
        return ('上代接续缺失',status,
                reason.replace('待核：','')+' 总述中的祖辈称谓与后文起首人物之间缺少可逐代验证的父子链，不能为了连成整树补造中间人物或把祖孙直接接成父子。',
                '请按“上一代姓名—下一代姓名”的形式补足中间代；如同人异名，应先确认同人依据，再确定是否合框。')
    if any(s in reason for s in ['称谓','层次','同辈','父母','逐人','对应','归属','孙女三个']):
        return ('代次称谓或父母归属',status,
                reason.replace('待核：','')+' 原稿的亲属称谓可能以不同人物为参照，段落先后本身不能证明某人是谁的子女。当前候选接线和相对代次为便于查阅保留，不是新增事实结论。',
                f'请确认{name}的父亲、母亲及与当前所接亲属的关系；若只是原称谓写错，请写明正确称谓。原文未具名者还需确认人数、排行及婚嫁去向。')
    if any(s in reason for s in ['数量','缺一子','名单及正文仅列','人数']):
        return ('人数与名单不符',status,
                reason.replace('待核：','')+' 数量摘要与逐人记录不能相互吻合，可能是摘要写错、名单缺人或姓名对应错误。未有独立证据前，不能凭差额造出一个新成员。',
                '请列出该家庭全部子女的姓名、性别、排行和父母，确认到底是数量误记还是漏录成员。')
    if any(s in reason for s in ['收养','过继','承嗣','继亲','入赘']):
        context=person.get('context',raw)
        if person.get('render_as'):
            context+='；本条已与同人记录合框，保留两处来源。'
        detail='原文含特殊关系记载：'+context
        return ('特殊关系及生身、承嗣区分',status,
                detail+' 这里不能把“抚养、出继、立嗣、入赘”全部当作普通生身父子关系。原文明示的特殊关系已经保留，本项主要复核其具体对象、生身与嗣系区别，以及是否存在另一处同人记载；不是声称原文已明确的过继事实全部不成立。',
                '请说明该记载指谁与谁、关系性质为何，以及生身父母和嗣父母分别是谁。原文只写送养去向而未写收养者姓名的，请尽可能补充；原文已明确的事实无需重复推翻。')
    return ('原文信息不足',status,
            reason.replace('待核：','')+' 本条尚无足够的交叉记载使这一点唯一确定，故将原文与疑点独立列出，便于与亲属或旧谱逐项核对。',
            '请针对上述具体疑点提供确定记载，并写明核对依据；未确认前保留原始记录。')


def main():
    parser=argparse.ArgumentParser(description='生成独立详细审核文件')
    parser.add_argument('--layout',type=Path,required=True)
    parser.add_argument('--list',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    data=json.loads(args.layout.read_text(encoding='utf-8'))
    records=data['original_records']
    old=list(csv.DictReader(args.list.open(encoding='utf-8-sig')))
    listed={item['记录编号'] for item in old}
    house_names={item['户号']:item['家族'] for item in data['households']}
    for rid,person in records.items():
        target=person.get('render_as',rid)
        reasons=[value for value in data['profiles'][target]['body'] if any(word in value for word in ['待核','须核','需核','待确认'])]
        if rid in listed or not reasons or person.get('continuation_of'):
            continue
        old.append({'序号':str(len(old)+1),'记录编号':rid,'家族':house_names[data['assigned'][rid]],
                    '所在图页':'、'.join(str(page['global_page']) for page in data['pages'] if target in page['record_ids']),
                    '原稿段号':str(person['para']),'原文出处':'\n'.join(f"第{x['para']}段：{x['text']}" for x in person['fragments']),
                    '待审核事项':'\n'.join(reasons)})
    house_order={house['户号']:index for index,house in enumerate(data['households'])}
    old.sort(key=lambda item:(house_order[data['assigned'][item['记录编号']]],int(item['原稿段号']),item['记录编号']))
    for number,item in enumerate(old,1):item['序号']=str(number)
    rows=[]
    for item in old:
        person=records[item['记录编号']]
        category,status,cause,question=explanation(item,person,records)
        related=[]
        refs=[person.get('owner'),person.get('parent')]+person.get('spouses',[])
        parent=records.get(person.get('parent'),{})
        refs+=parent.get('spouses',[])
        for rid in dict.fromkeys(refs):
            if rid in records:
                p=records[rid]
                fragments=p.get('fragments',[{'para':p['para'],'text':p['raw']}])
                related.extend(f"第{x['para']}段，{p['name']}相关原文：{x['text']}" for x in fragments)
        detail={
            '序号':int(item['序号']),'家族':item['家族'],'人物或原称谓':person['name'],
            '状态':status,'问题类别':category,'所在图页':item['所在图页'],
            '原稿段号':item['原稿段号'],'原文记载':item['原文出处'],
            '相关亲属原文':'\n'.join(related) or '原稿未明确可直接对应的上代。',
            '原有核查记录':item['待审核事项'],'具体原因':cause,'需要确认的问题':question,
            '当前图中处理':'人物及既有候选接线保持原位置；图内不出现核查字样，未确认的事实不因隐藏标记而转为确认。',
            '确认结论':'','确认依据或来源':'','记录编号':item['记录编号']}
        rows.append(detail)
    args.out.mkdir(parents=True,exist_ok=True)
    with (args.out/'独立待审核详细清单.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    book=Workbook();sheet=book.active;sheet.title='逐项审核'
    sheet.append(list(rows[0]))
    for row in rows:sheet.append(list(row.values()))
    sheet.freeze_panes='D2';sheet.auto_filter.ref=sheet.dimensions
    widths=[7,28,18,25,25,14,14,65,65,65,85,70,65,45,45,22]
    for n,width in enumerate(widths,1):sheet.column_dimensions[sheet.cell(1,n).column_letter].width=width
    for row in sheet:
        for c in row:c.font=Font(name='宋体',size=11);c.alignment=Alignment(vertical='top',wrap_text=True)
    for c in sheet[1]:c.font=Font(name='黑体',size=11,bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='333333')
    for n in range(2,len(rows)+2):sheet.row_dimensions[n].height=180
    intro=book.create_sheet('阅读说明',0)
    intro.append(['独立待审核详细清单'])
    intro.append(['图内按要求不显示核查标记；候选关系并不因此变成已确认关系。'])
    intro.append(['每行列原文、相关亲属、具体原因、所需确认内容和空白确认栏；长段落也可在配套文字文档中完整阅读。'])
    intro.append([f"共{len(rows)}条来源记录；其中{sum(r['状态']=='需人工确认' for r in rows)}条需人工确认，其他为已纠正或分户说明。重复来源记录不等于不同人口。"])
    intro.column_dimensions['A'].width=115
    for row in intro:
        row[0].font=Font(name='宋体',size=12);row[0].alignment=Alignment(wrap_text=True);intro.row_dimensions[row[0].row].height=42
    book.save(args.out/'独立待审核详细清单.xlsx')
    doc=Document();section=doc.sections[0]
    section.page_width=Mm(210);section.page_height=Mm(297)
    section.top_margin=section.bottom_margin=Mm(18);section.left_margin=section.right_margin=Mm(20)
    for style in ['Normal','Heading 1','Heading 2','Title']:
        doc.styles[style].font.name='宋体' if style=='Normal' else '黑体'
        doc.styles[style]._element.rPr.rFonts.set(qn('w:eastAsia'),doc.styles[style].font.name)
    doc.styles['Normal'].font.size=Pt(10.5)
    doc.styles['Normal'].paragraph_format.line_spacing=Pt(15)
    doc.styles['Normal'].paragraph_format.space_after=Pt(5)
    doc.styles['Heading 1'].font.size=Pt(16);doc.styles['Heading 2'].font.size=Pt(12)
    doc.add_heading('独立待审核详细清单',0)
    doc.add_paragraph('依据指定的《总》与已整理关系记录编写。图内不显示“待核”及相关说明，全部在本文件留存。')
    doc.add_paragraph(f"共{len(rows)}条来源记录；其中{sum(r['状态']=='需人工确认' for r in rows)}条需人工确认，其他为已纠正或分户说明。")
    doc.add_paragraph('图页为人物介绍版整册页码。每项先列原文及当前对应亲属，再解释问题原因。姓名相同、年龄相近或段落相邻都不单独作为确认关系的依据。')
    doc.add_paragraph('图内隐藏标记仅为呈现调整，不代表尚未确认的关系已经定稿。请在每项末尾填写确认结论和依据。')
    for row in rows:
        doc.add_page_break()
        doc.add_heading(f"{row['序号']}．{row['人物或原称谓']}｜{row['问题类别']}",1)
        doc.add_paragraph(f"家族：{row['家族']}　整册图页：{row['所在图页']}　原稿段号：{row['原稿段号']}")
        doc.add_paragraph('状态：'+row['状态'])
        for title,key in [('一、原文记载','原文记载'),('二、相关亲属原文','相关亲属原文'),('三、具体原因','具体原因'),('四、原有核查记录','原有核查记录'),('五、需要确认的问题','需要确认的问题')]:
            doc.add_heading(title,2)
            for text in row[key].split('\n'):doc.add_paragraph(text)
        doc.add_paragraph('当前处理：'+row['当前图中处理'])
        doc.add_paragraph('确认结论：')
        doc.add_paragraph('确认依据或来源：')
    footer=section.footer.paragraphs[0];footer.alignment=1
    field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
    doc.core_properties.author='';doc.core_properties.last_modified_by='';doc.core_properties.title='独立待审核详细清单'
    doc.save(args.out/'独立待审核详细清单.docx')
    lines=['独立待审核详细清单','图内不显示核查标记；未确认关系不因此转为确认。','']
    for row in rows:
        lines.extend([f"{row['序号']}．{row['人物或原称谓']}（{row['家族']}，图页{row['所在图页']}）"]+[key+'：'+row[key] for key in ['状态','原文记载','相关亲属原文','具体原因','原有核查记录','需要确认的问题']]+[''])
    (args.out/'独立待审核详细清单.txt').write_text('\n'.join(lines),encoding='utf-8-sig')
    actual=Document(args.out/'独立待审核详细清单.docx')
    text=''.join(p.text for p in actual.paragraphs)
    compact=lambda value:re.sub(r'\s+','',value)
    assert all(compact(row['具体原因']) in compact(text) and compact(row['需要确认的问题']) in compact(text) for row in rows)
    check=load_workbook(args.out/'独立待审核详细清单.xlsx',read_only=True);assert check['逐项审核'].max_row==len(rows)+1;check.close()
    (args.out/'审核清单内容.json').write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
    print('独立详细文件已生成；条数',len(rows),'状态统计',dict(Counter(r['状态'] for r in rows)))


if __name__=='__main__':main()
