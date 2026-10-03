param([Parameter(Mandatory=$true)][ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$ExpectedSha256)
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\OracovaNativeRemote';$name='Oracova-KhadangStartup';$script=Join-Path $root 'router-startup.ps1'
$principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Administrator-reviewed install required'}
if(Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue){throw 'Existing startup task: inspect and merge'}
if((Get-FileHash $script).Hash -ne $ExpectedSha256 -or ((Get-Item $script).Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Reviewed protected startup script required'}
$acl=Get-Acl $root
if(-not $acl.AreAccessRulesProtected -or $acl.Owner -notmatch 'Administrators$'){throw 'Expected administrator-owned protected root'}
$action=New-ScheduledTaskAction -Execute 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$script+'"')
$boot=New-ScheduledTaskTrigger -AtStartup
$logon=New-ScheduledTaskTrigger -AtLogOn -User 'DESKTOP-8SO9HDK\pou'
$repeat=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval ([TimeSpan]::FromMinutes(1))
$system=New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::FromMinutes(1))
Register-ScheduledTask -TaskName $name -Action $action -Trigger @($boot,$logon,$repeat) -Principal $system -Settings $settings | Out-Null
Start-ScheduledTask -TaskName $name
[Console]::WriteLine('Owner-ready startup task installed; live service and native remotes untouched')
