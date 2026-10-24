param([Parameter(Mandatory=$true)][ValidateSet('prepare','validate','stage','probe','activate','verify')][string]$Phase)
# Scoped observer repair. Preserve native custody and all uncertain receipts.
# Reconciliation is performed by the tested router, never by editing a live DB.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote';$temp='C:\Users\pou\AppData\Local\Temp'
$release="$root\release-claude-handoff-20261024";$source="$temp\router-claude-handoff-20261024-v2"
$manifestHash='B9843DBB9ED372E4FF7C92B72EFC7D835C2245B48C1A2A5A97ECB312C7C20082'
$oldCode='32E50A1F4199BF281BDE3BC71B0ACB94731DF0B9BC6981CD82002EF863261C25'
$code='2FF3072D7599A11A76ACE6CCAD23184AE85C207EAEE63B906BC56804DD58B7F5'
$policy='6271B521E9C069618384FD6632088C7FAF06FDD1CBCB8A7CBCDC36E77215192C'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$helper="$temp\deploy-switch-isolation-20261014.ps1"
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helpers changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Unknown','Bindings','HostIdentity','ExactTask','Fenced')){
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
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or @($s.nativeSessions|Where-Object {$_.binding.Runtime -eq 'windows' -and $_.busy}).Count){throw 'Fresh idle owned Windows work required; independent Linux work remains untouched'}
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
if($Phase -eq 'prepare'){
 Artifacts $oldCode;if(Test-Path $release){throw 'Existing evidence: inspect, never overwrite'}
 if((Get-FileHash "$temp\router-claude-handoff-20261024-v2.manifest.json").Hash -ne $manifestHash){throw 'Exact reviewed manifest required'}
 $m=[IO.File]::ReadAllText("$temp\router-claude-handoff-20261024-v2.manifest.json")|ConvertFrom-Json
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
 $publisherHash='B7384A54C0C2C364C1AD02E478958B7F72C0EED8C7869927E78EFA30722C9484'
 if((Get-FileHash "$temp\dispatch-controller-claude-handoff-20261024.ps1").Hash -ne $publisherHash){throw 'Reviewed publisher differs'}
 Copy-Item "$temp\dispatch-controller-claude-handoff-20261024.ps1" "$release\dispatch-controller-handoff.ps1";Protect "$release\dispatch-controller-handoff.ps1"
}
if($Phase -in @('prepare','validate')){
 Artifacts $oldCode
 if(Test-Path "$release\prepared.json"){throw 'Already validated: read retained evidence'}
 if((Get-FileHash "$temp\router-claude-handoff-20261024-v2.manifest.json").Hash -ne $manifestHash){throw 'Exact manifest required'}
 $m=[IO.File]::ReadAllText("$temp\router-claude-handoff-20261024-v2.manifest.json")|ConvertFrom-Json
 foreach($f in $m.files){if($f.Name -notmatch '^[A-Za-z0-9._-]+$' -or (Get-FileHash (Join-Path "$release\candidate" $f.Name)).Hash -ne $f.Sha256){throw 'Sealed candidate drift'}}
 if((Get-FileHash "$release\dispatch-controller-handoff.ps1").Hash -ne 'B7384A54C0C2C364C1AD02E478958B7F72C0EED8C7869927E78EFA30722C9484'){throw 'Sealed publisher drift'}
 $acl=(& ([ScriptBlock]::Create([IO.File]::ReadAllText("$release\dispatch-controller-handoff.ps1"))) -SelfTest)-join "`n";if($acl -notmatch 'Passed 4 controller-handoff ACL publication checks'){throw 'Publisher ACL fixture failed'}
 $tests=@{publisher=$acl}
 foreach($suite in @('--self-test-controller-handoff','--self-test-transport-health','--self-test-reliability','--self-test-delivery','--self-test-startup-isolation','--self-test')){
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
 if((Get-FileHash "$native\dispatch-controller-handoff.ps1").Hash -ne '6F99331B285FC1C902569722E290A2B33CEA2C6635670F2A4966231697790D4E'){throw 'Protected publisher changed'}
 $before=@{bindings=(Bindings);host=(HostIdentity);claudePids=@($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude'}|ForEach-Object { @{thread=$_.binding.ThreadId;pid=$_.pid} });startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled;at=[DateTimeOffset]::UtcNow}
 Save "$release\before.json" $before;Copy-Item "$root\state\probe.json" "$release\previous-probe.json";Protect "$release\previous-probe.json"
 try{
  StopObserver
  if([RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('dispatching','unknown')").Length -or [RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Unsettled intake/action: preserve for review'}
  Save "$release\original-unknown.json" @{receipts=(Unknown)}
  if((Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host){throw 'Bindings or independent custody changed'}
 }catch{
  try{if((Get-Service KhadangRouter).Status -eq 'Stopped'){StartObserver}}finally{RestoreSupervisors $before}
  throw
 }
 Move-Item "$root\bin" "$release\previous-bin";New-Item -ItemType Directory "$root\bin"|Out-Null;Protect "$root\bin" $true
 Copy-Item "$release\candidate\*" "$root\bin";Protect "$root\bin" $true;Artifacts $code
 Copy-Item "$native\dispatch-controller-handoff.ps1" "$release\previous-publisher.ps1";Protect "$release\previous-publisher.ps1"
 Copy-Item "$release\dispatch-controller-handoff.ps1" "$native\dispatch-controller-handoff.ps1" -Force;Protect "$native\dispatch-controller-handoff.ps1"
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
 $p|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Independent host/connector/policy unchanged; controller adds exact primary-user UUID/content-verified Claude handoffs';liveClaudeAvailabilityClaimed=$false} -Force
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
  $s=Status;$targets=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -in @('01a104cc-9a63-7901-8897-abf8aff3dfb3','01a0facd-1bc0-7d23-95d6-c32fde0c62db','7dc840b0-402f-451e-bc79-dadfb706d363','10ab0d8a-f31c-49ca-ab99-1a6152ae4ee2')})
  $guards=@{statusFresh=([DateTimeOffset]$s.at -ge [DateTimeOffset]::UtcNow.AddSeconds(-40));pollFresh=([DateTimeOffset]$s.lastPollAttempt -ge [DateTimeOffset]::UtcNow.AddSeconds(-60));background=([bool]$s.backgroundHealthy);transport=([bool]$s.nativeTransportHealthy);targets=($targets.Count -eq 4 -and @($targets|Where-Object {$_.held -or -not $_.ready -or -not $_.nativeConnected -or $_.admission.Blocking -ne 0}).Count -eq 0);bindings=((Bindings) -ceq $before.bindings);host=((HostIdentity) -ceq $before.host)}
  if(@($guards.Values|Where-Object {-not $_}).Count -eq 0){break}
 }catch{$guards=@{snapshotRead=$false}}
 Start-Sleep -Milliseconds 500
}while([DateTimeOffset]::UtcNow -lt $end)
if(@($guards.Values|Where-Object {-not $_}).Count){throw ('Fresh exact readiness not proven: '+(($guards.Keys|Where-Object {-not $guards[$_]}) -join ','))}
$unknown=[IO.File]::ReadAllText("$release\original-unknown.json")|ConvertFrom-Json
if((Unknown) -cne $unknown.receipts){throw 'Unknown receipts changed: inspect, never overwrite'}
foreach($old in $before.claudePids){if(@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $old.thread -and $_.pid -eq $old.pid}).Count -ne 1){throw 'Independent Claude worker generation changed'}}
RestoreSupervisors $before
$result=@{at=[DateTimeOffset]::UtcNow;code=$code;baseAndControllerReady=$true;dutAndMimicReady=$true;claudeNativePidsPreserved=$true;routes=@($s.nativeSessions).Count;held=@($s.nativeSessions|Where-Object held|ForEach-Object {$_.binding.Name});nativePid=$s.nativeLinuxPid;unknownReceiptsPreserved=$true;bindingsPreserved=$true;independentHostPreserved=$true;poll=$s.lastPollAttempt;inputReplay=0;freshOwnerRoundTripClaimed=$false}
Save "$release\verified.json" $result;$result|ConvertTo-Json -Depth 5 -Compress
