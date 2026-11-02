# 仅临时核对当前桌面环境，检查结束移除本诊断任务。
$ErrorActionPreference = 'Stop'
$probeName = '小鲸鱼桌面环境核对20261102'
if (Get-ScheduledTask -TaskName $probeName -ErrorAction SilentlyContinue) { throw '同名诊断任务已存在' }
$probeUser = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$probePrincipal = New-ScheduledTaskPrincipal -UserId $probeUser -LogonType Interactive -RunLevel Limited
$probeAction = New-ScheduledTaskAction -Execute 'C:\Users\14431\AppData\Local\Programs\Python\Python311\pythonw.exe' `
    -Argument '-B -X utf8 "E:\sss\小鲸鱼通道修复_20261102\核对桌面运行环境.py"' `
    -WorkingDirectory 'E:\sss\小鲸鱼通道修复_20261102'
$probeSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $probeName -Principal $probePrincipal -Action $probeAction -Settings $probeSettings | Out-Null
try {
    $probeBegin = Get-Date
    Start-ScheduledTask -TaskName $probeName
    for ($probeIndex = 0; $probeIndex -lt 30; $probeIndex++) {
        $probeOutput = Get-Item -LiteralPath 'E:\sss\小鲸鱼通道修复_20261102\桌面环境核对.local.json' -ErrorAction SilentlyContinue
        if ($probeOutput -and $probeOutput.LastWriteTime -ge $probeBegin) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $probeOutput -or $probeOutput.LastWriteTime -lt $probeBegin) { throw '本次核对未产生新证据' }
    $probeResult = Get-Content -LiteralPath $probeOutput.FullName -Raw | ConvertFrom-Json
    $probeResult | Select-Object '窗口站','桌面','令牌','原安全描述符控制','临时窗口站' | ConvertTo-Json -Depth 7
} finally {
    Unregister-ScheduledTask -TaskName $probeName -Confirm:$false
}
