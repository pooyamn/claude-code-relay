param([ValidateSet('prepare','stage','finish-stage','finish-installed-stage','probe','activate','verify','reattach')][string]$Phase,[Parameter(Mandatory=$true)][string]$ManifestSha256)
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$hostRoot='C:\ProgramData\KhadangClaudeHost';$native='C:\ProgramData\OracovaNativeRemote';$temp='C:\Users\pou\AppData\Local\Temp'
$release=$root+'\release-claude-pipe-20261107-v3';$incoming=$temp+'\router-claude-pipe-20261107'
$oldCode='7CB14B08DB72972FB2A35CF9CCB13DA60906CAE865DDBECB3BC486092B54C7F2';$oldHost='7CB14B08DB72972FB2A35CF9CCB13DA60906CAE865DDBECB3BC486092B54C7F2';$oldPolicy='F41B5F544EE550460788BF24B21A907A78CB6DDACB0CD0194B847A95F6C3EB0C'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$helper=$temp+'\deploy-switch-isolation-20261014.ps1'
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helpers changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Bindings','Unknown','HostIdentity','ExactTask')){
 $d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true);. ([scriptblock]::Create($d.Extent.Text))
}
LoadSql ($native+'\inspect-state.ps1') 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
function Status{[IO.File]::ReadAllText($root+'\state\status.json')|ConvertFrom-Json}
function Original{
 if((Get-FileHash ($root+'\bin\KhadangRouter.dll')).Hash -ne $oldCode -or (Get-FileHash ($hostRoot+'\bin\KhadangRouter.dll')).Hash -ne $oldHost -or
  (Get-FileHash ($root+'\config.json')).Hash -ne $oldPolicy){throw 'Reviewed original deployment changed'}
}
function RestoreSupervisors($b){foreach($n in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){(ExactTask $n).Enabled=[bool]$(if($n -like '*Startup'){$b.startup}else{$b.watchdog})}}
function StartObserver([bool]$Probe=$false){
 $mode=if($Probe){'--probe-service'}else{'--service'}
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" '+$mode+' --config "'+$root+'\config.json"');StartMode='Manual'}
 if($r.ReturnValue){throw 'Service path update failed'};Start-Service KhadangRouter
}
function Stopped{
 if((Get-Service KhadangRouter).Status -ne 'Stopped' -or (ExactTask 'Oracova-KhadangStartup').Enabled -or (ExactTask 'Oracova-KhadangWatchdog').Enabled){throw 'Observer must be fenced'}
}
function CheckManifest($path){if((Get-FileHash $path).Hash -ne $ManifestSha256){throw 'Exact reviewed manifest required'};[IO.File]::ReadAllText($path)|ConvertFrom-Json}
function InstallWatchdog{
 $path=$native+'\router-watchdog-20261014.ps1';$wrapper=$native+'\router-watchdog-task-20261014.ps1'
 if((Get-FileHash $path).Hash -ne '057093FD58A701422AE7EDE4BA0022717C3702288A46C97CF57AA0989EDD6382' -or
  (Get-FileHash $wrapper).Hash -ne '9B984CF1BFD53FC23B2C053DA7977701D1D2AA8A008475882FC9F5047CCB2FED'){throw 'Reviewed existing watchdog/wrapper changed'}
 [xml]$task=(ExactTask 'Oracova-KhadangWatchdog').Xml
 if($task.Task.Actions.Exec.Arguments -cne ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$wrapper+'"')){throw 'Watchdog task points elsewhere'}
 Copy-Item $path ($release+'\previous-watchdog.ps1');Protect ($release+'\previous-watchdog.ps1')
 Copy-Item ($release+'\router-watchdog.ps1') $path;Protect $path
 if((Get-FileHash $path).Hash -ne $m.watchdog){throw 'Installed watchdog differs'}
}
function WorkerReader($pin){
 if($pin -notmatch '^[a-f0-9-]{36}$'){throw 'Exact native ID required'}
 $class='PipeRead'+$pin.Replace('-','');$db=$hostRoot+'\state\'+$pin+'\broker.db'
 if(-not ($class -as [type])){
  $a=[Management.Automation.Language.Parser]::ParseFile(($native+'\inspect-state.ps1'),[ref]$null,[ref]$null)
  $d=$a.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type'},$true)
  . ([scriptblock]::Create($d.Extent.Text.Replace('RouterReceipts',$class).Replace($root+'\state\router.db',$db)))
 }
 return ($class -as [type])
}
function IdleSettled{
 $s=Status;$targets=@($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude'})
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddSeconds(-30) -or -not $s.backgroundHealthy -or $targets.Count -ne 9 -or
  @($targets|Where-Object {$_.busy -or $_.held -or -not $_.ready -or -not $_.nativeConnected -or $_.pid -eq 0 -or $_.admission.Blocking -ne 0}).Count -or
  @($s.nativeSessions|Where-Object {$_.binding.Runtime -eq 'windows' -and $_.busy}).Count -or
  [RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('received','dispatching','unknown')").Length -or
  [RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'All nine Claude workers must be idle and settled; never stop active or uncertain work'}
 $a=[Management.Automation.Language.Parser]::ParseFile(($native+'\inspect-state.ps1'),[ref]$null,[ref]$null)
 $d=$a.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type'},$true)
 foreach($target in $targets){
  $pin=$target.binding.ThreadId;if($pin -notmatch '^[a-f0-9-]{36}$'){throw 'Exact native ID required'}
  $class='PipeRead'+$pin.Replace('-','');$db=$hostRoot+'\state\'+$pin+'\broker.db'
  if(-not ($class -as [type])){. ([scriptblock]::Create($d.Extent.Text.Replace('RouterReceipts',$class).Replace($root+'\state\router.db',$db)))}
  $reader=$class -as [type]
  if($reader::Read("SELECT 1 FROM operations WHERE status IN ('attempting','unknown') AND kind<>'telegram/editMessageText' LIMIT 1").Length -or
   $reader::Read("SELECT 1 FROM broker_calls WHERE status IN ('attempting','unknown','submitted') LIMIT 1").Length -or
   $reader::Read("SELECT 1 FROM broker_replies WHERE status IN ('attempting','unknown','submitted') LIMIT 1").Length -or
   $reader::Read("SELECT 1 FROM broker_requests WHERE status IN ('pending','replying','reply-submitted') LIMIT 1").Length -or
   $reader::Read("SELECT 1 FROM meta WHERE key LIKE 'claude/request/$pin/%' AND json_extract(value,'$.status')='pending' LIMIT 1").Length){throw 'Private native question/action is unsettled; no host update'}
 }
 return $s
}
if($Phase -eq 'prepare'){
 Original;if(Test-Path $release){throw 'Retained release exists: inspect, never repeat'}
 $m=CheckManifest ($temp+'\router-claude-pipe-20261107.manifest.json')
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 Copy-Item ($temp+'\router-claude-pipe-20261107.manifest.json') ($release+'\manifest.json');Protect ($release+'\manifest.json')
 New-Item -ItemType Directory ($release+'\candidate')|Out-Null;Protect ($release+'\candidate') $true
 foreach($f in $m.files){
  if($f.name -notmatch '^[A-Za-z0-9._-]+$' -or $f.sha256 -notmatch '^[A-Fa-f0-9]{64}$'){throw 'Invalid file entry'}
  $from=Join-Path $incoming $f.name;$to=Join-Path ($release+'\candidate') $f.name
  if((Get-FileHash $from).Hash -ne $f.sha256 -or (Get-Item $from).Length -ne $f.bytes){throw 'Candidate changed'}
  Copy-Item $from $to;Protect $to;if((Get-FileHash $to).Hash -ne $f.sha256){throw 'Sealed candidate differs'}
 }
 if((Get-FileHash ($temp+'\router-watchdog-pipe-20261107.ps1')).Hash -ne $m.watchdog){throw 'Reviewed watchdog changed'}
 Copy-Item ($temp+'\router-watchdog-pipe-20261107.ps1') ($release+'\router-watchdog.ps1');Protect ($release+'\router-watchdog.ps1')
 New-Item -ItemType Directory ($release+'\gate')|Out-Null;Protect ($release+'\gate') $true
 foreach($f in $m.gate){
  if($f.name -notmatch '^[A-Za-z0-9._-]+\.ps1$' -or $f.sha256 -notmatch '^[A-Fa-f0-9]{64}$'){throw 'Invalid gate file'}
  $from=Join-Path ($temp+'\router-claude-pipe-gate-20261107') $f.name;$to=Join-Path ($release+'\gate') $f.name
  if((Get-FileHash $from).Hash -ne $f.sha256){throw 'Reviewed release gate changed'}
  Copy-Item $from $to;Protect $to;if((Get-FileHash $to).Hash -ne $f.sha256){throw 'Sealed gate differs'}
 }
 # Process-local script execution only; machine/user execution policies do not
 # change. The actual shared gate runs against the sealed target artifact.
 $out=(& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File ($release+'\gate\validate-release.ps1') -CandidateDirectory ($release+'\candidate'))-join "`n"
 Save ($release+'\tests.json') @{releaseGate=$out;exit=$LASTEXITCODE}
 if($LASTEXITCODE -or $out -notmatch 'Release validation passed; router SHA256:'){throw "Sealed Windows release gate failed: $out"}
 Save ($release+'\prepared.json') @{at=[DateTimeOffset]::UtcNow;code=$m.code;manifest=$ManifestSha256}
 $out;return
}
$m=CheckManifest ($release+'\manifest.json')
if($Phase -in @('stage','finish-stage')){
 Original;$null=[IO.File]::ReadAllText($release+'\prepared.json')
 if($Phase -eq 'stage'){
  if(Test-Path ($release+'\before.json')){throw 'Stage already attempted'}
  $s=IdleSettled
  $b=@{at=[DateTimeOffset]::UtcNow;startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled;bindings=(Bindings);unknown=(Unknown);nativePid=$s.nativeLinuxPid;claudeBindings=@($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude'}|ForEach-Object {$_.binding})}
  Save ($release+'\before.json') $b
 }else{
  Stopped;$b=[IO.File]::ReadAllText($release+'\before.json')|ConvertFrom-Json
  if((Get-Service KhadangClaudeHost).Status -ne 'Stopped' -or (Test-Path ($release+'\staged.json')) -or
   (Test-Path ($release+'\previous-router-bin')) -or (Test-Path ($release+'\previous-host-bin')) -or
   @($b.claudeBindings).Count -ne 9 -or (Bindings) -cne $b.bindings -or (Unknown) -cne $b.unknown -or
   [RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('received','dispatching','unknown')").Length -or
   [RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Only exact pre-copy interrupted stage with stopped custody may continue'}
  $live=(& C:\Windows\System32\wsl.exe -d Ubuntu-24.04 -u pou --exec /usr/bin/pgrep -x claude)-join ''
  if($LASTEXITCODE -ne 1 -or $live){throw 'Do not replace a live native owner'}
  Save ($release+'\stage-continuation.json') @{at=[DateTimeOffset]::UtcNow;originalArtifactsUnchanged=$true;nativeOwnersAbsent=$true;bindingsPreserved=$true;unknownPreserved=$true;inputReplay=0}
 }
 $installed=[IO.File]::ReadAllText($hostRoot+'\installed.json')|ConvertFrom-Json
 if($installed.dll -ne $oldHost -or $installed.exe -ne (Get-FileHash ($hostRoot+'\bin\KhadangRouter.exe')).Hash){throw 'Original host attestation mismatch'}
 try{
  foreach($n in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $n;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
  if($Phase -eq 'stage'){$null=IdleSettled;$svc=Get-Service KhadangRouter;$svc.Stop();$svc.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(45))};Stopped
  if((Bindings) -cne $b.bindings -or (Unknown) -cne $b.unknown){throw 'Custody changed during stop'}
  # Recheck after ingress/handlers are stopped, not only a pre-stop heartbeat.
  foreach($binding in $b.claudeBindings){
   $pin=$binding.ThreadId;$reader=WorkerReader $pin
   $bubble=[RouterReceipts]::Read("SELECT value FROM meta WHERE key='bubble/$pin'")[0][0]|ConvertFrom-Json
   $last=$reader::Read("SELECT frame FROM broker_events WHERE epoch=(SELECT json_extract(value,'$.epoch') FROM meta WHERE key='broker/current-epoch') AND json_extract(frame,'$.type')='system' AND json_extract(frame,'$.subtype')='session_state_changed' ORDER BY position DESC LIMIT 1")
   if($bubble.busy -or $bubble.held -or $bubble.claudeState -ne 'idle' -or
    ($last.Length -and ($last[0][0]|ConvertFrom-Json).state -ne 'idle') -or
    $reader::Read("SELECT 1 FROM broker_calls WHERE status IN ('attempting','unknown','submitted') LIMIT 1").Length -or
    $reader::Read("SELECT 1 FROM meta WHERE key LIKE 'claude/request/$pin/%' AND json_extract(value,'$.status')='pending' LIMIT 1").Length){throw 'Work arrived during maintenance fence; do not stop the native host'}
  }
  # The OLD buggy host may already have exited on observer EOF. This phase
  # deliberately updates idle custody once; an already-stopped host is safe.
  if((Get-Service KhadangClaudeHost).Status -ne 'Stopped'){
   try{Stop-Service KhadangClaudeHost}catch{(Get-Service KhadangClaudeHost).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30))}
  }
  (Get-Service KhadangClaudeHost).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30))
  Copy-Item ($root+'\config.json') ($release+'\previous-config.json');Protect ($release+'\previous-config.json')
  Copy-Item ($root+'\state\probe.json') ($release+'\previous-probe.json');Protect ($release+'\previous-probe.json')
  Copy-Item ($hostRoot+'\installed.json') ($release+'\previous-installed.json');Protect ($release+'\previous-installed.json')
  foreach($entry in @(@{root=$root;backup='previous-router-bin'},@{root=$hostRoot;backup='previous-host-bin'})){
   Move-Item ($entry.root+'\bin') ($release+'\'+$entry.backup)
   New-Item -ItemType Directory ($entry.root+'\bin')|Out-Null;Protect ($entry.root+'\bin') $true
   foreach($f in $m.files){Copy-Item (Join-Path ($release+'\candidate') $f.name) (Join-Path ($entry.root+'\bin') $f.name);Protect (Join-Path ($entry.root+'\bin') $f.name)}
  }
  $installed.dll=$m.code;$installed.exe=(Get-FileHash ($hostRoot+'\bin\KhadangRouter.exe')).Hash;$installed.generation='claude-pipe-20261107';$installed.at=[DateTimeOffset]::UtcNow.ToString('o')
  Save ($hostRoot+'\installed.json.reviewed') $installed
  [IO.File]::Replace($hostRoot+'\installed.json.reviewed',$hostRoot+'\installed.json',[System.Management.Automation.Language.NullString]::Value)
  InstallWatchdog
  Save ($release+'\staged.json') @{at=[DateTimeOffset]::UtcNow;code=$m.code;policy=(Get-FileHash ($root+'\config.json')).Hash}
 }catch{RestoreSupervisors $b;throw}
 'STAGED; nine proven idle workers stopped once for host update; no history/input changes';return
}
$b=[IO.File]::ReadAllText($release+'\before.json')|ConvertFrom-Json
if($Phase -eq 'finish-installed-stage'){
 Stopped
 if((Get-Service KhadangClaudeHost).Status -ne 'Stopped' -or (Test-Path ($release+'\staged.json')) -or
  (Bindings) -cne $b.bindings -or (Unknown) -cne $b.unknown -or (Get-FileHash ($root+'\config.json')).Hash -ne $oldPolicy -or
  (Get-FileHash ($release+'\previous-router-bin\KhadangRouter.dll')).Hash -ne $oldCode -or
  (Get-FileHash ($release+'\previous-host-bin\KhadangRouter.dll')).Hash -ne $oldHost){throw 'Exact interrupted installed stage required'}
 foreach($entry in @($root,$hostRoot)){foreach($f in $m.files){if((Get-FileHash (Join-Path ($entry+'\bin') $f.name)).Hash -ne $f.sha256){throw 'Installed artifact differs'}}}
 $installed=[IO.File]::ReadAllText($hostRoot+'\installed.json')|ConvertFrom-Json
 if($installed.dll -ne $m.code -or $installed.exe -ne (Get-FileHash ($hostRoot+'\bin\KhadangRouter.exe')).Hash){throw 'Host manifest differs'}
 InstallWatchdog
 Save ($release+'\staged.json') @{at=[DateTimeOffset]::UtcNow;code=$m.code;policy=$oldPolicy;continuation='verified installed artifacts and preserved task wrapper'}
 'STAGED: verified existing installed artifacts; no native launches or receipt changes';return
}
$stage=[IO.File]::ReadAllText($release+'\staged.json')|ConvertFrom-Json
if((Get-FileHash ($root+'\bin\KhadangRouter.dll')).Hash -ne $m.code -or (Get-FileHash ($hostRoot+'\bin\KhadangRouter.dll')).Hash -ne $m.code -or
 (Get-FileHash ($root+'\config.json')).Hash -ne $stage.policy){throw 'Staged artifacts changed'}
if($Phase -eq 'probe'){
 Stopped;StartObserver $true;$end=[DateTimeOffset]::UtcNow.AddSeconds(55)
 do{$proof=[IO.File]::ReadAllText($root+'\state\probe.json')|ConvertFrom-Json;if($proof.routerSha256 -eq $m.code -and $proof.policySha256 -eq $stage.policy -and [DateTimeOffset]$proof.testedAt -gt [DateTimeOffset]$stage.at){break};Start-Sleep -Milliseconds 500}while([DateTimeOffset]::UtcNow -lt $end)
 $svc=Get-Service KhadangRouter;$svc.Stop();$svc.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Stopped
 if(-not $proof.verified -or -not $proof.credentialAndCodeDenied -or -not $proof.nativeWindowsSandboxVerified -or -not $proof.nativeLinuxCommandOwnerVerified -or
  $proof.modelInference -or $proof.telegramPolling -or $proof.routerSha256 -ne $m.code -or $proof.policySha256 -ne $stage.policy -or [DateTimeOffset]$proof.testedAt -le [DateTimeOffset]$stage.at){throw 'Fresh SYSTEM denial/owner proof failed'}
 Save ($release+'\generic-proof.json') $proof
 $prior=[IO.File]::ReadAllText($release+'\previous-probe.json')|ConvertFrom-Json
 foreach($field in @('nativeLinuxClaudeLaunchVerified','nativeLinuxClaudeToolOwnerVerified','nativeLinuxClaudeContinuityVerified','nativeLinuxClaudeAcceptance')){if($prior.PSObject.Properties[$field]){$proof|Add-Member $field $prior.$field -Force}}
 $proof|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Same native executable, connector, policy, account, exact IDs and least-owner launch contract; pipe changes require fresh live reattachment verification';liveRecoveryClaimed=$false} -Force
 Save ($root+'\state\probe.json') $proof;Save ($release+'\accepted.json') @{at=[DateTimeOffset]::UtcNow;code=$m.code;policy=$stage.policy}
 'FRESH SECURITY PROBE PASSED';return
}
if($Phase -eq 'activate'){
 Stopped;$null=[IO.File]::ReadAllText($release+'\accepted.json')
 try{if((Get-Service KhadangClaudeHost).Status -ne 'Running'){Start-Service KhadangClaudeHost};StartObserver}finally{RestoreSupervisors $b}
 Save ($release+'\activated.json') @{at=[DateTimeOffset]::UtcNow};'ACTIVATED';return
}
if($Phase -eq 'reattach'){
 $baseline=IdleSettled;$hostBefore=HostIdentity;$pids=@{}
 foreach($t in @($baseline.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude'})){$pids[$t.binding.ThreadId]=$t.pid}
 $taskState=@{startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled}
 Save ($release+'\reattach-before.json') @{at=$baseline.at;host=$hostBefore;pids=$pids}
 try{
  foreach($n in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $n;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
  # Close real hub AND worker clients, retaining the exact custody host.
  for($cycle=1;$cycle -le 3;$cycle++){
   $null=IdleSettled;$svc=Get-Service KhadangRouter;$svc.Stop();$svc.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(45))
   if((Get-Service KhadangClaudeHost).Status -ne 'Running' -or (HostIdentity) -cne $hostBefore){throw 'Observer EOF terminated independent custody'}
   $startedAt=[DateTimeOffset]::UtcNow;StartObserver;$deadline=[DateTimeOffset]::UtcNow.AddSeconds(90)
   do{
    Start-Sleep -Milliseconds 500;$after=Status
    $claude=@($after.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude'})
    $ready=[DateTimeOffset]$after.at -ge $startedAt -and $claude.Count -eq 9 -and
     -not @($claude|Where-Object {-not $_.nativeConnected -or $_.held -or -not $_.ready}).Count
   }while(-not $ready -and [DateTimeOffset]::UtcNow -lt $deadline)
   if(-not $ready -or (HostIdentity) -cne $hostBefore -or
    @($claude|Where-Object {$pids[$_.binding.ThreadId] -ne $_.pid}).Count -or
    $after.nativeLinuxPid -ne $b.nativePid -or (Bindings) -cne $b.bindings -or (Unknown) -cne $b.unknown){throw 'Same-owner reattachment failed; preserve evidence, never replay'}
   Save ($release+'\reattach-cycle-'+$cycle+'.json') @{at=$after.at;hostPreserved=$true;allNineNativePidsPreserved=$true;bindingsPreserved=$true;unknownPreserved=$true;inputReplay=0}
   $baseline=$after
  }
 }finally{RestoreSupervisors $taskState}
 'PASS: three real observer restarts; host and all nine native PIDs preserved';return
}
$s=Status;$targets=@($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude'})
if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddSeconds(-30) -or -not $s.backgroundHealthy -or -not $s.nativeTransportHealthy -or
 [DateTimeOffset]$s.at -lt [DateTimeOffset]([IO.File]::ReadAllText($release+'\activated.json')|ConvertFrom-Json).at -or
 $targets.Count -ne @($b.claudeBindings).Count -or @($targets|Where-Object {-not $_.ready -or $_.held -or -not $_.nativeConnected -or $_.pid -eq 0 -or $_.admission.Blocking -ne 0}).Count -or
 (Bindings) -cne $b.bindings -or (Unknown) -cne $b.unknown -or $s.nativeLinuxPid -ne $b.nativePid){throw 'Exact full recovery not yet verified; inspect, never clear/replay'}
$result=@{at=$s.at;code=$m.code;policy=$stage.policy;claude=$targets;bindingsPreserved=$true;unknownPreserved=$true;daemonPreserved=$true;inputReplay=0;wsLRestartTested=$false}
Save ($release+'\verified.json') $result;$result|ConvertTo-Json -Depth 9 -Compress
