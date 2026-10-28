# -*- coding: utf-8 -*-
"""由电子表格软件直接创建组合、条形、折线和环形图。"""
from 图表页面 import P

def rgb(h):return int(h[:2],16)+int(h[2:4],16)*256+int(h[4:6],16)*65536

SPECS={
    'daily':(51,[('消费金额（元）','G26:G56','B26:B56'),('已完成回访（次）','G26:G56','C26:C56')]),
    'segments':(-4120,[('客户结构','A159:A160','B159:B160')]),
    'stores':(57,[('消费金额（元）','A61:A63','B61:B63')]),
    'completion':(-4120,[('回访计划','A163:A164','B163:B164')]),
    'sixmonths':(4,[('消费金额（元）','A150:A155','B150:B155')]),
    'projects':(57,[('消费金额（元）','A68:A74','B68:B74')]),
    'staff':(57,[('已完成回访（次）','G79:G87','H79:H87')]),
    'overdue':(51,[('逾期任务（次）','A140:A143','B140:B143')]),
    'cards':(-4120,[('开卡结构','A167:A168','B167:B168')]),
    'weekdays':(51,[('服务记录（次）','A128:A134','B128:B134')])}

def create_native_charts(book,layout):
    data=book.Worksheets('图表数据')
    charts={}
    for spec in layout:
        ws=book.Worksheets(spec['sheet']);ws.Activate()
        region=ws.Range(spec['region']);anchor=ws.Range(spec['top_cell'])
        top=anchor.Top+2
        obj=ws.ChartObjects().Add(region.Left+8,top,region.Width-16,region.Top+region.Height-top-6)
        obj.Name='图表_'+spec['key']
        obj.ShapeRange.AlternativeText=spec['title']
        chart=obj.Chart
        kind,series_specs=SPECS[spec['key']]
        chart.ChartType=kind
        chart.ChartStyle=2
        chart.HasTitle=False
        while chart.SeriesCollection().Count:chart.SeriesCollection(1).Delete()
        for index,(name,categories,values) in enumerate(series_specs,1):
            series=chart.SeriesCollection().NewSeries()
            series.Name=name
            series.XValues=data.Range(categories)
            series.Values=data.Range(values)
            if spec['key']=='daily' and index==2:
                series.ChartType=4
                series.AxisGroup=2
        chart.PlotVisibleOnly=False
        chart.ChartArea.Format.Fill.ForeColor.RGB=rgb(P['white'])
        chart.ChartArea.Format.Line.Visible=False
        chart.ChartArea.Font.Name='微软雅黑';chart.ChartArea.Font.Size=9
        charts[spec['key']]=chart
    return charts
