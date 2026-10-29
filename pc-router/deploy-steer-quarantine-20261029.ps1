param([Parameter(Mandatory=$true)][ValidateSet('prepare','validate','stage','probe','activate','verify')][string]$Phase)
# Scoped observer repair. Preserve native custody and all uncertain receipts.
# Reconciliation is performed by the tested router, never by editing a live DB.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote';$temp='C:\Users\pou\AppData\Local\Temp'
$release="$root\release-steer-quarantine-20261029";$source="$temp\router-steer-quarantine-20261029-win"
$manifestHash='CAF9E2B9FAC79A0996954A5340CC41ECFCF19FAC88E91D410CD54A04779FBD37'
$oldCode='69E74A18F68D48BE729976D42EDD1461F99D5C864BC196A6D65A5B48291C8E30'
$code='0E219BC929A8DB6903DDC3F172BC2D14F22E710D7270D48EEB2E33668000E851'
$policy='20CBA6C69B0463B3AA576B690737C7C9586FEB120501C1C28CE554F2032CF85A'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$helper="$temp\deploy-switch-isolation-20261014.ps1"
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helpers changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Unknown','Bindings','HostIdentity','ExactTask','Fenced','Hex')){
 $d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true)
 if(-not $d){throw 'Missing helper'};. ([ScriptBlock]::Create($d.Extent.Text))
}
LoadSql "$native\inspect-state.ps1" 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
function Status{[IO.File]::ReadAllText("$root\state\status.json")|ConvertFrom-Json}
function Artifacts($hash){
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $hash -or (Get-FileHash "$root\config.json").Hash -ne $policy -or -not (Get-Acl "$root\state").AreAccessRulesProtected){throw 'Pinned code/policy/ACL required'}
 $h='C:\ProgramData\KhadangClaudeHost';$i=[IO.File]::ReadAllText("$h\installed.json")|ConvertFrom-Json
 if($i.dll -ne (Get-FileHash "$h\bin\KhadangRouter.dll").Hash -or $i.exe -ne (Get-FileHash "$h\bin\KhadangRouter.exe").Hash){throw 'Independent host startup attestation differs; release not restartable'}
}
function RestoreSupervisors($before){foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){(ExactTask $name).Enabled=[bool]$(if($name -like '*Startup'){$before.startup}else{$before.watchdog})}}
function StopObserver{
 $s=Status
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or @($s.nativeSessions|Where-Object {$_.binding.Runtime -eq 'windows' -and $_.busy}).Count -or
  [RouterReceipts]::Read("SELECT id FROM updates WHERE status='dispatching'").Length -or
  [RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Fresh idle Windows custody and no in-flight mutations required; independent Linux work remains untouched'}
 foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $name;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
 $svc=Get-Service KhadangRouter
 if($svc.Status -ne 'Stopped'){$svc.Stop();$svc.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(50))}
 Fenced
}
function StartObserver([bool]$Probe=$false){
 $mode=if($Probe){'--probe-service'}else{'--service'}
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" '+$mode+' --config "'+$root+'\config.json"');StartMode='Manual'}
 if($r.ReturnValue){throw 'Service path update failed'};Start-Service KhadangRouter
}

function QuarantineCompletedSteer{
 $pin='01a158ac-b686-7011-b706-8549a7f8e6d2';$operation='84e7974188084c9e9af3338bf9642c0e'
 $proofPath="$temp\motor-native-read-20261029.json"
 if((Get-FileHash $proofPath).Hash -ne '2EDC9B36B064807D4C5B217F1B969345D5766A4F07A2CA3509EB884C59996442'){throw 'Reviewed native observation changed'}
 $proof=[IO.File]::ReadAllText($proofPath)|ConvertFrom-Json
 if(-not $proof.readOnly -or $proof.modelInference -or $proof.peer.peerPid -ne 479 -or $proof.peer.peerUid -ne 1000 -or
  $proof.thread -cne $pin -or $proof.workspace -cne '/Users/pouya/.openclaw/workspace/motorcontrol-plant' -or
  $proof.oldTurn.id -ne '01a16ef1-5cc0-7951-b414-fe3cd3cbf75d' -or $proof.oldTurn.status -ne 'completed' -or
  -not $proof.latestTurn.id -or $proof.latestTurn.id -eq $proof.oldTurn.id -or
  [DateTimeOffset]::FromUnixTimeSeconds([long][Math]::Floor($proof.observedAt)) -lt [DateTimeOffset]::UtcNow.AddMinutes(-15)){throw 'Exact fresh terminal-turn native evidence required'}
 Copy-Item $proofPath "$release\native-observation.json";Protect "$release\native-observation.json"
 LoadSql "$native\stage-dut-topic.ps1" '0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF' 'PcbaRegistry'
 $lease=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null
 try{
  $db=[PcbaRegistry]::new()
  if($db.Read("SELECT id FROM updates WHERE status IN ('received','dispatching','unknown')").Length -or
   $db.Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Unsettled input/effect; no reconciliation'}
  $binding=$db.Read('SELECT payload FROM bindings WHERE chat=-1003550185469 AND topic=14439')[0][0]|ConvertFrom-Json
  $effect=$db.Read("SELECT kind,status,payload,result FROM operations WHERE id='$operation'")[0];$payload=$effect[2]|ConvertFrom-Json
  if($binding.ThreadId -cne $pin -or $binding.Backend -ne 'codex' -or $binding.Runtime -ne 'linux' -or
   $binding.Workspace -cne $proof.workspace -or $effect[0] -ne 'native/turn/steer' -or $effect[1] -ne 'unknown' -or
   $payload.parameters.threadId -cne $pin -or $payload.parameters.expectedTurnId -cne $proof.oldTurn.id -or $null -ne $effect[3]){throw 'Exact original unknown steer required'}
  if($db.Read("SELECT key FROM meta WHERE key='owner-steer-quarantine/$operation'").Length){throw 'Existing review; inspect, never overwrite'}
  $sha=[Security.Cryptography.SHA256]::Create()
  try{$fingerprint=[BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($effect[2]))).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
  $review=@{schema='ccrelay.owner_steer_quarantine.v1';operation=$operation;binding=$binding;payloadSha256=$fingerprint;
   action='retain-unknown-no-replay';deliveryConfirmed=$false;replay=$false;terminalTurn=$proof.oldTurn;observedThread=$proof.thread;
   observedWorkspace=$proof.workspace;currentTurn=$proof.latestTurn.id;evidenceSha256=(Get-FileHash $proofPath).Hash.ToLowerInvariant();
   ownerApproval='Pouya confirmed Motorcontrol Plant recovery in CC Relay topic816 on2026-10-29; continue without replaying the old uncertain steer';at=[DateTimeOffset]::UtcNow}
  Save "$release\original-steer.json" @{kind=$effect[0];status=$effect[1];payload=$effect[2];result=$effect[3]}
  Save "$release\owner-review.json" $review
  $null=$db.Read('BEGIN IMMEDIATE')
  try{$null=$db.Read("INSERT INTO meta VALUES('owner-steer-quarantine/$operation',CAST(X'$(Hex $review)' AS TEXT))");$null=$db.Read('COMMIT')}catch{$null=$db.Read('ROLLBACK');throw}
 }finally{if($db){$db.Dispose()};$lease.Dispose()}
}

if($Phase -eq 'prepare'){
 Artifacts $oldCode;if(Test-Path $release){throw 'Existing evidence: inspect, never overwrite'}
 if((Get-FileHash "$temp\router-steer-quarantine-20261029.manifest.json").Hash -ne $manifestHash){throw 'Exact reviewed manifest required'}
 $m=[IO.File]::ReadAllText("$temp\router-steer-quarantine-20261029.manifest.json")|ConvertFrom-Json
 if($m.schema -ne 'ccrelay.release_files.v1' -or @($m.files).Count -lt 10 -or @($m.files).Count -gt 250 -or @($m.files.Name|Sort-Object -Unique).Count -ne @($m.files).Count -or @(Get-ChildItem -LiteralPath $source).Count -ne @($m.files).Count){throw 'Invalid sealed file set'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 New-Item -ItemType Directory "$release\candidate"|Out-Null;Protect "$release\candidate" $true
 foreach($f in $m.files){
  if($f.Name -notmatch '^[A-Za-z0-9._-]+$' -or $f.Sha256 -notmatch '^[A-F0-9]{64}$' -or $f.Size -le 0 -or $f.Size -gt 100MB){throw 'Invalid candidate entry'}
  $p=Join-Path $source $f.Name;$i=Get-Item -LiteralPath $p
  if($i.PSIsContainer -or $i.Attributes -band [IO.FileAttributes]::ReparsePoint -or $i.Length -ne $f.Size -or (Get-FileHash $p).Hash -ne $f.Sha256){throw 'Candidate changed'}
  Copy-Item -LiteralPath $p -Destination "$release\candidate";Protect (Join-Path "$release\candidate" $f.Name)
  if((Get-FileHash (Join-Path "$release\candidate" $f.Name)).Hash -ne $f.Sha256){throw 'Protected candidate differs'}
 }
 if((Get-FileHash "$release\candidate\KhadangRouter.dll").Hash -ne $code){throw 'Unexpected reviewed code'}
}
if($Phase -in @('prepare','validate')){
 Artifacts $oldCode
 if(Test-Path "$release\prepared.json"){throw 'Already validated: read retained evidence'}
 if((Get-FileHash "$temp\router-steer-quarantine-20261029.manifest.json").Hash -ne $manifestHash){throw 'Exact manifest required'}
 $m=[IO.File]::ReadAllText("$temp\router-steer-quarantine-20261029.manifest.json")|ConvertFrom-Json
 foreach($f in $m.files){if($f.Name -notmatch '^[A-Za-z0-9._-]+$' -or (Get-FileHash (Join-Path "$release\candidate" $f.Name)).Hash -ne $f.Sha256){throw 'Sealed candidate drift'}}
 $tests=@{}
 foreach($suite in @('--self-test-ledger-performance','--self-test-controller-handoff','--self-test-transport-health','--self-test-reliability','--self-test-delivery','--self-test-startup-isolation','--self-test')){
  $text=(& "$release\candidate\KhadangRouter.exe" $suite)-join "`n"
  if($LASTEXITCODE -or $text -notmatch '(Passed \d+ .+ checks|All \d+ PC-router checks passed)'){throw "Candidate suite failed: $suite"}
  $tests[$suite]=$text;Save "$release\tests.json" $tests
 }
 Save "$release\prepared.json" @{at=[DateTimeOffset]::UtcNow;code=$code;manifest=$manifestHash;policy=$policy}
 @{phase='prepared';tests=$tests;productionChanged=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'stage'){
 Artifacts $oldCode;if(-not (Test-Path "$release\prepared.json") -or (Test-Path "$release\before.json")){throw 'Fresh preparation required'}
 $s=Status
 $before=@{bindings=(Bindings);host=(HostIdentity);held=@($s.nativeSessions|Where-Object held|ForEach-Object {$_.binding.ThreadId});claudePids=@($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude'}|ForEach-Object { @{thread=$_.binding.ThreadId;pid=$_.pid} });startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled;at=[DateTimeOffset]::UtcNow}
 Save "$release\before.json" $before;Copy-Item "$root\state\probe.json" "$release\previous-probe.json";Protect "$release\previous-probe.json"
 try{
  Save "$release\original-unknown.json" @{receipts=(Unknown)}
  StopObserver
  $u=[IO.File]::ReadAllText("$release\original-unknown.json")|ConvertFrom-Json
  if((Unknown) -cne $u.receipts){throw 'Receipt uncertainty changed during graceful stop; preserve and inspect'}
  if((Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host){throw 'Bindings or independent custody changed'}
 }catch{
  try{if((Get-Service KhadangRouter).Status -eq 'Stopped'){StartObserver}}finally{RestoreSupervisors $before}
  throw
 }
 try{QuarantineCompletedSteer}catch{try{StartObserver}finally{RestoreSupervisors $before};throw}
 Move-Item "$root\bin" "$release\previous-bin";New-Item -ItemType Directory "$root\bin"|Out-Null;Protect "$root\bin" $true
 Copy-Item "$release\candidate\*" "$root\bin";Protect "$root\bin" $true;Artifacts $code
 Save "$release\staged.json" @{at=[DateTimeOffset]::UtcNow;code=$code}
 @{phase='staged';nativeDaemonsStopped=0;receiptRowsChanged=0}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'probe'){
 Fenced;Artifacts $code;$stage=[IO.File]::ReadAllText("$release\staged.json")|ConvertFrom-Json
 StartObserver $true;$end=[DateTimeOffset]::UtcNow.AddSeconds(55)
 do{$p=[IO.File]::ReadAllText("$root\state\probe.json")|ConvertFrom-Json;if($p.routerSha256 -eq $code -and [DateTimeOffset]$p.testedAt -gt [DateTimeOffset]$stage.at){break};Start-Sleep -Milliseconds 500}while([DateTimeOffset]::UtcNow -lt $end)
 $svc=Get-Service KhadangRouter;$svc.Stop();$svc.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 if($p.routerSha256 -ne $code -or $p.policySha256 -ne $policy -or -not $p.verified -or -not $p.credentialAndCodeDenied -or -not $p.nativeWindowsSandboxVerified -or -not $p.nativeLinuxCommandOwnerVerified -or $p.modelInference -or $p.telegramPolling -or [DateTimeOffset]$p.testedAt -le [DateTimeOffset]$stage.at){throw 'Fresh SYSTEM security proof required'}
 Save "$release\generic-proof.json" $p
 $old=[IO.File]::ReadAllText("$release\previous-probe.json")|ConvertFrom-Json;$before=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json
 if(-not $old.nativeLinuxClaudeContinuityVerified -or (HostIdentity) -cne $before.host){throw 'Unchanged independent host contract required'}
 foreach($field in @('nativeLinuxClaudeLaunchVerified','nativeLinuxClaudeToolOwnerVerified','nativeLinuxClaudeContinuityVerified','nativeLinuxClaudeAcceptance')){if($old.PSObject.Properties[$field]){$p|Add-Member $field $old.$field -Force}}
 $p|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Independent host/connector/policy unchanged; router-only indexed/batched receipt reads and isolated status publisher';liveClaudeAvailabilityClaimed=$false} -Force
 Save "$root\state\probe.json" $p;Save "$release\accepted.json" @{at=[DateTimeOffset]::UtcNow;code=$code}
 @{phase='accepted';credentialBoundaryVerified=$true;modelInference=$false}|ConvertTo-Json -Compress;return
}
$before=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json
if($Phase -eq 'activate'){
 Fenced;Artifacts $code;$null=[IO.File]::ReadAllText("$release\accepted.json")
 Save "$release\activated.json" @{at=[DateTimeOffset]::UtcNow;code=$code}
 try{StartObserver}finally{RestoreSupervisors $before}
 @{phase='activated';nativeDaemonRestarted=$false}|ConvertTo-Json -Compress;return
}
Artifacts $code;$activation=[IO.File]::ReadAllText("$release\activated.json")|ConvertFrom-Json
$end=[DateTimeOffset]::UtcNow.AddSeconds(50)
do{
 try{
  $s=Status;$targets=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -in @('01a104cc-9a63-7901-8897-abf8aff3dfb3','01a0facd-1bc0-7d23-95d6-c32fde0c62db','7dc840b0-402f-451e-bc79-dadfb706d363','01a158ac-b686-7011-b706-8549a7f8e6d2')})
  $guards=@{statusFresh=([DateTimeOffset]$s.at -ge [DateTimeOffset]::UtcNow.AddSeconds(-20));pollFresh=([DateTimeOffset]$s.lastPollAttempt -ge [DateTimeOffset]::UtcNow.AddSeconds(-40));statusCost=($s.PSObject.Properties['statusBuildMs'] -and $s.statusBuildMs -lt 2000);background=([bool]$s.backgroundHealthy);transport=([bool]$s.nativeTransportHealthy);targets=($targets.Count -eq 4 -and @($targets|Where-Object {$_.held -or -not $_.ready -or -not $_.nativeConnected -or $_.admission.Blocking -ne 0}).Count -eq 0);bindings=((Bindings) -ceq $before.bindings);host=((HostIdentity) -ceq $before.host)}
  if(@($guards.Values|Where-Object {-not $_}).Count -eq 0){break}
 }catch{$guards=@{snapshotRead=$false}}
 Start-Sleep -Milliseconds 500
}while([DateTimeOffset]::UtcNow -lt $end)
if(@($guards.Values|Where-Object {-not $_}).Count){throw ('Fresh exact readiness not proven: '+(($guards.Keys|Where-Object {-not $guards[$_]}) -join ','))}
$unknown=[IO.File]::ReadAllText("$release\original-unknown.json")|ConvertFrom-Json
if((Unknown) -cne $unknown.receipts){throw 'Unknown receipts changed: inspect, never overwrite'}
foreach($old in $before.claudePids){if(@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $old.thread -and $_.pid -eq $old.pid}).Count -ne 1){throw 'Independent Claude worker generation changed'}}
RestoreSupervisors $before
$availabilityReattached=@()
foreach($held in $before.held){
 $route=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $held})
 if($route.Count -eq 1 -and $route[0].held){continue}
 if($held -eq '01a158ac-b686-7011-b706-8549a7f8e6d2' -and $route.Count -eq 1 -and
  $route[0].nativeConnected -and $route[0].ready -and $route[0].admission.Blocking -eq 0){
  $availabilityReattached+=$route[0].binding.Name;continue
 }

 # These two pre-existing observation-only failures recovered through the
 # ordinary exact-ID ResumeCodex path. This verification does NOT clear a hold
 # or grant a retry: require fresh health, unchanged uncertainty, and an exact
 # protected native resume/security receipt. All other hold changes fail closed.
 if($held -notin @('01a1122c-c62d-75f2-9b47-9ad9adcdf7d5','01a104a5-c705-71b1-8614-c193d97da290') -or
  $route.Count -ne 1 -or $route[0].binding.Backend -ne 'codex' -or -not $route[0].ready -or -not $route[0].nativeConnected -or $route[0].admission.Blocking -ne 0){throw 'Unexpected hold transition; inspect, never clear or replay'}
 $rows=[RouterReceipts]::Read("SELECT result FROM operations WHERE kind='native/thread/resume' AND status='confirmed' AND json_extract(payload,'$.parameters.threadId')='$held' ORDER BY rowid DESC LIMIT 1")
 if($rows.Length -ne 1){throw 'Exact successful resume receipt missing'}
 $ack=$rows[0][0]|ConvertFrom-Json;$p=[IO.File]::ReadAllText("$root\config.json")|ConvertFrom-Json
 # These are computed JsonIgnore properties in RouterPolicy, not config keys.
 $approval=if($p.OwnerFullAccess){'never'}else{'on-request'};$sandbox=if($p.OwnerFullAccess){'dangerFullAccess'}else{'workspaceWrite'}
 if($ack.thread.id -cne $held -or $ack.cwd -cne $route[0].binding.Workspace -or $ack.approvalPolicy -ne $approval -or $ack.approvalsReviewer -ne 'user' -or $ack.sandbox.type -ne $sandbox){throw 'Resume identity/workspace/security receipt differs'}
 $availabilityReattached+=$route[0].binding.Name
}
if([RouterReceipts]::Read("SELECT name FROM sqlite_master WHERE type='index' AND name IN ('operations_status_kind','updates_status')").Length -ne 2){throw 'Live receipt indexes absent'}
$result=@{at=[DateTimeOffset]::UtcNow;code=$code;baseAndControllerReady=$true;dutReady=$true;motorReady=$true;statusBuildMs=$s.statusBuildMs;availabilityReattached=$availabilityReattached;claudeNativePidsPreserved=$true;routes=@($s.nativeSessions).Count;held=@($s.nativeSessions|Where-Object held|ForEach-Object {$_.binding.Name});nativePid=$s.nativeLinuxPid;unknownReceiptsPreserved=$true;bindingsPreserved=$true;independentHostPreserved=$true;poll=$s.lastPollAttempt;inputReplay=0;freshOwnerRoundTripClaimed=$false}
Save "$release\verified.json" $result;$result|ConvertTo-Json -Depth 5 -Compress
