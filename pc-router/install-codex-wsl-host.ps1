param([Parameter(Mandatory=$true)][ValidatePattern('^[0-9A-Fa-f]{64}$')][string]$ExpectedSha256)
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or
 -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
 throw 'Reviewed PC administrator installation required'
}
$root='C:\ProgramData\OracovaNativeRemote';$runner=Join-Path $root 'codex-wsl-host.ps1'
# Prerequisites: the owner profile, reviewed observer package, and native CLI
# daemon package bootstrapped then pinned with `daemon update --from-cli --yes`.
# This installer does not run any native provider as SSH administrator/SYSTEM.
$task='Oracova-CodexWslRemote'
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
if((Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue) -or
 (Test-Path -LiteralPath 'C:\Users\pou\.native-remote\codex-wsl-status.json')){throw 'Existing WSL remote setup; inspect and merge, never overwrite'}
if(-not (Get-Acl $root).AreAccessRulesProtected -or
 (Get-Acl $root).GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $admin.Value -or
 (Get-Item $root).Attributes -band [IO.FileAttributes]::ReparsePoint -or
 (Get-Item $runner).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Literal protected code required'}
$acl=[Security.AccessControl.FileSecurity]::new();$acl.SetOwner($admin);$acl.SetAccessRuleProtection($true,$false)
foreach($sid in @($admin,$system)){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','Allow'))}
$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($owner,'ReadAndExecute','Allow'))
Set-Acl -LiteralPath $runner $acl
if((Get-FileHash $runner).Hash -ne $ExpectedSha256){throw 'Reviewed runner digest mismatch'}
$tokens=$null;$errors=$null
[Management.Automation.Language.Parser]::ParseFile($runner,[ref]$tokens,[ref]$errors)|Out-Null
if($errors.Count){throw 'Runner PowerShell parsing failed'}
$principal=New-ScheduledTaskPrincipal -UserId $owner.Value -LogonType Interactive -RunLevel Limited
$action=New-ScheduledTaskAction -Execute 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$runner+'"')
$logon=New-ScheduledTaskTrigger -AtLogOn -User $owner.Value
$repeat=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
# No automatic retry of launch failure; its evidence stays visible. A later
# supervisor run only starts a daemon whose native state explicitly is not up.
Register-ScheduledTask -TaskName $task -Action $action -Principal $principal -Trigger @($logon,$repeat) -Settings $settings|Out-Null
$scheduler=New-Object -ComObject Schedule.Service;$scheduler.Connect();$registered=$scheduler.GetFolder('\').GetTask($task)
$registered.SetSecurityDescriptor('O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)',0x10)
$security=[Security.AccessControl.RawSecurityDescriptor]::new($registered.GetSecurityDescriptor(7))
if($security.Owner.Value -ne $admin.Value -or -not ($security.ControlFlags -band [Security.AccessControl.ControlFlags]::DiscretionaryAclProtected)){
 throw 'Protected task owner/DACL required'
}
foreach($ace in $security.DiscretionaryAcl){if($ace.SecurityIdentifier.Value -notin @($admin.Value,$system.Value)){throw 'Untrusted task grant'}}
Start-ScheduledTask -TaskName $task
[Console]::WriteLine((@{task=$task;state=[string](Get-ScheduledTask -TaskName $task).State;
 owner='Interactive/Limited';existingWindowsSessionsChanged=$false;runnerSha256=$ExpectedSha256}|ConvertTo-Json -Compress))
