param([string]$Source='C:\Users\pou\AppData\Local\Temp\router-watchdog-20261014.ps1')
$ErrorActionPreference='Stop'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$name='Oracova-KhadangWatchdog'
if(Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue){throw 'Existing task must be inspected and preserved; refusing overwrite'}
$root='C:\ProgramData\KhadangRouter'
$receipt=Get-Content "$root\release-startup-isolation-20261014\verified.json" -Raw|ConvertFrom-Json
if($receipt.code -ne (Get-FileHash "$root\bin\KhadangRouter.dll").Hash -or (Get-Service KhadangRouter).Status -ne 'Running'){throw 'Verified live release required'}
$target='C:\ProgramData\OracovaNativeRemote\router-watchdog-20261014.ps1'
if(Test-Path $target){throw 'New protected destination required'}
Copy-Item $Source $target
if((Get-FileHash $target).Hash -ne 'B69990052A673655099A5C11A962DE1CD9D43DF3B38358857330A2B9E39FB52A'){throw 'Watchdog changed'}
$acl=[Security.AccessControl.FileSecurity]::new();$acl.SetAccessRuleProtection($true,$false);$acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
foreach($sid in @('S-1-5-18','S-1-5-32-544')){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','Allow'))}
Set-Acl -LiteralPath $target -AclObject $acl
$wrapper='C:\ProgramData\OracovaNativeRemote\router-watchdog-task-20261014.ps1'
if(Test-Path $wrapper){throw 'New wrapper destination required'}
Copy-Item (Join-Path (Split-Path $Source) 'router-watchdog-task-20261014.ps1') $wrapper
if((Get-FileHash $wrapper).Hash -ne '9B984CF1BFD53FC23B2C053DA7977701D1D2AA8A008475882FC9F5047CCB2FED'){throw 'Wrapper changed'}
Set-Acl -LiteralPath $wrapper -AclObject $acl
$action=New-ScheduledTaskAction -Execute 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$wrapper+'"')
$triggers=@((New-ScheduledTaskTrigger -AtStartup),(New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)))
$principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -StartWhenAvailable
Register-ScheduledTask -TaskName $name -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Description 'Bounded reviewed router-only liveness recovery; preserves native custody and uncertainty'|Out-Null
Start-ScheduledTask $name
@{installed=$true;task=$name;existingStartupChanged=$false;nativeHostsRestarted=$false}|ConvertTo-Json -Compress
