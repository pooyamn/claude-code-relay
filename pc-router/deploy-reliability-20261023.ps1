param([Parameter(Mandatory=$true)][ValidateSet('prepare','stage','probe','activate','verify','rollback')][string]$Phase)
# Sealed, owner-requested reliability release. No native host/daemon restart,
# fake owner update, model canary, uncertain-send retry or database rollback.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote';$temp='C:\Users\pou\AppData\Local\Temp'
$release="$root\release-reliability-20261023";$source="$temp\router-reliability-20261023"
$manifestHash='2DFFB924F210CBE927140AA2E4B57C9BC41AF2C06F0BCDC2DBC16F7FDC372254';$code='283FA49068C461BAA97F5585D94E69FDB3E930EC87AC9A40ABE74C251C2112FF'
$oldCode='D0028E06D93781B15BD202B7360636C9B401A87BE82C262AFB7E27AF3EC4BAD3'
$policy='6271B521E9C069618384FD6632088C7FAF06FDD1CBCB8A7CBCDC36E77215192C'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$helper="$temp\deploy-switch-isolation-20261014.ps1"
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helpers changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Unknown','Bindings','HostIdentity','ExactTask','Fenced')){
 $d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true);if(-not $d){throw 'Missing helper'};. ([ScriptBlock]::Create($d.Extent.Text))
}
$helper="$temp\deploy-web-menu-proof-20261022.ps1"
if((Get-FileHash $helper).Hash -ne 'C02D912692A3811174D8B6190F8AF37982E4543F44C05D88A13E3556BF6F0958'){throw 'Reviewed lifecycle changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Status','SafeStop','NormalStart','RestoreSupervisors')){
 $d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true);if(-not $d){throw 'Missing lifecycle helper'};. ([ScriptBlock]::Create($d.Extent.Text))
}
LoadSql "$native\inspect-state.ps1" 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
function Artifacts([string]$hash){
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $hash -or (Get-FileHash "$root\config.json").Hash -ne $policy -or
  -not (Get-Acl "$root\state").AreAccessRulesProtected){throw 'Pinned artifacts/policy and explicit protected state required'}
}
function StopObserver{
 try{SafeStop}catch{
  if((Get-Service KhadangRouter).Status -ne 'Stopped'){
   try{(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(20))}catch{throw 'Graceful observer stop unconfirmed; no force kill or data change permitted'}
  }
  Fenced
 }
}
if($Phase -eq 'prepare'){
 Artifacts $oldCode;if(Test-Path $release){throw 'Existing release evidence; inspect, never overwrite'}
 if($code -notmatch '^[A-F0-9]{64}$' -or $manifestHash -notmatch '^[A-F0-9]{64}$' -or (Get-FileHash "$temp\router-reliability-20261023.manifest.json").Hash -ne $manifestHash){throw 'Exact reviewed manifest required'}
 $manifest=[IO.File]::ReadAllText("$temp\router-reliability-20261023.manifest.json")|ConvertFrom-Json
 if($manifest.schema -ne 'ccrelay.release_files.v1' -or @($manifest.files).Count -lt 10 -or @($manifest.files).Count -gt 250 -or
  @($manifest.files.Name|Sort-Object -Unique).Count -ne @($manifest.files).Count -or @(Get-ChildItem -LiteralPath $source).Count -ne @($manifest.files).Count){throw 'Unexpected candidate file set'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 New-Item -ItemType Directory "$release\candidate"|Out-Null;Protect "$release\candidate" $true
 foreach($file in $manifest.files){
  if($file.Name -notmatch '^[A-Za-z0-9._-]+$' -or $file.Sha256 -notmatch '^[A-F0-9]{64}$' -or $file.Size -le 0 -or $file.Size -gt 100MB){throw 'Invalid sealed file'}
  $path=Join-Path $source $file.Name;$item=Get-Item -LiteralPath $path
  if($item.PSIsContainer -or $item.Attributes -band [IO.FileAttributes]::ReparsePoint -or $item.Length -ne $file.Size -or (Get-FileHash -LiteralPath $path).Hash -ne $file.Sha256){throw 'Source candidate changed'}
  Copy-Item -LiteralPath $path -Destination "$release\candidate";Protect (Join-Path "$release\candidate" $file.Name)
  if((Get-FileHash -LiteralPath (Join-Path "$release\candidate" $file.Name)).Hash -ne $file.Sha256){throw 'Protected candidate differs'}
 }
 if((Get-FileHash "$release\candidate\KhadangRouter.dll").Hash -ne $code){throw 'Core code differs'}
 Copy-Item "$temp\router-reliability-20261023.manifest.json" "$release\manifest.json";Protect "$release\manifest.json"
 $results=@{}
 foreach($suite in @('--self-test-reliability','--self-test-delivery','--self-test-input-isolation','--self-test-startup-isolation','--self-test-participants','--self-test')){
  $result=(& "$release\candidate\KhadangRouter.exe" $suite)-join "`n"
  if($LASTEXITCODE -or $result -notmatch '(Passed \d+ .+ checks|All \d+ PC-router checks passed)'){throw "Candidate regression failed: $suite"}
  $results[$suite]=$result;Save "$release\test-results.json" $results
 }
 Save "$release\prepared.json" @{code=$code;policy=$policy;manifest=$manifestHash;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='prepared';productionChanged=$false;tests=$results}|ConvertTo-Json -Depth 4 -Compress;return
}
if($Phase -eq 'rollback'){
 if(Test-Path "$release\activated.json"){throw 'Activated outbox schema requires reviewed forward recovery; never restore an old database or blindly downgrade'}
 if(-not (Test-Path "$release\previous-bin")){throw 'No staged artifact replacement to roll back'}
 $before=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json;StopObserver
 Move-Item "$root\bin" "$release\rejected-bin";Move-Item "$release\previous-bin" "$root\bin"
 Copy-Item "$release\previous-probe.json" "$root\state\probe.json" -Force;Protect "$root\state\probe.json";Artifacts $oldCode
 try{NormalStart}finally{RestoreSupervisors $before}
 @{phase='rolled-back-before-activation';databaseRestored=$false;nativeReplay=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'stage'){
 Artifacts $oldCode;if(-not (Test-Path "$release\prepared.json") -or (Test-Path "$release\before.json")){throw 'Fresh completed preparation required'}
 $s=Status
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 18 -or
  @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count -or
  @($s.nativeSessions|Where-Object {$_.binding.Runtime -eq 'windows' -and ($_.busy -or -not $_.nativeConnected)}).Count -or
  [RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('dispatching','unknown')").Length){throw 'Fresh native custody and quiescent ingress/owned Windows work required'}
 $before=@{host=(HostIdentity);bindings=(Bindings);unknown=(Unknown);held=@($s.nativeSessions|Where-Object held|ForEach-Object {$_.binding.ThreadId});
  claudePids=@($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude'}|ForEach-Object {@{thread=$_.binding.ThreadId;pid=$_.pid}});
  startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled;at=[DateTimeOffset]::UtcNow.ToString('o')}
 Save "$release\before.json" $before;Copy-Item "$root\state\probe.json" "$release\previous-probe.json";Protect "$release\previous-probe.json"
 try{
  StopObserver
  if([RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('dispatching','unknown')").Length -or
   [RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length -or
   (Unknown) -cne $before.unknown -or (Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host){throw 'State changed while stopping; preserve without replay'}
  LoadSql "$native\stage-dut-topic.ps1" '0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF' 'PcbaRegistry'
  $lease=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null
  try{$db=[PcbaRegistry]::new();$null=$db.Read("VACUUM INTO '$release\previous-router.db'");Protect "$release\previous-router.db"}finally{if($db){$db.Dispose()};$lease.Dispose()}
  Move-Item "$root\bin" "$release\previous-bin";New-Item -ItemType Directory "$root\bin"|Out-Null;Protect "$root\bin" $true
  Copy-Item "$release\candidate\*" "$root\bin";Protect "$root\bin" $true;Artifacts $code
  Save "$release\staged.json" @{code=$code;policy=$policy;at=[DateTimeOffset]::UtcNow.ToString('o')}
 }catch{
  if(-not (Test-Path "$release\previous-bin")){try{if((Get-Service KhadangRouter).Status -eq 'Stopped'){Start-Service KhadangRouter}}finally{RestoreSupervisors $before}}
  throw
 }
 @{phase='staged';nativeHostsStopped=0;receiptRowsChanged=0}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'probe'){
 Fenced;Artifacts $code;$staged=[IO.File]::ReadAllText("$release\staged.json")|ConvertFrom-Json
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --probe-service --config "'+$root+'\config.json"');StartMode='Manual'};if($r.ReturnValue){throw 'Probe configuration failed'}
 Start-Service KhadangRouter;$end=[DateTimeOffset]::UtcNow.AddSeconds(50)
 do{$p=[IO.File]::ReadAllText("$root\state\probe.json")|ConvertFrom-Json;if($p.routerSha256 -eq $code -and $p.verified -and [DateTimeOffset]$p.testedAt -gt [DateTimeOffset]$staged.at){break};Start-Sleep -Milliseconds 500}while([DateTimeOffset]::UtcNow -lt $end)
 try{Stop-Service KhadangRouter}catch{if((Get-Service KhadangRouter).Status -ne 'Stopped'){throw}}
 (Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 if($p.routerSha256 -ne $code -or $p.policySha256 -ne $policy -or -not $p.verified -or -not $p.credentialAndCodeDenied -or -not $p.nativeWindowsSandboxVerified -or
  -not $p.nativeLinuxCommandOwnerVerified -or $p.modelInference -or $p.telegramPolling -or [DateTimeOffset]$p.testedAt -le [DateTimeOffset]$staged.at){throw 'Fresh exact SYSTEM security proof required'}
 Save "$release\generic-proof.json" $p
 $old=[IO.File]::ReadAllText("$release\previous-probe.json")|ConvertFrom-Json;$before=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json
 if(-not $old.nativeLinuxClaudeContinuityVerified -or (HostIdentity) -cne $before.host){throw 'Independent unchanged Claude custody proof required'}
 foreach($field in @('nativeLinuxClaudeLaunchVerified','nativeLinuxClaudeToolOwnerVerified','nativeLinuxClaudeContinuityVerified','nativeLinuxClaudeAcceptance')){if($old.PSObject.Properties[$field]){$p|Add-Member $field $old.$field -Force}}
 $p|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Native host, launch paths, authorization settings, checkpoints and pipe contract unchanged; routing/delivery reliability redesigned';modelInferenceRerun=$false} -Force
 Save "$root\state\probe.json" $p;Save "$release\accepted.json" @{code=$code;policy=$policy;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='security-accepted';modelsStarted=0;telegramPolling=$false}|ConvertTo-Json -Compress;return
}
$before=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json
if($Phase -eq 'activate'){
 Fenced;Artifacts $code;$accepted=[IO.File]::ReadAllText("$release\accepted.json")|ConvertFrom-Json
 if($accepted.code -ne $code -or $accepted.policy -ne $policy -or (HostIdentity) -cne $before.host){throw 'Accepted custody changed'}
 Save "$release\activated.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');code=$code;outboxSchema='independent-files-and-retained-output'}
 try{NormalStart}finally{RestoreSupervisors $before}
 @{phase='activated';independentNativeHostsRestarted=0;supervisorsRestored=$true}|ConvertTo-Json -Compress;return
}
Artifacts $code;$activated=[IO.File]::ReadAllText("$release\activated.json")|ConvertFrom-Json;$end=[DateTimeOffset]::UtcNow.AddSeconds(50)
do{
 $s=Status
 if([DateTimeOffset]$s.at -gt [DateTimeOffset]$activated.at -and [DateTimeOffset]$s.lastPollAttempt -gt [DateTimeOffset]$activated.at -and
  @($s.nativeSessions).Count -eq 18 -and @($s.nativeSessions|Where-Object {-not $_.ready}).Count -eq 0){break}
 Start-Sleep -Milliseconds 500
}while([DateTimeOffset]::UtcNow -lt $end)
if((Get-Service KhadangRouter).Status -ne 'Running' -or [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or
 [DateTimeOffset]$s.lastPollAttempt -le [DateTimeOffset]$activated.at -or -not $s.backgroundHealthy -or -not $s.nativeTransportHealthy -or
 $s.nativeLinuxPid -ne 479 -or @($s.nativeSessions).Count -ne 18 -or @($s.nativeSessions|Where-Object {-not $_.ready}).Count -or
 @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count -or
 @($s.nativeSessions|Where-Object {-not $_.held -and $_.admission.Blocking -ne 0}).Count -or
 (Bindings) -cne $before.bindings -or (Unknown) -cne $before.unknown -or (HostIdentity) -cne $before.host){throw 'Fresh complete runtime/admission/polling/custody proof not yet established'}
if((@($s.nativeSessions|Where-Object held|ForEach-Object {$_.binding.ThreadId})|Sort-Object|ConvertTo-Json -Compress) -cne ($before.held|Sort-Object|ConvertTo-Json -Compress)){throw 'Unrelated native holds changed'}
foreach($prior in $before.claudePids){if(@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $prior.thread -and $_.pid -eq $prior.pid}).Count -ne 1){throw 'Independent Claude worker was replaced'}}
RestoreSupervisors $before
Save "$release\verified.json" @{at=$s.at;code=$code;policy=$policy;routesReady=18;daemonPreserved=479;claudeWorkersPreserved=$true;unknownReceiptsPreserved=$true;
 nativeHoldsPreserved=$true;unrelatedAdmissionBlocked=0;telegramPolling=$true;supervisorsRestored=$true;inputsReplayed=0;liveOwnerRoundTripTested=$false}
[IO.File]::ReadAllText("$release\verified.json")
