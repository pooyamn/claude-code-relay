param(
 [Parameter(Mandatory=$true)][ValidateSet('prepare','stage','probe','activate','verify','rollback')][string]$Phase,
 [Parameter(Mandatory=$true)][ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$ManifestSha256,
 [Parameter(Mandatory=$true)][ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$CandidateSha256)
# Observer authorization only. No grants, native restarts, DB writes or replay.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$PSDefaultParameterValues['Get-Content:Encoding']='UTF8'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote';$temp='C:\Users\pou\AppData\Local\Temp'
$release="$root\release-participant-commands-20261114";$source="$temp\router-participant-commands-20261114"
$oldCode='BD6CF699E3BD92ABC86C552C4F5BAC11BFDAA73876979A4AED98E7CF548F1B86'
$policy='BA702EC3497F03E9F31F80092223200102751C7100BE9473C0A1B2E8D97513D3'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed owner maintenance required'}
$helper="$temp\deploy-switch-isolation-20261014.ps1"
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helpers changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Unknown','Bindings','HostIdentity','ExactTask','Fenced')){
 $d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true)
 if(-not $d){throw 'Missing helper'};. ([scriptblock]::Create($d.Extent.Text))
}
LoadSql "$native\inspect-state.ps1" 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
function Status{[IO.File]::ReadAllText("$root\state\status.json")|ConvertFrom-Json}
function Artifacts($hash){
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $hash -or (Get-FileHash "$root\config.json").Hash -ne $policy -or (Get-Service KhadangClaudeHost).Status -ne 'Running'){throw 'Pinned code, policy and independent host required'}
 $h='C:\ProgramData\KhadangClaudeHost';$i=Get-Content "$h\installed.json" -Raw|ConvertFrom-Json
 if($i.dll -ne (Get-FileHash "$h\bin\KhadangRouter.dll").Hash -or $i.exe -ne (Get-FileHash "$h\bin\KhadangRouter.exe").Hash){throw 'Host startup attestation changed'}
}
function RestoreTasks($before){foreach($n in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){(ExactTask $n).Enabled=[bool]$before.tasks.$n}}
function StartObserver([bool]$Probe=$false){
 $mode=if($Probe){'--probe-service'}else{'--service'}
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" '+$mode+' --config "'+$root+'\config.json"');StartMode='Manual'}
 if($r.ReturnValue){throw 'Service path update failed'};Start-Service KhadangRouter
}
function StopObserver{
 $s=Status
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or @($s.nativeSessions|Where-Object {$_.binding.Runtime -eq 'windows' -and $_.busy}).Count -or
  [RouterReceipts]::Read("SELECT id FROM updates WHERE status='dispatching'").Length -or
  [RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Fresh idle Windows custody and settled dispatch required'}
 foreach($n in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $n;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(50));Fenced
}
if($Phase -eq 'prepare'){
 Artifacts $oldCode;if(Test-Path $release){throw 'Existing release; inspect instead of overwriting'}
 $manifest="$temp\router-participant-commands-20261114.manifest.json"
 if((Get-FileHash $manifest).Hash -ne $ManifestSha256){throw 'Reviewed manifest required'}
 $m=Get-Content $manifest -Raw|ConvertFrom-Json
 if(@($m.files).Count -lt 10 -or @($m.files).Count -gt 250 -or @($m.files.Name|Sort-Object -Unique).Count -ne @($m.files).Count -or @(Get-ChildItem $source).Count -ne @($m.files).Count){throw 'Invalid candidate file set'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 New-Item -ItemType Directory "$release\candidate"|Out-Null;Protect "$release\candidate" $true
 foreach($f in $m.files){
  if($f.Name -notmatch '^[A-Za-z0-9._-]+$' -or $f.Sha256 -notmatch '^[A-F0-9]{64}$' -or $f.Size -le 0 -or $f.Size -gt 100MB){throw 'Invalid manifest entry'}
  $p=Join-Path $source $f.Name;$i=Get-Item $p
  if($i.PSIsContainer -or $i.Attributes -band [IO.FileAttributes]::ReparsePoint -or $i.Length -ne $f.Size -or (Get-FileHash $p).Hash -ne $f.Sha256){throw 'Candidate changed'}
  $sealed=Join-Path "$release\candidate" $f.Name;Copy-Item $p $sealed;Protect $sealed
  if((Get-FileHash $sealed).Hash -ne $f.Sha256){throw 'Sealed file differs'}
 }
 if((Get-FileHash "$release\candidate\KhadangRouter.dll").Hash -ne $CandidateSha256){throw 'Unexpected reviewed code'}
 $tests=@{}
 foreach($suite in @('--self-test-participants','--self-test-claude-restart','--self-test-ledger-performance','--self-test-reliability','--self-test-delivery','--self-test-input-isolation','--self-test-startup-isolation','--self-test-transport-health','--self-test-capacity','--self-test-controller-handoff','--self-test')){
  $text=(& "$release\candidate\KhadangRouter.exe" $suite)-join "`n"
  if($LASTEXITCODE -or $text -notmatch '(Passed \d+ .+ checks|All \d+ PC-router checks passed)'){throw "Offline candidate suite failed: $suite"}
  $tests[$suite]=$text;Save "$release\tests.json" $tests;Write-Output $text
 }
 Save "$release\prepared.json" @{at=[DateTimeOffset]::UtcNow;code=$CandidateSha256;manifest=$ManifestSha256;policy=$policy}
 'PREPARED; production unchanged';return
}
if($Phase -eq 'rollback'){
 $before=Get-Content "$release\before.json" -Raw|ConvertFrom-Json
 if((Get-Service KhadangRouter).Status -ne 'Stopped' -or -not (Test-Path "$release\previous-bin") -or (Get-FileHash "$root\config.json").Hash -ne $policy){throw 'Stopped exact rollback required'}
 Move-Item "$root\bin" "$release\rejected-bin";Move-Item "$release\previous-bin" "$root\bin"
 Copy-Item "$release\previous-probe.json" "$root\state\probe.json" -Force;Protect "$root\state\probe.json"
 try{StartObserver}finally{RestoreTasks $before};'ROLLED BACK; no input replay';return
}
if($Phase -eq 'stage'){
 Artifacts $oldCode
 if(-not (Test-Path "$release\prepared.json") -or (Test-Path "$release\before.json")){throw 'Fresh validated release required'}
 $prepared=Get-Content "$release\prepared.json" -Raw|ConvertFrom-Json
 if($prepared.code -ne $CandidateSha256 -or $prepared.manifest -ne $ManifestSha256){throw 'Preparation differs'}
 $s=Status;$tasks=@{};foreach($n in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$tasks[$n]=(ExactTask $n).Enabled}
 $before=@{at=[DateTimeOffset]::UtcNow;status=$s;tasks=$tasks;bindings=(Bindings);unknown=(Unknown);host=(HostIdentity)}
 Save "$release\before.json" $before;Copy-Item "$root\state\probe.json" "$release\previous-probe.json";Protect "$release\previous-probe.json"
 try{
  StopObserver
  if((Unknown) -cne $before.unknown -or (Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host){throw 'Custody or uncertainty changed; preserve'}
 }catch{try{if((Get-Service KhadangRouter).Status -eq 'Stopped'){StartObserver}}finally{RestoreTasks $before};throw}
 $lease=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None')
 try{
  Move-Item "$root\bin" "$release\previous-bin"
  Copy-Item "$release\candidate" "$root\bin" -Recurse;Protect "$root\bin" $true
  Artifacts $CandidateSha256;Save "$release\staged.json" @{at=[DateTimeOffset]::UtcNow;code=$CandidateSha256}
 }finally{$lease.Dispose()}
 'STAGED; native workers and receipts preserved';return
}
Artifacts $CandidateSha256
if($Phase -in @('probe','activate')){Fenced}
if($Phase -eq 'probe'){
 $stage=Get-Content "$release\staged.json" -Raw|ConvertFrom-Json
 try{
  StartObserver $true;$end=[DateTimeOffset]::UtcNow.AddSeconds(55)
  do{Start-Sleep -Milliseconds 500;$p=Get-Content "$root\state\probe.json" -Raw|ConvertFrom-Json
   if($p.routerSha256 -eq $CandidateSha256 -and [DateTimeOffset]$p.testedAt -gt [DateTimeOffset]$stage.at){break}
  }while([DateTimeOffset]::UtcNow -lt $end)
 }finally{Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30))}
 if(-not $p.verified -or -not $p.credentialAndCodeDenied -or -not $p.nativeWindowsSandboxVerified -or -not $p.nativeLinuxCommandOwnerVerified -or $p.modelInference -or $p.telegramPolling -or $p.routerSha256 -ne $CandidateSha256 -or $p.policySha256 -ne $policy -or [DateTimeOffset]$p.testedAt -le [DateTimeOffset]$stage.at){throw 'Fresh SYSTEM security proof failed'}
 Save "$release\generic-proof.json" $p;$old=Get-Content "$release\previous-probe.json" -Raw|ConvertFrom-Json
 if(-not $old.nativeLinuxClaudeLaunchVerified -or -not $old.nativeLinuxClaudeToolOwnerVerified -or -not $old.nativeLinuxClaudeContinuityVerified){throw 'Prior unchanged native-runtime acceptance missing'}
 foreach($f in @('nativeLinuxClaudeLaunchVerified','nativeLinuxClaudeToolOwnerVerified','nativeLinuxClaudeContinuityVerified','nativeLinuxClaudeAcceptance')){$p|Add-Member $f $old.$f -Force}
 $p|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Observer participant command authorization and handoff attribution only; policy, native binary, connector, host, launch and permissions unchanged';nativeModelTestsRerun=$false} -Force
 Save "$root\state\probe.json" $p;Save "$release\accepted.json" @{at=[DateTimeOffset]::UtcNow;code=$CandidateSha256}
 'SECURITY PROBE PASSED; no model inference';return
}
$before=Get-Content "$release\before.json" -Raw|ConvertFrom-Json
if($Phase -eq 'activate'){
 $null=Get-Content "$release\accepted.json" -Raw|ConvertFrom-Json
 Save "$release\activated.json" @{at=[DateTimeOffset]::UtcNow;code=$CandidateSha256}
 try{StartObserver}finally{RestoreTasks $before};'ACTIVATED; native workers not restarted';return
}
$activation=Get-Content "$release\activated.json" -Raw|ConvertFrom-Json
$end=[DateTimeOffset]::UtcNow.AddSeconds(50)
do{
 $s=Status
 if([DateTimeOffset]$s.at -gt [DateTimeOffset]$activation.at -and [DateTimeOffset]$s.lastPollAttempt -gt [DateTimeOffset]$activation.at){break}
 Start-Sleep -Milliseconds 500
}while([DateTimeOffset]::UtcNow -lt $end)
if((Get-Service KhadangRouter).Status -ne 'Running' -or [DateTimeOffset]$s.at -le [DateTimeOffset]$activation.at -or
 [DateTimeOffset]$s.lastPollAttempt -le [DateTimeOffset]$activation.at -or -not $s.backgroundHealthy -or -not $s.nativeLinuxConnected -or
 $s.nativeLinuxPid -ne $before.status.nativeLinuxPid -or (Bindings) -cne $before.bindings -or (Unknown) -cne $before.unknown -or (HostIdentity) -cne $before.host){throw 'Fresh polling, preserved custody and receipts not proven'}
foreach($old in @($before.status.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and $_.nativeConnected})){
 if(@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $old.binding.ThreadId -and $_.nativeConnected -and $_.pid -eq $old.pid}).Count -ne 1){throw 'Native peer changed'}
}
$held=@($s.nativeSessions|Where-Object held|ForEach-Object {$_.binding.ThreadId})|Sort-Object|ConvertTo-Json -Compress
$previousHeld=@($before.status.nativeSessions|Where-Object held|ForEach-Object {$_.binding.ThreadId})|Sort-Object|ConvertTo-Json -Compress
if($held -cne $previousHeld){throw 'Unrelated holds changed; inspect'}
RestoreTasks $before
Save "$release\verified.json" @{at=$s.at;code=$CandidateSha256;approvedParticipantCommands=$true;ownerOnlyApprovals=$true;routes=@($s.bindings).Count;nativeLinuxPid=$s.nativeLinuxPid;nativePeersPreserved=$true;grantsAndBindingsUnchanged=$true;uncertainReceiptsPreserved=$true;supervisorsRestored=$true;telegramPolling=$true;phoneRoundTripClaimed=$false;inputReplay=0;preexistingHeld=@($before.status.nativeSessions|Where-Object held|ForEach-Object {$_.binding.Name})}
Get-Content "$release\verified.json" -Raw
