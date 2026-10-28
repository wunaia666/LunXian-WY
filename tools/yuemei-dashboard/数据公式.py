# -*- coding: utf-8 -*-
"""集中定义动态图表口径，所有统计均从原生数据表计算。"""

def build_formulas():
    f={}
    def put(cell,formula):f[cell]=formula
    put('B2',"=DATE('经营驾驶舱'!$B$7,'经营驾驶舱'!$F$7,1)")
    put('B3','=EDATE(B2,1)')
    put('B4',"=IF('经营驾驶舱'!$J$7=\"全部门店\",\"*\",'经营驾驶舱'!$J$7)")
    put('B5','=EDATE(B2,-1)')
    service='Services[所属门店],$B$4,Services[服务日期],">="&$B$2,Services[服务日期],"<"&$B$3'
    planned='Followups[所属门店],$B$4,Followups[计划回访日],">="&$B$2,Followups[计划回访日],"<"&$B$3'
    actual='Followups[所属门店],$B$4,Followups[实际跟进时间],">="&$B$2,Followups[实际跟进时间],"<"&$B$3,Followups[完成状态],"已完成"'
    put('B7',f'=SUMIFS(Services[消费金额（元）],{service})')
    put('B8',f'=COUNTIFS(Services[记录编号],"<>",{service})')
    put('B9','=COUNTIFS(Customers[客户编号],"<>",Customers[所属门店],$B$4)')
    put('B10',f'=COUNTIFS(Followups[任务编号],"<>",{planned},Followups[完成状态],"<>已停用")')
    put('B11',f'=COUNTIFS({planned},Followups[完成状态],"已完成")')
    put('B12','=IF(B10=0,0,B11/B10)')
    put('B13','=COUNTIFS(Followups[所属门店],$B$4,Followups[完成状态],"逾期")')
    put('B14','=COUNTIFS(Birthdays[客户编号],"<>",Birthdays[所属门店],$B$4,Birthdays[提醒状态],"待提醒")')
    put('B15','=SUMIFS(Services[消费金额（元）],Services[所属门店],$B$4,Services[服务日期],">="&$B$5,Services[服务日期],"<"&$B$2)')
    put('B16','=IF(B15=0,0,(B7-B15)/B15)')
    put('B17','=B10-B11')
    put('B18',f'=COUNTIFS({actual})')
    put('B19','=COUNTIFS(Customers[客户编号],"<>",Customers[所属门店],$B$4,Customers[客户分类],"新客")')
    put('B20','=COUNTIFS(Customers[客户编号],"<>",Customers[所属门店],$B$4,Customers[客户分类],"老客")')
    for i in range(31):
        r=26+i
        put(f'A{r}',f'=IF({i+1}>DAY(EOMONTH($B$2,0)),"",$B$2+{i})')
        put(f'G{r}',f'=IF(A{r}="","",TEXT(A{r},"d日"))')
        put(f'B{r}',f'=IF(A{r}="",0,SUMIFS(Services[消费金额（元）],Services[所属门店],$B$4,Services[服务日期],">="&A{r},Services[服务日期],"<"&A{r}+1))')
        put(f'C{r}',f'=IF(A{r}="",0,COUNTIFS(Followups[所属门店],$B$4,Followups[实际跟进时间],">="&A{r},Followups[实际跟进时间],"<"&A{r}+1,Followups[完成状态],"已完成"))')
        put(f'D{r}',f'=IF(A{r}="",0,COUNTIFS(Services[记录编号],"<>",Services[所属门店],$B$4,Services[服务日期],">="&A{r},Services[服务日期],"<"&A{r}+1))')
        put(f'E{r}',f'=IF(A{r}="",0,COUNTIFS(Followups[任务编号],"<>",Followups[所属门店],$B$4,Followups[计划回访日],A{r},Followups[完成状态],"<>已停用"))')
        put(f'F{r}',f'=IF(A{r}="",0,COUNTIFS(Birthdays[客户编号],"<>",Birthdays[所属门店],$B$4,Birthdays[下次公历生日],A{r}))')
        put(f'H{r}',f'=IF(A{r}="",0,E{r}-COUNTIFS(Followups[所属门店],$B$4,Followups[计划回访日],A{r},Followups[完成状态],"已完成"))')
        put(f'I{r}',f'=IF(A{r}="","",WEEKDAY(A{r},2))')
    for r in range(61,64):
        active=f'OR($B$4="*",A{r}=$B$4)'
        put(f'B{r}',f'=IF({active},SUMIFS(Services[消费金额（元）],Services[所属门店],A{r},Services[服务日期],">="&$B$2,Services[服务日期],"<"&$B$3),0)')
        put(f'C{r}',f'=IF({active},COUNTIFS(Customers[客户编号],"<>",Customers[所属门店],A{r}),0)')
    projects=['面部深层护理','肩颈疏通','光电嫩肤','身体护理','头皮护理','产品零售']
    for r,project in enumerate(projects,68):
        value=f'SUMIFS(Services[消费金额（元）],{service},Services[服务项目],A{r})'
        if project=='身体护理':value+=f'+SUMIFS(Services[消费金额（元）],{service},Services[服务项目],"身体SPA")'
        put(f'B{r}','='+value)
    put('B74','=B7-SUM(B68:B73)')
    # 预留40名人员；前9名排序图会随门店和新增人员更新。
    for i in range(40):
        r=79+i;source=3+i
        put(f'A{r}',f'=IF(OR(\'门店员工\'!B{source}="",\'门店员工\'!C{source}="管理员",AND($B$4<>"*",\'门店员工\'!A{source}<>$B$4)),"",\'门店员工\'!B{source})')
        put(f'B{r}',f'=IF(A{r}="",0,COUNTIFS({actual},Followups[负责员工],A{r}))')
        put(f'C{r}',f'=IF(A{r}="",0,COUNTIFS(Customers[客户编号],"<>",Customers[所属门店],$B$4,Customers[负责员工],A{r}))')
        put(f'E{r}',f'=IF(A{r}="",0,COUNTIFS(Followups[所属门店],$B$4,Followups[负责员工],A{r},Followups[完成状态],"逾期"))')
        put(f'F{r}',f'=IF(A{r}="",1000+ROW(),COUNTIFS($B$79:$B$118,">"&B{r},$A$79:$A$118,"<>")+COUNTIFS($B$79:B{r},B{r},$A$79:A{r},"<>"))')
    for i in range(9):
        r=79+i
        put(f'G{r}',f'=IFERROR(INDEX($A$79:$A$118,MATCH({i+1},$F$79:$F$118,0)),"")')
        put(f'H{r}',f'=IF(G{r}="",0,INDEX($B$79:$B$118,MATCH({i+1},$F$79:$F$118,0)))')
    put('J78','=MAX(1,MIN(9,COUNTIF(A79:A118,"?*")))')
    for i in range(7):
        r=128+i
        put(f'B{r}',f'=SUMIF($I$26:$I$56,{i+1},$D$26:$D$56)')
    for r,low,high in [(140,1,3),(141,3,8),(142,8,15),(143,15,1000000)]:
        put(f'B{r}',f'=COUNTIFS(Followups[所属门店],$B$4,Followups[完成状态],"逾期",Followups[逾期天数],">={low}",Followups[逾期天数],"<{high}")')
    for i in range(6):
        r=150+i
        put(f'C{r}',f'=EDATE($B$2,{i-5})')
        put(f'A{r}',f'=TEXT(C{r},"yy年m月")')
        put(f'B{r}',f'=SUMIFS(Services[消费金额（元）],Services[所属门店],$B$4,Services[服务日期],">="&C{r},Services[服务日期],"<"&EDATE(C{r},1))')
    put('B159','=B19');put('B160','=B20')
    put('B163','=B11');put('B164','=B17')
    put('B167','=COUNTIFS(Customers[客户编号],"<>",Customers[所属门店],$B$4,Customers[开卡情况],"已开卡")')
    put('B168','=B9-B167')
    put('C159','=TEXT(B9,"0")')
    put('C163','=TEXT(B12,"0%")')
    put('C167','=IF(B9=0,"0%",TEXT(B167/B9,"0%"))')
    return f
