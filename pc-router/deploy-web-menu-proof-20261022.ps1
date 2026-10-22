param([Parameter(Mandatory=$true)][ValidateSet('prepare','stage','probe','activate','verify','rollback','release-unsent')][string]$Phase)
# Follow-up: exact later menu ACKs supersede UI-config uncertainty only.
# Original uncertain receipts remain untouched; no native task is replayed.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote';$temp='C:\Users\pou\AppData\Local\Temp'
$release="$root\release-web-menu-proof-20261022";$prior="$root\release-web-handoff-20261022"
$oldCode='C58FB5EB22F673055072F6FCFFBC5A069E111279402C7680AE2F330A9D0CAA51'
$code='72B601927C23C67F46A232627B14420BDE79EB80A8BE0D6E3AE48F18A8C683C5'
$policy='6271B521E9C069618384FD6632088C7FAF06FDD1CBCB8A7CBCDC36E77215192C'
$zip='5D17DBBCAB457A72014A0C074F4E303C71F8D15AC02892161633AAE87A77ADCA'
$publisher='6F99331B285FC1C902569722E290A2B33CEA2C6635670F2A4966231697790D4E'
$watchdog='057093FD58A701422AE7EDE4BA0022717C3702288A46C97CF57AA0989EDD6382'
$pin='01a104a6-9fce-74a3-bdb0-e6dc04237ce7'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$helper="$temp\deploy-switch-isolation-20261014.ps1"
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helpers changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Unknown','Bindings','HostIdentity','ExactTask','Fenced','Hex')){$d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true);if(-not $d){throw 'Helper missing'};. ([ScriptBlock]::Create($d.Extent.Text))}
LoadSql "$native\inspect-state.ps1" 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
function Status{[IO.File]::ReadAllText("$root\state\status.json")|ConvertFrom-Json}
function ExactArtifacts($digest){if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $digest -or (Get-FileHash "$root\config.json").Hash -ne $policy -or (Get-FileHash "$native\router-watchdog-20261014.ps1").Hash -ne $watchdog -or (Get-FileHash "$native\dispatch-controller-handoff.ps1").Hash -ne $publisher -or -not (Get-Acl "$root\state").AreAccessRulesProtected){throw 'Exact accepted artifacts and explicit state ACL required'}}
function SafeStop{
 if((Get-Service KhadangRouter).Status -eq 'Running'){$s=Status;if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or @($s.nativeSessions|Where-Object {$_.binding.Runtime -eq 'windows' -and $_.busy}).Count){throw 'Do not stop active or unobserved owned Windows work'}}
 foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $name;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
}
function NormalStart{
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"');StartMode='Manual'};if($r.ReturnValue){throw 'Normal path failed'};Start-Service KhadangRouter
}
function RestoreSupervisors($before){foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){(ExactTask $name).Enabled=[bool]$(if($name -like '*Startup'){$before.startup}else{$before.watchdog})}}
if($Phase -eq 'prepare'){
 ExactArtifacts $oldCode;if(Test-Path $release){throw 'Existing release; reconcile'}
 if((Get-FileHash "$temp\router-web-menu-proof-20261022.zip").Hash -ne $zip){throw 'Candidate changed'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true;Copy-Item "$temp\router-web-menu-proof-20261022.zip" "$release\candidate.zip";Protect "$release\candidate.zip"
 if((Get-FileHash "$release\candidate.zip").Hash -ne $zip){throw 'Sealed candidate differs'}
 Add-Type -AssemblyName System.IO.Compression.FileSystem;$archive=[IO.Compression.ZipFile]::OpenRead("$release\candidate.zip")
 try{foreach($e in $archive.Entries){if($e.FullName -notmatch '^[A-Za-z0-9._-]+$' -or $e.Length -gt 200MB -or ($e.ExternalAttributes -shr 16 -band 0xF000) -eq 0xA000){throw 'Unexpected archive entry'}}}finally{$archive.Dispose()}
 [IO.Compression.ZipFile]::ExtractToDirectory("$release\candidate.zip","$release\candidate");Protect "$release\candidate" $true
 if((Get-FileHash "$release\candidate\KhadangRouter.dll").Hash -ne $code){throw 'Sealed code differs'}
 $focused=(& "$release\candidate\KhadangRouter.exe" --self-test-controller-handoff)-join "`n";if($LASTEXITCODE -or $focused -notmatch '^Passed 76 controller-handoff checks'){throw 'Focused Windows regressions failed'}
 $tests=(& "$release\candidate\KhadangRouter.exe" --self-test)-join "`n";if($LASTEXITCODE -or $tests -notmatch '^All 1636 PC-router checks passed'){throw 'Full Windows regressions failed'}
 Save "$release\prepared.json" @{code=$code;policy=$policy;tests=$tests;focused=$focused;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='prepared';tests=$tests;focused=$focused;productionChanged=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'rollback'){
 if((Get-FileHash "$release\previous-bin\KhadangRouter.dll").Hash -ne $oldCode -or (Get-FileHash "$root\config.json").Hash -ne $policy -or (Test-Path "$release\rolled-back-bin")){throw 'Exact rollback required'}
 $before=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json;SafeStop
 Move-Item "$root\bin" "$release\rolled-back-bin";Move-Item "$release\previous-bin" "$root\bin";Copy-Item "$release\previous-probe.json" "$root\state\probe.json" -Force;Protect "$root\state\probe.json"
 NormalStart;RestoreSupervisors $before;@{phase='rolled-back';inputReplay=0}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'stage'){
 ExactArtifacts $oldCode;if(-not (Test-Path "$release\prepared.json") -or (Test-Path "$release\before.json")){throw 'Fresh preparation required'}
 $s=Status;$web=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $pin})
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or [DateTimeOffset]$s.lastPollAttempt -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 18 -or $web.Count -ne 1 -or $web[0].held -or $web[0].busy -or -not $web[0].nativeConnected -or @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Fresh polling, idle Web and native custody required'}
 Save "$release\before.json" @{host=(HostIdentity);unknown=(Unknown);bindings=(Bindings);held=@($s.nativeSessions|Where-Object held|ForEach-Object {$_.binding.ThreadId});startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled;at=[DateTimeOffset]::UtcNow.ToString('o')}
 Copy-Item "$root\state\probe.json" "$release\previous-probe.json";SafeStop
 if([RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('dispatching','unknown')").Length -or [RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Unsettled effects; preserve'}
 Move-Item "$root\bin" "$release\previous-bin";New-Item -ItemType Directory "$root\bin"|Out-Null;Protect "$root\bin" $true;Copy-Item "$release\candidate\*" "$root\bin";Protect "$root\bin" $true;ExactArtifacts $code
 Save "$release\staged.json" @{code=$code;policy=$policy;at=[DateTimeOffset]::UtcNow.ToString('o')};@{phase='staged';inputAndOperationRowsChanged=0;nativeWorkersRestarted=0}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'probe'){
 Fenced;$svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --probe-service --config "'+$root+'\config.json"');StartMode='Manual'};if($r.ReturnValue){throw 'Probe path failed'};Start-Service KhadangRouter
 $stage=[IO.File]::ReadAllText("$release\staged.json")|ConvertFrom-Json;$end=[DateTimeOffset]::UtcNow.AddSeconds(55)
 do{$p=[IO.File]::ReadAllText("$root\state\probe.json")|ConvertFrom-Json;if($p.routerSha256 -eq $code -and $p.policySha256 -eq $policy -and $p.verified -and [DateTimeOffset]$p.testedAt -gt [DateTimeOffset]$stage.at){break};Start-Sleep -Milliseconds 500}while([DateTimeOffset]::UtcNow -lt $end)
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 if($p.routerSha256 -ne $code -or $p.policySha256 -ne $policy -or -not $p.verified -or -not $p.credentialAndCodeDenied -or -not $p.nativeWindowsSandboxVerified -or -not $p.nativeLinuxCommandOwnerVerified -or $p.modelInference -or $p.telegramPolling -or [DateTimeOffset]$p.testedAt -le [DateTimeOffset]$stage.at){throw 'Fresh SYSTEM proof required'}
 Save "$release\generic-proof.json" $p;$old=[IO.File]::ReadAllText("$release\previous-probe.json")|ConvertFrom-Json;if(-not $old.nativeLinuxClaudeContinuityVerified){throw 'Unchanged Claude host acceptance required'}
 foreach($field in @('nativeLinuxClaudeLaunchVerified','nativeLinuxClaudeToolOwnerVerified','nativeLinuxClaudeContinuityVerified','nativeLinuxClaudeAcceptance')){if($old.PSObject.Properties[$field]){$p|Add-Member $field $old.$field -Force}}
 $p|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Exact later menu ACK proof only; policy, connectors and independent native host unchanged';nativeModelTestsRerun=$false} -Force
 Save "$root\state\probe.json" $p;Save "$release\accepted.json" @{code=$code;policy=$policy;at=[DateTimeOffset]::UtcNow.ToString('o')};@{phase='probe-accepted';modelsStarted=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'activate'){Fenced;ExactArtifacts $code;$null=[IO.File]::ReadAllText("$release\accepted.json")|ConvertFrom-Json;NormalStart;@{phase='activated';nativeWorkersRestarted=0}|ConvertTo-Json -Compress;return}
if($Phase -eq 'release-unsent'){
 ExactArtifacts $code;$null=[IO.File]::ReadAllText("$release\verified.json")|ConvertFrom-Json
 $s=Status;$web=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $pin});$id='web-board-render-swap-2026-10-21';$fingerprint='837C309EE4CF97ED45739D0F85C51381BAD97617C9422BE212D621708410A70F'
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or -not $s.backgroundHealthy -or -not $s.nativeTransportHealthy -or $web.Count -ne 1 -or $web[0].held -or $web[0].busy){throw 'Exact healthy idle Web required'}
 LoadSql "$native\stage-dut-topic.ps1" '0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF' 'PcbaRegistry';$db=[PcbaRegistry]::new()
 try{
  $saved=$db.Read("SELECT value FROM meta WHERE key='controller-handoff/$id'")[0][0]|ConvertFrom-Json
  if($saved.state -ne 'retained-held' -or $saved.fingerprint -cne $fingerprint -or $saved.mode -or $saved.turnId -or $saved.target.ThreadId -ne $pin -or $db.Read("SELECT key FROM meta WHERE key='owner-released-unsent-handoff/$id'").Length){throw 'Only the exact proven PRE-NATIVE retained request may be released once'}
  $job=[IO.File]::ReadAllText("$root\state\controller-handoffs\$id.json")|ConvertFrom-Json
  if($job.TextSha256 -ne '1D062092A1CCA8DBA4BD3793B77B2CDC986C31D53460836251A0A6767FAEC72E' -or [DateTimeOffset]$job.ExpiresAt -le [DateTimeOffset]::UtcNow -or $job.RequestId -ne $id){throw 'Original unexpired approved task required'}
  Save "$release\original-retained-handoff.json" $saved
  $record=@{originalRequestId=$id;priorReceipt=$saved;reason='Owner-approved repair of proven pre-native admission failure; same task/id, no native input attempted';inputReplay=0;at=[DateTimeOffset]::UtcNow.ToString('o')}
  $db.Read('BEGIN IMMEDIATE')|Out-Null
  try{
   $null=$db.Read("INSERT INTO meta(key,value) VALUES('owner-released-unsent-handoff/$id',CAST(X'$(Hex $record)' AS TEXT))")
   $null=$db.Read("DELETE FROM meta WHERE key='controller-handoff/$id' AND json_extract(value,'$.state')='retained-held' AND json_extract(value,'$.fingerprint')='$fingerprint'")
   if($db.Read('SELECT changes()')[0][0] -ne '1'){throw 'Retained receipt changed; preserve'}
   $db.Read('COMMIT')|Out-Null
  }catch{$db.Read('ROLLBACK')|Out-Null;throw}
  Save "$release\unsent-release.json" $record
 }finally{$db.Dispose()}
 @{phase='unsent-released-once';originalRequestId=$id;priorReceiptRetained=$true;nativeInputReplay=0;deliveryClaimed=$false}|ConvertTo-Json -Compress;return
}
$before=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json;$a=[IO.File]::ReadAllText("$release\accepted.json")|ConvertFrom-Json;$end=[DateTimeOffset]::UtcNow.AddSeconds(55)
do{try{$s=Status}catch{$s=$null};if($s -and [DateTimeOffset]$s.at -gt [DateTimeOffset]$a.at -and [DateTimeOffset]$s.lastPollAttempt -gt [DateTimeOffset]$a.at){break};Start-Sleep -Milliseconds 500}while([DateTimeOffset]::UtcNow -lt $end)
if((Get-Service KhadangRouter).Status -ne 'Running' -or [DateTimeOffset]$s.at -le [DateTimeOffset]$a.at -or [DateTimeOffset]$s.lastPollAttempt -le [DateTimeOffset]$a.at -or [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 18 -or -not $s.nativeTransportHealthy -or -not $s.backgroundHealthy -or (Unknown) -cne $before.unknown -or (Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host -or @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Fresh polling/custody/health not confirmed'}
$held=@($s.nativeSessions|Where-Object held|ForEach-Object {$_.binding.ThreadId});if(($held|Sort-Object|ConvertTo-Json -Compress) -cne (@($before.held)|Sort-Object|ConvertTo-Json -Compress)){throw 'Unrelated holds changed'}
RestoreSupervisors $before
Save "$release\verified.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');routes=18;nativeDaemonPid=479;backgroundHealthy=$s.backgroundHealthy;nativeTransportHealthy=$s.nativeTransportHealthy;telegramPolling=$true;supervisorsRestored=$true;webUnheld=$true;unknownReceiptsPreserved=$true;hostPreserved=$true;inputReplay=0}
[IO.File]::ReadAllText("$release\verified.json")
