param([ValidateSet('Inspect','Apply')][string]$Mode='Inspect')
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
foreach($path in @($PSScriptRoot,(Join-Path $PSScriptRoot 'ShutdownGuard.cs'),(Join-Path $PSScriptRoot 'shutdown-guard-start.ps1'))){
 $item=Get-Item -LiteralPath $path;$acl=Get-Acl -LiteralPath $path
 if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $admin.Value){throw 'Sealed executable source required'}
 foreach($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])){
  if($rule.AccessControlType -eq 'Allow' -and $rule.IdentityReference.Value -notin @($admin.Value,'S-1-5-18') -and
   ([int]$rule.FileSystemRights -band 0xD0156)){throw 'Unprivileged code mutation denied'}
 }
}
$name='Oracova-ShutdownGuard';$old=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if($Mode -eq 'Inspect'){
 [pscustomobject]@{task=$name;exists=($null -ne $old);interactiveOwnerLoggedOn=(@(Get-Process explorer -ErrorAction SilentlyContinue).Count -gt 0)}|ConvertTo-Json -Compress;return
}
if($old){
 Export-ScheduledTask -TaskName $name|Out-File (Join-Path $PSScriptRoot 'shutdown-task-before.xml') -NoClobber -Encoding UTF8
 if($old.Principal.UserId -notin @($owner.Value,'pou','DESKTOP-8SO9HDK\pou') -or $old.Principal.RunLevel -ne 'Limited' -or
  @($old.Actions).Count -ne 1 -or $old.Actions[0].Arguments -notlike '*C:\ProgramData\OracovaMTProtoHealth-*'){throw 'Unexpected existing task; preserve'}
}
$exe=Join-Path $PSScriptRoot 'ShutdownGuard.exe'
if(Test-Path $exe){throw 'Fresh executable required'}
& 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe' /nologo /target:winexe /r:System.Windows.Forms.dll /r:System.Drawing.dll ('/out:'+$exe) (Join-Path $PSScriptRoot 'ShutdownGuard.cs')
if($LASTEXITCODE -ne 0){throw 'Shutdown guard compilation failed'}
$a=Get-Acl $exe;$a.SetOwner($admin);Set-Acl $exe $a
$test=Start-Process -FilePath $exe -ArgumentList '--self-test' -Wait -PassThru
if($test.ExitCode -ne 0){throw 'Shutdown guard policy tests failed'}
# Read/execute only: user has no WriteDAC or ability to replace SYSTEM code.
$a=Get-Acl $PSScriptRoot
$a.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($owner,'ReadAndExecute','ContainerInherit,ObjectInherit','None','Allow'))
Set-Acl -LiteralPath $PSScriptRoot -AclObject $a
$desktop='Registry::HKEY_USERS\'+$owner.Value+'\Control Panel\Desktop'
$autoEnd=Get-ItemProperty -LiteralPath $desktop -ErrorAction Stop
[pscustomobject]@{AutoEndTasks=$autoEnd.AutoEndTasks;appSha256=(Get-FileHash $exe).Hash}|ConvertTo-Json -Compress|Out-File (Join-Path $PSScriptRoot 'shutdown-before.json') -NoClobber -Encoding UTF8
if($autoEnd.AutoEndTasks -eq '1'){New-ItemProperty -LiteralPath $desktop -Name AutoEndTasks -Value '0' -PropertyType String -Force|Out-Null}
$principal=New-ScheduledTaskPrincipal -UserId $owner.Value -LogonType Interactive -RunLevel Limited
$action=New-ScheduledTaskAction -Execute 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -Argument ('-WindowStyle Hidden -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+(Join-Path $PSScriptRoot 'shutdown-guard-start.ps1')+'"')
$logon=New-ScheduledTaskTrigger -AtLogOn -User $owner.Value
$repeat=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval ([TimeSpan]::FromMinutes(1))
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval ([TimeSpan]::FromMinutes(1))
Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Trigger @($logon,$repeat) -Settings $settings -Force|Out-Null
Start-ScheduledTask -TaskName $name
[pscustomobject]@{task=$name;criticalShutdownBlocked=$false;ordinaryShutdownVeto=$true;forcedRestart=$false;interactiveOwnerOnly=$true;realShutdownTested=$false}|ConvertTo-Json -Compress
