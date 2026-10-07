# Protected SYSTEM task, every minute + at boot. Fixed two-service allowlist.
# No reboot, privilege grant, routing/credential changes or broad process kill.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
if(-not [Security.Principal.WindowsIdentity]::GetCurrent().IsSystem){throw 'SYSTEM task required'}
$mt='C:\ProgramData\OracovaMTProto-2a2ae0dae7f749a2bcd664519271c88d'
$python='C:\ProgramData\OracovaVPN-20261003-FA9g4b\python\python.exe'
$statePath=Join-Path $PSScriptRoot 'watchdog-state.json'
$lock=$null
$phase='state-read'
try {
 $lock=[IO.File]::Open((Join-Path $PSScriptRoot 'watchdog.lock'),'OpenOrCreate','ReadWrite','None')
} catch [IO.IOException] {exit 0}
function Choose-Recovery([string]$Status,[bool]$LocalOk,[bool]$TelegramOk,[bool]$UpstreamOk,[int]$Failures,[double]$Age,[double]$SinceRestart){
 if($Status -eq 'Stopped'){return 'start'}
 if($Status -ne 'Running' -or $Age -lt 120){return 'wait'}
 if($TelegramOk){return 'healthy'}
 if($LocalOk -and -not $UpstreamOk){return 'network-outage'}
 if($Failures -ge 3 -and $SinceRestart -ge 300){return 'restart'}
 return 'suspect'
}
try {
 $state=@{}
 if(Test-Path $statePath){
  $loaded=Get-Content -LiteralPath $statePath -Raw|ConvertFrom-Json
  foreach($p in $loaded.services.psobject.Properties){$state[$p.Name]=$p.Value}
 }
 $rows=@{}
 foreach($name in @('OracovaMTProto','OracovaMTProto8443')){
  $phase='service-check'
  $now=[DateTime]::UtcNow
  $service=Get-CimInstance Win32_Service -Filter ('Name="'+$name+'"')
  if($null -eq $service -or $service.PathName -ne ('"'+$mt+'\ServiceHost.exe" '+$name) -or
     $service.StartName -ne 'NT AUTHORITY\LocalService' -or $service.StartMode -ne 'Auto'){throw 'Exact installed service required'}
  $last=$state[$name];$failures=0;$restarted=[DateTime]::MinValue
  if($last){$failures=[int]$last.failures;if($last.lastRestart){$restarted=[DateTime]::Parse($last.lastRestart).ToUniversalTime()}}
  $check=[pscustomobject]@{localAuthenticated=$false;telegram=$false;upstreamReachable=$false}
  $age=9999
  if($service.State -eq 'Running'){
   $phase='health-probe'
   $process=Get-Process -Id $service.ProcessId -ErrorAction Stop
   $age=($now-$process.StartTime.ToUniversalTime()).TotalSeconds
   $info=[Diagnostics.ProcessStartInfo]::new($python,('-I -B "'+(Join-Path $PSScriptRoot 'health_probe.py')+'" '+$name))
   $info.UseShellExecute=$false;$info.CreateNoWindow=$true;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
   $probe=[Diagnostics.Process]::Start($info)
   try {
    if(-not $probe.WaitForExit(22000)){$probe.Kill();throw 'Bounded health probe timed out'}
    $output=$probe.StandardOutput.ReadToEnd()
    if($probe.ExitCode -ne 0 -or $output.Length -gt 4096){throw 'Health probe failed; preserve service'}
    $check=$output|ConvertFrom-Json
    if($check.name -ne $name -or $null -eq $check.telegram -or $null -eq $check.localAuthenticated){throw 'Invalid health result'}
   } finally {$probe.Dispose()}
  }
  if($check.telegram){$failures=0}else{$failures++}
  $phase='recovery-decision'
  $action=Choose-Recovery $service.State $check.localAuthenticated $check.telegram $check.upstreamReachable $failures $age ($now-$restarted).TotalSeconds
  $errorType=$null
  try {
   if($action -eq 'restart'){
    try {Stop-Service -Name $name -ErrorAction Stop}catch{}
    (Get-Service $name).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(20))
   }
   if($action -in @('start','restart')){Start-Service -Name $name;$restarted=$now;$failures=0}
  } catch {$errorType=$_.Exception.GetType().Name}
  $rows[$name]=[pscustomobject]@{state=(Get-Service $name).Status.ToString();localAuthenticated=$check.localAuthenticated;
   telegram=$check.telegram;upstreamReachable=$check.upstreamReachable;failures=$failures;action=$action;
   lastRestart=if($restarted -ne [DateTime]::MinValue){$restarted.ToString('o')}else{$null};errorType=$errorType}
 }
 $phase='receipt-write'
 $log=Join-Path $PSScriptRoot 'watchdog.log'
 $receipt=[pscustomobject]@{at=[DateTime]::UtcNow.ToString('o');services=$rows}
 $json=$receipt|ConvertTo-Json -Depth 5 -Compress
 [IO.File]::WriteAllText($statePath+'.new',$json)
 # Windows PowerShell binds $null string arguments as empty strings. Supply
 # an explicit bounded backup path, otherwise the second run fails to persist
 # its failure count and a hung proxy would never reach the retry threshold.
 if(Test-Path $statePath){[IO.File]::Replace($statePath+'.new',$statePath,$statePath+'.previous')}else{[IO.File]::Move($statePath+'.new',$statePath)}
 if((Test-Path $log) -and (Get-Item $log).Length -gt 1048576){Move-Item $log ($log+'.1') -Force}
 [IO.File]::AppendAllText($log,$json+[Environment]::NewLine)
} catch {
 [pscustomobject]@{at=[DateTime]::UtcNow.ToString('o');phase=$phase;errorType=$_.Exception.GetType().Name;
  errorId=$_.FullyQualifiedErrorId;line=$_.InvocationInfo.ScriptLineNumber}|ConvertTo-Json -Compress|
  Set-Content -LiteralPath (Join-Path $PSScriptRoot 'watchdog-error.json') -Encoding UTF8
 throw
} finally {if($lock){$lock.Dispose()}}
