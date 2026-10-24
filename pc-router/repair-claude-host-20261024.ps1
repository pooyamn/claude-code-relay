param([ValidateSet('repair','verify')][string]$Phase='repair')
# Owner-approved repair of stale shared Claude custody. Never stop live workers.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$hostRoot='C:\ProgramData\KhadangClaudeHost';$native='C:\ProgramData\OracovaNativeRemote';$temp='C:\Users\pou\AppData\Local\Temp'
$release="$root\repair-claude-host-20261024"
$current='32E50A1F4199BF281BDE3BC71B0ACB94731DF0B9BC6981CD82002EF863261C25';$old='BA71E22CB633BCC4070EB832EC8E846F78A573F0D65FD164DBC1A6E86F9D00A2'
$policy='6271B521E9C069618384FD6632088C7FAF06FDD1CBCB8A7CBCDC36E77215192C'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed administrator required'}
$helper="$temp\deploy-switch-isolation-20261014.ps1"
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helpers changed'}
$a=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Unknown','Bindings','ExactTask','Fenced')){$d=$a.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true);if(-not $d){throw 'Missing helper'};. ([ScriptBlock]::Create($d.Extent.Text))}
LoadSql "$native\inspect-state.ps1" 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
function Status{[IO.File]::ReadAllText("$root\state\status.json")|ConvertFrom-Json}
function NoWorkers{
 $s=Status
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and ($_.nativeConnected -or $_.busy -or $_.pid -ne 0)}).Count -or @($s.nativeSessions|Where-Object {$_.binding.Runtime -eq 'windows' -and $_.busy}).Count){throw 'Only offline Claude workers and idle owned Windows work may be repaired'}
 # Read-only kernel process check, not an elevated WSL native launcher.
 $found=(& C:\Windows\System32\wsl.exe -d Ubuntu-24.04 -u pou --exec /usr/bin/pgrep -x claude)-join ''
 if($LASTEXITCODE -ne 1 -or $found){throw 'Live/unknown Claude process; no host stop permitted'}
}
function Restore($b){foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){(ExactTask $name).Enabled=[bool]$(if($name -like '*Startup'){$b.startup}else{$b.watchdog})}}
if($Phase -eq 'repair'){
 if(Test-Path $release){throw 'Existing repair: inspect, do not repeat'}
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $current -or (Get-FileHash "$hostRoot\bin\KhadangRouter.dll").Hash -ne $old -or (Get-FileHash "$root\config.json").Hash -ne $policy){throw 'Pinned tested router, old host and unchanged policy required'}
 $v=[IO.File]::ReadAllText("$root\release-reconciliation-20261024-v2\verified.json")|ConvertFrom-Json
 if($v.code -ne $current -or -not $v.unknownReceiptsPreserved){throw 'Accepted candidate evidence required'}
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangClaudeHost'"
 if($svc.StartName -ne 'LocalSystem' -or $svc.PathName -cne ('"'+$hostRoot+'\bin\KhadangRouter.exe" --claude-host-service')){throw 'Exact existing host service required'}
 NoWorkers
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 $b=@{startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled;bindings=(Bindings);hostPid=$svc.ProcessId;at=[DateTimeOffset]::UtcNow}
 Save "$release\before.json" $b
 try{
  foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $name;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
  NoWorkers
  $r=Get-Service KhadangRouter;$r.Stop();$r.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(50));Fenced
  NoWorkers
  $h=Get-Service KhadangClaudeHost;$h.Stop();$h.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30))
  Save "$release\original-unknown.json" @{receipts=(Unknown)}
  Move-Item "$hostRoot\bin" "$release\previous-host-bin";New-Item -ItemType Directory "$hostRoot\bin"|Out-Null;Protect "$hostRoot\bin" $true
  Copy-Item "$root\bin\*" "$hostRoot\bin";Protect "$hostRoot\bin" $true
  if((Get-FileHash "$hostRoot\bin\KhadangRouter.dll").Hash -ne $current -or (Bindings) -cne $b.bindings){throw 'Host copy/registry differs'}
  Save "$release\replaced.json" @{at=[DateTimeOffset]::UtcNow;oldHost=$old;newHost=$current;nativeWorkersStopped=0;bindingsChanged=0;inputsReplayed=0}
  Start-Service KhadangClaudeHost;Start-Service KhadangRouter
 }finally{Restore $b}
 @{phase='host-upgraded';nativeWorkersStopped=0;inputReplay=0;newHost=$current}|ConvertTo-Json -Compress;return
}
$b=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json
$s=Status;$targets=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -in @('7dc840b0-402f-451e-bc79-dadfb706d363','10ab0d8a-f31c-49ca-ab99-1a6152ae4ee2')})
if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $targets.Count -ne 2 -or @($targets|Where-Object {$_.held -or -not $_.nativeConnected -or $_.pid -eq 0 -or $_.admission.Blocking -ne 0}).Count -or (Bindings) -cne $b.bindings){throw 'Exact DUT and Mimic native recovery not confirmed'}
$u=[IO.File]::ReadAllText("$release\original-unknown.json")|ConvertFrom-Json
if((Unknown) -cne $u.receipts){throw 'Unknown receipts changed: inspect'}
$r=@{at=[DateTimeOffset]::UtcNow;targets=@($targets|Select-Object binding,pid,nativeConnected,held);bindingsPreserved=$true;unknownReceiptsPreserved=$true;inputReplay=0;nativeWorkersStopped=0}
Save "$release\verified.json" $r;$r|ConvertTo-Json -Depth 6 -Compress
