# 只注册网页按需调用的固定验证副本入口，不设置任何自动触发器。
$ErrorActionPreference = 'Stop'
$taskName = '小鲸鱼验证副本手动启动'
$clientPath = 'E:\sss\小鲸鱼QQ兼容验证\Files\QQ.exe'
if (-not (Test-Path -LiteralPath $clientPath -PathType Leaf)) {
    throw '验证副本不存在，停止注册'
}
$existing = Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Output '按需启动任务已存在；后续部署脚本会核对完整配置，不自动覆盖。'
    exit 0
}
$userSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$principal = New-ScheduledTaskPrincipal -UserId $userSid -LogonType Interactive -RunLevel Limited
$action = New-ScheduledTaskAction -Execute $clientPath -WorkingDirectory 'E:\sss\小鲸鱼QQ兼容验证\Files'
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskPath '\' -TaskName $taskName -Principal $principal `
    -Action $action -Settings $settings -Description '仅在网页明确点击后启动获准验证副本；无定时、登录或开机触发；扫码由用户完成。' | Out-Null
Write-Output '普通用户桌面入口已注册；未启动QQ，未设置自动触发器。'
