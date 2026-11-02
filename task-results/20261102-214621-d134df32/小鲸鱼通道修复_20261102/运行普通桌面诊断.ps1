# 此诊断不接管登录，不操作原安装，也不设置自动触发器。
$ErrorActionPreference = 'Stop'
$diagnosticName = '小鲸鱼副本普通桌面诊断20261102'
if (Get-ScheduledTask -TaskName $diagnosticName -ErrorAction SilentlyContinue) {
    throw '同名诊断任务已存在，停止覆盖'
}
$diagnosticUser = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$diagnosticPrincipal = New-ScheduledTaskPrincipal -UserId $diagnosticUser -LogonType Interactive -RunLevel Limited
$diagnosticAction = New-ScheduledTaskAction -Execute 'C:\Users\14431\AppData\Local\Programs\Python\Python311\pythonw.exe' `
    -Argument '-B -X utf8 "E:\sss\小鲸鱼通道修复_20261102\捕获副本启动异常.py" --normal-desktop --observe-window-station' `
    -WorkingDirectory 'E:\sss\小鲸鱼通道修复_20261102'
$diagnosticSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $diagnosticName -Principal $diagnosticPrincipal -Action $diagnosticAction -Settings $diagnosticSettings | Out-Null
try {
    $diagnosticBegin = Get-Date
    Start-ScheduledTask -TaskName $diagnosticName
    for ($diagnosticIndex = 0; $diagnosticIndex -lt 90; $diagnosticIndex++) {
        $diagnosticOutput = Get-Item -LiteralPath 'E:\sss\小鲸鱼通道修复_20261102\证据\普通桌面窗口站实测.local.json' -ErrorAction SilentlyContinue
        if ($diagnosticOutput -and $diagnosticOutput.LastWriteTime -ge $diagnosticBegin) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $diagnosticOutput -or $diagnosticOutput.LastWriteTime -lt $diagnosticBegin) {
        throw '本次诊断未产生新证据，不能使用上一轮文件'
    }
    $diagnosticResult = Get-Content -LiteralPath 'E:\sss\小鲸鱼通道修复_20261102\证据\普通桌面窗口站实测.local.json' -Raw | ConvertFrom-Json
    $diagnosticResult | Select-Object '进程号','正常退出事件','启动器环境' | ConvertTo-Json -Depth 5
    $diagnosticResult.'窗口站调用实测' | Select-Object '阶段','最后系统错误','令牌' | ConvertTo-Json -Depth 8
} finally {
    Unregister-ScheduledTask -TaskName $diagnosticName -Confirm:$false
}
