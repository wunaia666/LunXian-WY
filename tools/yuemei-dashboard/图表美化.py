# -*- coding: utf-8 -*-
"""统一原生图表的轴线、数值标签、配色和环形中心指标。"""
from 图表页面 import P

def rgb(h):return int(h[:2],16)+int(h[2:4],16)*256+int(h[4:6],16)*65536

def axis_style(axis):
    axis.TickLabelPosition=4
    axis.TickLabels.Font.Name='微软雅黑'
    axis.TickLabels.Font.Size=9
    axis.TickLabels.Font.Color=rgb(P['muted'])
    axis.MajorTickMark=-4142
    axis.MinorTickMark=-4142
    axis.Format.Line.Visible=False
    if axis.HasTitle:
        axis.AxisTitle.Font.Name='微软雅黑'
        axis.AxisTitle.Font.Size=9
        axis.AxisTitle.Font.Color=rgb(P['muted'])

def plain_labels(series):
    series.ApplyDataLabels(Type=2)
    labels=series.DataLabels()
    for key in ['ShowLegendKey','ShowSeriesName','ShowCategoryName','ShowPercentage','ShowBubbleSize']:
        try:setattr(labels,key,False)
        except Exception:pass
    labels.ShowValue=True
    labels.NumberFormat='#,##0'
    labels.Font.Name='微软雅黑';labels.Font.Size=9
    labels.Font.Color=rgb(P['ink'])
    try:labels.Position=2
    except Exception:pass

def linked_text(ws,name,left,top,width,height,formula=None,text=None,size=20,bold=True):
    shape=ws.Shapes.AddTextbox(1,left,top,width,height)
    shape.Name=name
    shape.Fill.Visible=False;shape.Line.Visible=False
    shape.Placement=1
    if formula:shape.DrawingObject.Formula=formula
    else:shape.TextFrame.Characters().Text=text
    frame=shape.TextFrame
    frame.HorizontalAlignment=-4108;frame.VerticalAlignment=-4108
    frame.MarginLeft=0;frame.MarginRight=0;frame.MarginTop=0;frame.MarginBottom=0
    frame.Characters().Font.Name='微软雅黑';frame.Characters().Font.Size=size
    frame.Characters().Font.Bold=bold
    frame.Characters().Font.Color=rgb(P['ink'] if bold else P['muted'])
    shape.TextFrame2.TextRange.Font.NameFarEast='微软雅黑'
    return shape

def polish(book,charts):
    rings={'segments':('C159','在管客户'),'completion':('C163','完成率'),'cards':('C167','开卡率')}
    horizontal={'stores','projects','staff'}
    for key,chart in charts.items():
        chart.ChartArea.Format.Shadow.Visible=False
        chart.PlotArea.Format.Shadow.Visible=False
        chart.ChartArea.Format.Line.Visible=False
        chart.ChartArea.Format.Fill.ForeColor.RGB=rgb(P['white'])
        if key in rings:
            chart.HasLegend=True
            chart.Legend.Position=-4107
            chart.Legend.Font.Name='微软雅黑';chart.Legend.Font.Size=9
            series=chart.SeriesCollection(1)
            series.HasDataLabels=False
            for index,tone in enumerate([P['ink'],P['olive']],1):
                point=series.Points(index)
                point.Format.Fill.Visible=True;point.Format.Fill.Solid()
                point.Format.Fill.ForeColor.RGB=rgb(tone)
                point.Format.Line.Visible=False
                point.Format.Shadow.Visible=False
            chart.ChartGroups(1).DoughnutHoleSize=73
            chart.Refresh()
            obj=chart.Parent;ws=obj.Parent
            plot=chart.PlotArea
            cx=obj.Left+plot.InsideLeft+plot.InsideWidth/2
            cy=obj.Top+plot.InsideTop+plot.InsideHeight/2
            ref,caption=rings[key]
            linked_text(ws,'环图中心_'+key,cx-40,cy-23,80,31,formula="='图表数据'!"+ref,size=22)
            linked_text(ws,'环图说明_'+key,cx-45,cy+10,90,18,text=caption,size=9,bold=False)
            continue
        chart.HasLegend=key=='daily'
        if chart.HasLegend:
            chart.Legend.Position=-4107
            chart.Legend.Font.Name='微软雅黑';chart.Legend.Font.Size=9
        for index,series in enumerate(chart.SeriesCollection(),1):
            series.Format.Shadow.Visible=False
            if key in ['sixmonths'] or (key=='daily' and index==2):
                series.HasDataLabels=False
                series.Format.Line.ForeColor.RGB=rgb(P['orange'] if key=='daily' else P['ink'])
                series.Format.Line.Weight=2
            else:
                series.Format.Fill.Visible=True;series.Format.Fill.Solid()
                series.Format.Fill.ForeColor.RGB=rgb(P['ink'])
                series.Format.Line.Visible=False
                series.InvertIfNegative=False
                if key!='daily':plain_labels(series)
                else:series.HasDataLabels=False
        if key=='daily':chart.SeriesCollection(2).AxisGroup=2
        category=chart.Axes(1,1);value=chart.Axes(2,1)
        axis_style(category);axis_style(value)
        value.ReversePlotOrder=False
        value.MinimumScale=0
        value.HasMajorGridlines=True
        value.MajorGridlines.Format.Line.ForeColor.RGB=rgb(P['line'])
        value.MajorGridlines.Format.Line.Weight=.5
        if key in horizontal:
            category.ReversePlotOrder=True
            value.Crosses=4
            category.Crosses=2
        if key=='daily':
            category.TickLabelSpacing=5
            secondary=chart.Axes(2,2)
            axis_style(secondary)
            secondary.HasMajorGridlines=False
            secondary.MinimumScale=0
        chart.Refresh()

def finalize_layout(book,charts):
    """在数据切换完成后固定最终留白，并校准环形中心指标。"""
    for key,chart in charts.items():
        chart.HasTitle=False
        if key not in ['segments','completion','cards']:
            for kind in [1,2]:
                try:chart.Axes(kind,1).HasTitle=False
                except Exception:pass
        chart.Refresh()
    for key in ['segments','completion','cards']:
        chart=charts[key];obj=chart.Parent;ws=obj.Parent;plot=chart.PlotArea
        cx=obj.Left+plot.InsideLeft+plot.InsideWidth/2
        cy=obj.Top+plot.InsideTop+plot.InsideHeight/2
        hole=min(plot.InsideWidth,plot.InsideHeight)*.73
        size=min(22,max(14,hole*.24))
        value=ws.Shapes('环图中心_'+key)
        caption=ws.Shapes('环图说明_'+key)
        value.Width=min(80,hole);value.Height=size*1.5
        value.Left=cx-value.Width/2;value.Top=cy-value.Height/2-6
        value.TextFrame.Characters().Font.Size=size
        caption.Width=min(90,hole+10);caption.Height=15
        caption.Left=cx-caption.Width/2;caption.Top=cy+size*.55
        caption.TextFrame.Characters().Font.Size=8.5
        assert value.Left>=obj.Left and value.Top>=obj.Top
    assert all(not chart.HasTitle for chart in charts.values())
