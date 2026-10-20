param([switch]$SelfTest)
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'

function Get-RecentWatchdogAttempts($Prior,[DateTimeOffset]$Now) {
 if($null -eq $Prior -or $null -eq $Prior.attempts){return}
 foreach($attempt in $Prior.attempts){
  if($null -ne $attempt -and [DateTimeOffset]$attempt -gt $Now.AddMinutes(-10)){$attempt}
 }
}
function Save-WatchdogRecord([string]$File,[string]$Record) {
 $tmp=$File+'.new';[IO.File]::WriteAllText($tmp,$Record,[Text.UTF8Encoding]::new($false))
 # Windows PowerShell converts plain $null to an empty backup filename.
 if(Test-Path $File){[IO.File]::Replace($tmp,$File,[System.Management.Automation.Language.NullString]::Value)}else{[IO.File]::Move($tmp,$File)}
}

# Pure decision function: no processes, credentials, files or native input.
function Get-RouterWatchdogAction([hashtable]$Snapshot) {
 if($Snapshot.service -notin @('Stopped','Running')){return 'Wait'}
 if($Snapshot.recentAttempts -ge 3){return 'Cooldown'}
 if($Snapshot.service -eq 'Stopped'){return 'Start'}
 if($Snapshot.processAgeSeconds -lt 180){return 'Wait'}
 if($Snapshot.statusAgeSeconds -le 90 -and $Snapshot.pollAgeSeconds -le 120 -and $Snapshot.nativeHealthy -ne $false){return 'Healthy'}
 if($Snapshot.restartSafe -eq $false){return 'WaitForOwnedWork'}
 if($Snapshot.consecutiveBad -lt 2){return 'Observe'}
 return 'RestartRouterOnly'
}
if($SelfTest){
 $tests=0
 function Check($Expected,[hashtable]$S){$script:tests++;if((Get-RouterWatchdogAction $S) -ne $Expected){throw 'Watchdog decision regression'}}
 $healthy=@{service='Running';recentAttempts=0;processAgeSeconds=500;statusAgeSeconds=1;pollAgeSeconds=30;consecutiveBad=0}
 Check 'Healthy' $healthy
 $now=[DateTimeOffset]::UtcNow
 foreach($prior in @($null,@{},@{attempts=@()},@{attempts=@($null,$now.AddMinutes(-11).ToString('o'))})){
  $tests++;if(@(Get-RecentWatchdogAttempts $prior $now).Count -ne 0){throw 'First-run watchdog budget regression'}
 }
 $tests++;if(@(Get-RecentWatchdogAttempts @{attempts=@($now.ToString('o'))} $now).Count -ne 1){throw 'Recent attempt budget regression'}
 $fixture=Join-Path ([IO.Path]::GetTempPath()) ('watchdog-fixture-'+[Guid]::NewGuid().ToString('N')+'.json')
 try {
  foreach($text in @('{"attempts":[]}','{"attempts":["retained"]}')){
   Save-WatchdogRecord $fixture $text;$tests++
   if([IO.File]::ReadAllText($fixture) -cne $text){throw 'Atomic watchdog write regression'}
  }
 }finally{if(Test-Path $fixture){Remove-Item -LiteralPath $fixture};if(Test-Path ($fixture+'.new')){Remove-Item -LiteralPath ($fixture+'.new')}}
 $s=$healthy.Clone();$s.service='Stopped';Check 'Start' $s
 $s=$healthy.Clone();$s.service='StartPending';Check 'Wait' $s
 $s=$healthy.Clone();$s.processAgeSeconds=20;$s.statusAgeSeconds=500;Check 'Wait' $s
 $s=$healthy.Clone();$s.statusAgeSeconds=95;$s.consecutiveBad=1;Check 'Observe' $s
 $s.consecutiveBad=2;Check 'RestartRouterOnly' $s
 $s=$healthy.Clone();$s.pollAgeSeconds=125;$s.consecutiveBad=2;Check 'RestartRouterOnly' $s
 $s=$healthy.Clone();$s.recentAttempts=3;Check 'Cooldown' $s
 $s.service='Stopped';Check 'Cooldown' $s
 $s=$healthy.Clone();$s.pollAgeSeconds=60;Check 'Healthy' $s
 $s=$healthy.Clone();$s.nativeHealthy=$false;$s.consecutiveBad=1;Check 'Observe' $s
 $s.consecutiveBad=2;Check 'RestartRouterOnly' $s
 $s=$healthy.Clone();$s.nativeHealthy=$true;Check 'Healthy' $s
 $s=$healthy.Clone();$s.nativeHealthy=$false;$s.processAgeSeconds=20;$s.consecutiveBad=2;Check 'Wait' $s
 $s=$healthy.Clone();$s.nativeHealthy=$false;$s.recentAttempts=3;Check 'Cooldown' $s
 $s=$healthy.Clone();$s.nativeHealthy=$false;$s.restartSafe=$false;$s.consecutiveBad=2;Check 'WaitForOwnedWork' $s
 $s=$healthy.Clone();$s.restartSafe=$false;Check 'Healthy' $s
 $s=$healthy.Clone();$s.nativeHealthy=$false;$s.restartSafe=$true;$s.consecutiveBad=2;Check 'RestartRouterOnly' $s
 [Console]::WriteLine("Passed $tests watchdog decisions (no services/network/models)");return
}

$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not $identity.IsSystem -or [Diagnostics.Process]::GetCurrentProcess().SessionId -ne 0){throw 'SYSTEM session-zero watchdog required'}
$lease=$null
try{
 try{$lease=[IO.File]::Open("$root\state\watchdog.lock",'OpenOrCreate','ReadWrite','None')}catch [IO.IOException]{return}
 $service=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $expected='"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"'
 if(-not $service -or $service.StartName -ne 'LocalSystem' -or $service.PathName -cne $expected -or $service.StartMode -ne 'Manual'){throw 'Unexpected service configuration; no recovery'}
 $proof=Get-Content "$root\state\probe.json" -Raw -Encoding UTF8|ConvertFrom-Json
 if(-not $proof.verified -or -not $proof.credentialAndCodeDenied -or
  (Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $proof.routerSha256 -or
  (Get-FileHash "$root\config.json").Hash -ne $proof.policySha256){throw 'Unreviewed code/policy; no recovery'}
 $startup="$native\router-startup.ps1"
 if((Get-FileHash $startup).Hash -ne '2B4692B2F9DDD8B3F73A42186546D3B892326C32A319FF816586AC3ED94D5665'){throw 'Startup supervisor changed; no recovery'}
 $now=[DateTimeOffset]::UtcNow;$file="$root\state\watchdog.json"
 $prior=if(Test-Path $file){Get-Content $file -Raw -Encoding UTF8|ConvertFrom-Json}else{$null}
 $attempts=@(Get-RecentWatchdogAttempts $prior $now)
 $statusAge=1e9;$pollAge=1e9;$processAge=0;$nativeHealthy=$null;$restartSafe=$null
 if($service.State -eq 'Running'){
  $process=Get-Process -Id $service.ProcessId -ErrorAction Stop
  $processAge=($now-[DateTimeOffset]$process.StartTime).TotalSeconds
  # A concurrent status write or missing heartbeat is an observation, not
  # immediate permission to restart. Require two consecutive bad cycles.
  try{$s=Get-Content "$root\state\status.json" -Raw -Encoding UTF8|ConvertFrom-Json
   $statusAge=($now-[DateTimeOffset]$s.at).TotalSeconds
   $pollAge=($now-[DateTimeOffset]$s.lastPollAttempt).TotalSeconds
   # Backward-compatible absence during rollout; an advertised false or
   # malformed health value cannot be hidden by fresh polling/PID metadata.
   if($s.PSObject.Properties['nativeTransportHealthy']){$nativeHealthy=$s.nativeTransportHealthy -is [bool] -and $s.nativeTransportHealthy}
   if($s.PSObject.Properties['backgroundHealthy'] -and ($s.backgroundHealthy -isnot [bool] -or -not $s.backgroundHealthy)){$nativeHealthy=$false}
   if($s.PSObject.Properties['nativeObserverRestartSafe']){$restartSafe=$s.nativeObserverRestartSafe -is [bool] -and $s.nativeObserverRestartSafe}
   if($statusAge -lt -30 -or $pollAge -lt -30){$statusAge=1e9;$pollAge=1e9}
  }catch{$statusAge=1e9;$pollAge=1e9}
 }
 $bad=if($statusAge -gt 90 -or $pollAge -gt 120 -or $nativeHealthy -eq $false){1+[int]$prior.consecutiveBad}else{0}
 $action=Get-RouterWatchdogAction @{service=$service.State;recentAttempts=$attempts.Count;processAgeSeconds=$processAge;statusAgeSeconds=$statusAge;pollAgeSeconds=$pollAge;nativeHealthy=$nativeHealthy;restartSafe=$restartSafe;consecutiveBad=$bad}
 if($action -in @('Start','RestartRouterOnly')){$attempts+=($now.ToString('o'))}
 # Commit the bounded attempt BEFORE the external lifecycle operation.
 $record=@{at=$now.ToString('o');action=$action;attempts=$attempts;consecutiveBad=$bad;service=$service.State;statusAgeSeconds=$statusAge;pollAgeSeconds=$pollAge;nativeHealthy=$nativeHealthy;restartSafe=$restartSafe}|ConvertTo-Json -Compress
 Save-WatchdogRecord $file $record
 if($action -eq 'RestartRouterOnly'){
  # Never stop the independent Claude custody host or the Codex daemon;
  # never alter, confirm, clear or replay delivery journals.
  Stop-Service KhadangRouter
  (Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30))
 }
 if($action -in @('Start','RestartRouterOnly')){& $startup}
}finally{if($lease){$lease.Dispose()}}
