# Policy-only cutover: retain code, credentials and every existing delivery.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$root='C:\ProgramData\KhadangRouter'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed administrator deployment only'}
if((Get-FileHash "$root\config.json").Hash -ne '7E77ACA790FC5786C9737C93E67855EE5967C7D36FE364D1F3A41F83C874364A' -or
 (Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne '84AB5DEA4B368980A0754FB64D23F2ABBE0F63DCADA6EAFDB1F752E1A37E5690'){throw 'Reviewed current code/policy required'}
$service=Get-CimInstance Win32_Service|Where-Object Name -eq 'KhadangRouter'
if($service.State -ne 'Running' -or $service.StartName -ne 'LocalSystem' -or
 $service.PathName -ne '"C:\ProgramData\KhadangRouter\bin\KhadangRouter.exe" --service --config "C:\ProgramData\KhadangRouter\config.json"'){throw 'Exact current live service required'}
$task=Get-ScheduledTask -TaskName 'Oracova-KhadangStartup'
if($task.Actions.Count -ne 1 -or $task.Actions[0].Execute -ne 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -or
 $task.Actions[0].Arguments -ne '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\ProgramData\OracovaNativeRemote\router-startup.ps1"' -or
 $task.Principal.UserId -notin @('SYSTEM','NT AUTHORITY\SYSTEM','S-1-5-18') -or $task.State.ToString() -eq 'Disabled'){throw 'Exact enabled startup supervisor required'}
$raw=(. 'C:\ProgramData\OracovaNativeRemote\inspect-state.ps1') -join "`n"
$state=$raw|ConvertFrom-Json
if($state.service -ne 'Running' -or $state.status.unknown -ne 0 -or @($state.bindings).Count -ne 4){throw 'Existing healthy four-route service required'}
foreach($row in @($state.metadata|Where-Object key -like 'bubble/*')){
 $b=$row.value
 if($b.busy -or $b.held -or $b.sendUnknown -or @($b.pendingResponses).Count){throw 'Native work active or uncertain; no interruption or route change'}
}
$release=Join-Path $root ('release-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $release|Out-Null
$acl=[Security.AccessControl.DirectorySecurity]::new();$acl.SetAccessRuleProtection($true,$false)
$acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
foreach($sid in @('S-1-5-18','S-1-5-32-544')){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','ContainerInherit,ObjectInherit','None','Allow'))}
Set-Acl $release $acl
Copy-Item "$root\state\probe.json" (Join-Path $release 'previous-probe.json')
Copy-Item "$root\config.json" (Join-Path $release 'previous-config.json')
[IO.File]::WriteAllText((Join-Path $release 'startup-task-before.xml'),(Export-ScheduledTask -TaskName 'Oracova-KhadangStartup'),[Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText((Join-Path $release 'previous-service.json'),(@{path=$service.PathName;startMode=$service.StartMode}|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText((Join-Path $release 'startup-supervisor-before.json'),(@{task=$task.TaskName;wasEnabled=$true;restoreAfterMatchingLiveProbe=$true}|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
Disable-ScheduledTask -TaskName 'Oracova-KhadangStartup'|Out-Null
# Disabling a task does not terminate an instance that already started.
Stop-ScheduledTask -TaskName 'Oracova-KhadangStartup'
Stop-Service KhadangRouter
(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(20))
[ordered]@{phase='fenced-not-staged';recoveryDirectory=$release;service=(Get-Service KhadangRouter).Status.ToString();
 startup=(Get-ScheduledTask -TaskName 'Oracova-KhadangStartup').State.ToString();at=[DateTimeOffset]::UtcNow.ToString('o')}|ConvertTo-Json -Compress
