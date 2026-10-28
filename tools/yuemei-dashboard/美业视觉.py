# -*- coding: utf-8 -*-
"""为原生动态图表加入美业摄影、统一图标和暖白玫瑰棕视觉。"""
from pathlib import Path
import argparse,json,shutil
import win32com.client
from PIL import Image
from 图表页面 import P
from 图表美化 import polish,finalize_layout

COLORS={'ink':'49352F','sage':'A08172','olive':'DDCCBF','paper':'F5F1ED',
        'white':'FFFFFF','line':'E9E0D9','muted':'786C65','orange':'BA8565',
        'red':'A34D45','soft':'F0E6DF','gold':'956758'}
P.update(COLORS)
ROOT=Path(__file__).resolve().parent
ART=ROOT/'美化素材'

def rgb(value):return int(value[:2],16)+256*int(value[2:4],16)+65536*int(value[4:],16)

def block(ws,address,text=None,size=11,bold=False,color='ink',fill=None,align=-4131,font='微软雅黑',number=None):
    """用可编辑单元格排版，图片不进入文字区域。"""
    region=ws.Range(address)
    if region.Cells.Count>1:region.Merge()
    if text is not None:region.Cells(1,1).Formula=text if isinstance(text,str) and text.startswith('=') else text
    region.Font.Name=font;region.Font.Size=size;region.Font.Bold=bold
    region.Font.Color=rgb(P[color]);region.VerticalAlignment=-4108;region.HorizontalAlignment=align
    region.WrapText=False;region.IndentLevel=1 if align==-4131 else 0
    if fill:region.Interior.Color=rgb(P[fill])
    if number:region.NumberFormat=number
    return region

def outline(region,color='line'):
    for edge in [7,8,9,10]:
        region.Borders(edge).LineStyle=1;region.Borders(edge).Weight=2
        region.Borders(edge).Color=rgb(P[color])

def picture(ws,path,region,name,padding=0):
    """等比完整显示并内嵌文件，不裁切、不链接本地素材。"""
    r=ws.Range(region)
    with Image.open(path) as im:w,h=im.size
    scale=min((r.Width-padding*2)/w,(r.Height-padding*2)/h)
    width=w*scale;height=h*scale
    shape=ws.Shapes.AddPicture(str(path),False,True,r.Left+(r.Width-width)/2,r.Top+(r.Height-height)/2,width,height)
    shape.Name=name;shape.LockAspectRatio=True;shape.Placement=1
    shape.AlternativeText='护理静物摄影' if '静物' in name else ('护理空间摄影' if '空间' in name else '功能图标')
    return shape

def nav(ws,address,label,sheet):
    b=block(ws,address,'=HYPERLINK("#\''+sheet+'\'!A1","'+label+'")',10,True,'gold','soft',-4108)
    b.Font.Underline=-4142

def canvas(ws,title,subtitle,image_name,home):
    charts={str(o.Name).removeprefix('图表_'):o.Chart for o in ws.ChartObjects()}
    # 只重排两张展示页；原有业务单元格不参与清空。
    for i in range(ws.Shapes.Count,0,-1):
        sh=ws.Shapes(i)
        if not str(sh.Name).startswith('图表_'):sh.Delete()
    ws.Range('A1:AQ64').UnMerge();ws.Range('A1:AQ64').Clear()
    ws.Columns('A:AQ').ColumnWidth=5.2
    ws.Columns('A:A').ColumnWidth=2;ws.Columns('AQ:AQ').ColumnWidth=2
    ws.Rows('1:64').RowHeight=11.5
    for row,height in {1:12,2:20,3:26,4:24,5:18,6:14,7:23,8:19,9:15,10:21,11:25,12:16,13:16,14:14,15:14,16:12,17:8,18:22,19:17,37:12,38:10,39:22,40:17,60:12,61:14,62:14,63:6,64:6}.items():ws.Rows(row).RowHeight=height
    region=ws.Range('A1:AQ64');region.Interior.Color=rgb(P['paper'])
    region.Font.Name='微软雅黑';region.Font.Size=10;region.Font.Color=rgb(P['ink'])
    region.Borders.LineStyle=-4142
    block(ws,'B2:AC2','悦美  /  三门店客户管理',10,True,'gold')
    block(ws,'B3:AC4',title,29,False,'ink',font='宋体')
    block(ws,'B5:AC5',subtitle,10,False,'muted')
    image=picture(ws,ART/image_name,'AF2:AP8','品牌摄影_'+Path(image_name).stem)
    if home:
        for address,label in [('B6:D6','年份'),('F6:H6','月份'),('J6:P6','门店范围')]:block(ws,address,label,9,False,'muted')
        for address,value,fmt in [('B7:D8',2026,'0'),('F7:H8',10,'0"月"'),('J7:P8','全部门店',None)]:
            b=block(ws,address,value,13,True,'ink','white',-4108,number=fmt);outline(b)
        for address,kind,formula,upper in [('B7',1,'2025','2040'),('F7',3,'1,2,3,4,5,6,7,8,9,10,11,12',None),('J7',3,'全部门店,一店,二店,三店',None)]:
            v=ws.Range(address).MergeArea.Validation;v.Delete()
            if upper is None:v.Add(Type=kind,AlertStyle=1,Operator=1,Formula1=formula)
            else:v.Add(Type=kind,AlertStyle=1,Operator=1,Formula1=formula,Formula2=upper)
            v.ShowError=True;v.ErrorTitle='筛选条件无效';v.ErrorMessage='请从列表选择，年份范围为2025至2040。'
        nav(ws,'R7:W8','经营分析  →','图表分析中心')
        nav(ws,'Y7:AD8','回访月历  →','门店工作台')
    else:
        block(ws,'B7:P8','="分析范围  ·  "&\'经营驾驶舱\'!B7&"年"&\'经营驾驶舱\'!F7&"月  /  "&\'经营驾驶舱\'!J7',12,True)
        nav(ws,'R7:W8','经营总览  →','经营驾驶舱')
        nav(ws,'Y7:AD8','回访月历  →','门店工作台')
    ws.Tab.Color=rgb(P['gold']);ws.Activate()
    window=ws.Application.ActiveWindow
    window.DisplayGridlines=False;window.DisplayHeadings=False;window.Zoom=85
    window.ScrollColumn=1;window.ScrollRow=1
    setup=ws.PageSetup
    setup.PrintArea='$A$1:$AQ$64';setup.Orientation=2;setup.PaperSize=8
    setup.Zoom=False;setup.FitToPagesWide=1;setup.FitToPagesTall=1
    setup.CenterHorizontally=True;setup.CenterVertically=True
    setup.LeftMargin=10;setup.RightMargin=10;setup.TopMargin=10;setup.BottomMargin=10
    return charts,image

def panel(ws,address,title,subtitle,key):
    r=ws.Range(address);first=r.Row;last=first+r.Rows.Count-1;c1=r.Column;c2=c1+r.Columns.Count-1
    r.Interior.Color=rgb(P['white']);outline(r)
    block(ws,f'{ws.Cells(first,c1).Address}:{ws.Cells(first,c2-2).Address}',title,12,True,fill='white')
    block(ws,f'{ws.Cells(first,c2-1).Address}:{ws.Cells(first,c2).Address}',key,9,False,'sage','white',-4108)
    block(ws,f'{ws.Cells(first+1,c1).Address}:{ws.Cells(first+1,c2).Address}',subtitle,8.5,False,'muted','white')
    return (r.Left+10,ws.Cells(first+2,c1).Top+3,r.Width-20,r.Top+r.Height-ws.Cells(first+2,c1).Top-11)

def style_charts(book,charts):
    polish(book,charts)
    for key,chart in charts.items():
        chart.ChartArea.Font.Color=rgb(P['ink']);chart.ChartArea.Font.Size=10
        if key in ['segments','completion','cards']:
            chart.ChartGroups(1).DoughnutHoleSize=78
            chart.Legend.Font.Color=rgb(P['muted']);chart.Legend.Font.Size=9
            # 次要部分用浅沙色，主部分使用玫瑰棕。
            for i,tone in enumerate(['956758','E5D8CE'],1):chart.SeriesCollection(1).Points(i).Format.Fill.ForeColor.RGB=rgb(tone)
            if key=='cards':
                chart.Legend.Position=-4152
                chart.PlotArea.Width=min(chart.Parent.Height-5,chart.Parent.Width*.55)
                chart.PlotArea.Height=chart.Parent.Height-5
                chart.PlotArea.Left=chart.Parent.Width*.42-chart.PlotArea.Width/2;chart.PlotArea.Top=1
                chart.Legend.Left=chart.Parent.Width*.60
                chart.Legend.Top=(chart.Parent.Height-chart.Legend.Height)/2
            continue
        chart.Axes(1,1).TickLabels.Font.Size=9.5
        chart.Axes(2,1).TickLabels.Font.Size=9.5
        chart.Axes(2,1).MajorGridlines.Format.Line.ForeColor.RGB=rgb(P['line'])
        for i,series in enumerate(chart.SeriesCollection(),1):
            if key=='sixmonths' or (key=='daily' and i==2):
                series.Format.Line.ForeColor.RGB=rgb(P['orange'] if key=='daily' else P['gold'])
                series.Format.Line.Weight=2.5
                series.MarkerStyle=8 if key=='sixmonths' else -4142
                if key=='sixmonths':
                    series.MarkerSize=5;series.MarkerBackgroundColor=rgb(P['white']);series.MarkerForegroundColor=rgb(P['gold'])
            else:
                series.Format.Fill.ForeColor.RGB=rgb(P['gold'])
                if key in ['stores','projects','overdue','weekdays']:
                    shades=['956758','B58F7C','D2B4A1','DFCCC0','C3A08E','AB8170','DCC7B9']
                    for j in range(1,series.Points().Count+1):series.Points(j).Format.Fill.ForeColor.RGB=rgb(shades[(j-1)%len(shades)])
        if key not in ['sixmonths']:
            try:chart.ChartGroups(1).GapWidth=75 if key in ['stores','projects','staff'] else 85
            except Exception:pass
    finalize_layout(book,charts)

def redesign(book):
    """沿用原有公式与原生图表，只重建展示层。"""
    driver=book.Worksheets('经营驾驶舱')
    filters=[driver.Range(a).Value for a in ['B7','F7','J7']]
    charts,hero=canvas(driver,'门店经营总览','把消费、客群与回访，放在同一张清楚的工作台。','护理静物.jpg',True)
    center=book.Worksheets('图表分析中心')
    extra,hero2=canvas(center,'经营分析','看见服务的变化，也看见每一次跟进的进展。','护理空间.jpg',False)
    charts.update(extra)
    cards=[('本月消费 / 元','B7','="较上月  "&IF(\'图表数据\'!B15=0,"暂无可比数据",TEXT(\'图表数据\'!B16,"+0.0%;-0.0%;0.0%"))','#,##0','金额'),
           ('本月到店','B8','="服务记录 / 次"','0','门店'),
           ('在管客户','B9','="新客 "&\'图表数据\'!B19&"  ·  老客 "&\'图表数据\'!B20','0','客户'),
           ('回访完成率','B12','="计划 "&\'图表数据\'!B10&"  ·  完成 "&\'图表数据\'!B11','0%','图表趋势'),
           ('当前逾期','B13','="待优先处理 / 次"','0','提醒'),
           ('生日待关怀','B14','="提前15天关怀 / 人"','0','日历')]
    for i,(label,ref,note,fmt,icon) in enumerate(cards):
        c=2+i*7;left=driver.Cells(10,c);right=driver.Cells(15,c+5)
        r=driver.Range(left,right);r.Interior.Color=rgb(P['white'])
        block(driver,driver.Range(driver.Cells(10,c),driver.Cells(10,c+3)).Address,label,10,False,'muted','white')
        block(driver,driver.Range(driver.Cells(11,c),driver.Cells(13,c+5)).Address,"='图表数据'!"+ref,29,False,'red' if i==4 else 'ink','white',number=fmt,font='Arial')
        block(driver,driver.Range(driver.Cells(14,c),driver.Cells(15,c+5)).Address,note,8.5,False,'muted','white')
        icon_region=driver.Range(driver.Cells(10,c+4),driver.Cells(10,c+5))
        picture(driver,ART/(icon+'.png'),icon_region.Address,'指标图标_'+icon,padding=3)
    # 首项指标承担视觉重心，其余指标留在浅色面板中。
    driver.Range('B10:G15').Interior.Color=rgb(P['ink'])
    driver.Range('B10:G15').Font.Color=rgb(P['white'])
    driver.Range('B14:G15').Font.Color=rgb(P['olive'])
    specs=[(driver,'B18:AC36','本月消费与回访','消费金额 / 元     回访完成 / 次','daily','01'),
           (driver,'AE18:AP36','新老客结构','当前客户档案 · 随门店切换','segments','02'),
           (driver,'B39:V59','门店消费贡献','按所选月服务记录的消费金额汇总 / 元','stores','03'),
           (driver,'X39:AP59','本月回访计划','按计划日期统计 · 已停用任务不计入','completion','04'),
           (center,'B10:V25','近六个月消费走势','以所选月份为终点 / 元','sixmonths','01'),
           (center,'X10:AP25','服务项目消费构成','相同项目合并汇总 / 元','projects','02'),
           (center,'B28:V45','员工回访排行','按所选月实际完成次数排序 · 前9位 / 次','staff','03'),
           (center,'X28:AP45','当前逾期时长','截至今日的待处理任务 / 次','overdue','04'),
           (center,'B48:V61','开卡客户结构','按当前客户的开卡状态统计','cards','05'),
           (center,'X48:AP61','周内到店节奏','所选月份，周一至周日的服务记录 / 次','weekdays','06')]
    geometry=[]
    for ws,address,title,subtitle,key,number in specs:
        if ws.Name=='图表分析中心':
            r=ws.Range(address).Row;ws.Rows(r).RowHeight=22;ws.Rows(r+1).RowHeight=17
        left,top,width,height=panel(ws,address,title,subtitle,number)
        obj=ws.ChartObjects().Item('图表_'+key)
        obj.Left=left;obj.Top=top;obj.Width=width;obj.Height=height
        geometry.append({'页面':ws.Name,'图表':key,'区域':address,'宽度':round(width,1),'高度':round(height,1)})
    block(driver,'B61:AP62','使用方法：切换年份、月份与门店。继续录入服务和回访记录，图表会随计算更新。',9,False,'muted')
    block(center,'B63:AP64','统计口径：服务按服务日，回访按实际完成日，计划执行按计划日；客户结构、逾期和生日为当前状态。',8.5,False,'muted')
    for a,value in zip(['B7','F7','J7'],filters):driver.Range(a).Value=value
    book.Application.CalculateFullRebuild()
    style_charts(book,charts)
    # 业务表统一表头与字体，保留所有内容、公式和条件提醒规则。
    for ws in book.Worksheets:
        if ws.Name in ['经营驾驶舱','图表分析中心','图表数据','农历对照']:continue
        for table in ws.ListObjects:
            table.TableStyle='TableStyleLight1'
            table.HeaderRowRange.Interior.Color=rgb(P['gold'])
            table.HeaderRowRange.Font.Color=rgb(P['white'])
            table.HeaderRowRange.Font.Name='微软雅黑';table.HeaderRowRange.Font.Size=10;table.HeaderRowRange.Font.Bold=True
        ws.Tab.Color=rgb(P['sage'])
    # 图像与图表的包围框不得相交，摄影只属于页首。
    for ws,image in [(driver,hero),(center,hero2)]:
        for obj in ws.ChartObjects():
            assert image.Top+image.Height<=obj.Top,'摄影不能遮挡数据图表'
        assert image.Top+image.Height<=ws.Range('B10').Top,'摄影不能遮挡指标区'
    driver.Activate();driver.Range('J7').Select()
    return geometry

def enhance(source,output,qa):
    source=Path(source).resolve();output=Path(output).resolve();qa=Path(qa).resolve()
    assert source!=output,'使用新文件名保留原版'
    qa.mkdir(parents=True,exist_ok=True);output.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,output)
    app=win32com.client.DispatchEx('Excel.Application')
    app.Visible=False;app.DisplayAlerts=False;app.ScreenUpdating=False
    book=None
    try:
        book=app.Workbooks.Open(str(output),UpdateLinks=0)
        geometry=redesign(book)
        book.CheckCompatibility=False;book.Save()
        for name in ['经营驾驶舱','图表分析中心']:book.Worksheets(name).ExportAsFixedFormat(0,str(qa/(name+'.pdf')))
        book.Worksheets('经营驾驶舱').Activate();book.Save()
        (qa/'视觉检查.json').write_text(json.dumps({'原生图表':geometry,'图片':'两张内嵌摄影，完整等比显示','遮挡检查':'通过'},ensure_ascii=False,indent=2),encoding='utf-8')
        print('两页视觉重构已完成，十张原生图表和两张摄影均已保存。',flush=True)
    finally:
        if book is not None:book.Close(False)
        app.Quit()

if __name__=='__main__':
    p=argparse.ArgumentParser(description='美化已包含动态图表的悦美工作簿。')
    p.add_argument('--source',required=True);p.add_argument('--output',required=True);p.add_argument('--qa-dir',required=True)
    a=p.parse_args();enhance(a.source,a.output,a.qa_dir)
