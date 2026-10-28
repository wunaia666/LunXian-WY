# 将已完成任务的本地快照队列接入系统定时补推。
$ErrorActionPreference = 'Stop'
$python = 'C:\Users\14431\AppData\Local\Programs\Python\Python311\python.exe'
$script = 'E:\sss\tools\git-task-sync-20261028\publish_task.py'
$taskName = '任务完成代码自动补推'
$arguments = '"{0}" flush' -f $script
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory 'E:\sss'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description '仅补推已完成任务的代码快照，不扫描或提交未完成工作区。' -Force
