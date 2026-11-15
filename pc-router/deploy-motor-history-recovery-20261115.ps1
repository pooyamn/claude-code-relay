param([Parameter(Mandatory=$true)][ValidateSet('stage','probe','activate','verify','rollback')][string]$Phase)
# Reader-only compatibility fix. Never stop the independent host, rewrite a
# transcript, replay input, discard output uncertainty or change a binding.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$PSDefaultParameterValues['Get-Content:Encoding']='UTF8'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote'
$release=$root+'\release-motor-history-recovery-20261115';$pin='8cd2d34c-0805-4705-8197-d11de0728499'
$code='C6BAB770BDC160B62CE36A279E8EBF4039852CF7314A088D15CA5EB6F1DC6B45'
$oldPolicy='BA702EC3497F03E9F31F80092223200102751C7100BE9473C0A1B2E8D97513D3'
$oldConnector='F8B2AA66E3A30D210882EB8B93171423383B76A1F309CAA66B361EE410B0427A'
$candidate='70C0BF322DA5CF41B9C29F873E8912A62F0470518516BA25944A48580BFE2985'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed owner maintenance required'}
$helper='C:\Users\pou\AppData\Local\Temp\deploy-switch-isolation-20261014.ps1'
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helpers changed'}
$a=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Bindings','Unknown','HostIdentity','ExactTask')){
 $d=$a.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true);. ([scriptblock]::Create($d.Extent.Text))
}
LoadSql ($native+'\inspect-state.ps1') 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
function Status{Get-Content ($root+'\state\status.json') -Raw|ConvertFrom-Json}
function RestoredTasks{
 $before=Get-Content ($release+'\before.json') -Raw|ConvertFrom-Json
 foreach($n in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){(ExactTask $n).Enabled=[bool]$before.tasks.$n}
}
function StartObserver([bool]$Probe=$false){
 $mode=if($Probe){'--probe-service'}else{'--service'}
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" '+$mode+' --config "'+$root+'\config.json"');StartMode='Manual'}
 if($r.ReturnValue){throw 'Observer path rejected'};Start-Service KhadangRouter
}
function CoreUnchanged{
 if((Get-FileHash ($root+'\bin\KhadangRouter.dll')).Hash -ne $code -or (Get-Service KhadangClaudeHost).Status -ne 'Running'){throw 'Unchanged independent native custody required'}
}
CoreUnchanged
if($Phase -eq 'stage'){
 if((Test-Path ($release+'\before.json')) -or (Get-FileHash ($root+'\config.json')).Hash -ne $oldPolicy){throw 'Fresh exact deployment required; inspect existing evidence'}
 $s=Status;$motor=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $pin})
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddSeconds(-30) -or $motor.Count -ne 1 -or $motor[0].pid -ne 0 -or $motor[0].nativeConnected -or $motor[0].busy -or $motor[0].admission.Blocking -or
  @($s.nativeSessions|Where-Object {$_.binding.Runtime -eq 'windows' -and $_.busy}).Count){throw 'Fresh unavailable Motor and idle observer-owned Windows work required'}
 $policy=Get-Content ($root+'\config.json') -Raw|ConvertFrom-Json;$connector=$policy.LinuxClaude.PackageRoot+'\pc_claude_stdio.py'
 $source='C:\Users\pou\AppData\Local\Temp\pc_claude_stdio-motor-history-20261115.py'
 if((Get-FileHash $connector).Hash -ne $oldConnector -or (Get-FileHash $source).Hash -ne $candidate){throw 'Reviewed connector hashes required'}
 if(-not (Test-Path $release)){New-Item -ItemType Directory $release|Out-Null;Protect $release $true}
 Copy-Item $source ($release+'\candidate.py');Protect ($release+'\candidate.py')
 if((Get-FileHash ($release+'\candidate.py')).Hash -ne $candidate){throw 'Sealed candidate differs'}
 $tasks=@{};foreach($n in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$tasks[$n]=(ExactTask $n).Enabled}
 Save ($release+'\before.json') @{at=$s.at;status=$s;tasks=$tasks;bindings=(Bindings);unknown=(Unknown);host=(HostIdentity);connector=$connector}
 foreach($file in @('config.json','state\probe.json')){Copy-Item ($root+'\'+$file) ($release+'\previous-'+[IO.Path]::GetFileName($file));Protect ($release+'\previous-'+[IO.Path]::GetFileName($file))}
 Copy-Item $connector ($release+'\previous-connector.py');Protect ($release+'\previous-connector.py')
 foreach($n in $tasks.Keys){$t=ExactTask $n;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30))
 $lease=[IO.File]::Open($root+'\state\exclusive.lock','Open','ReadWrite','None')
 try{
  if([RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('received','dispatching','unknown')").Length -or [RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Unsettled root effects; preserve'}
  $tmp=$connector+'.history-reader';Copy-Item ($release+'\candidate.py') $tmp;Set-Acl $tmp (Get-Acl $connector);[IO.File]::Replace($tmp,$connector,[System.Management.Automation.Language.NullString]::Value)
  $policy.LinuxClaude.FileSha256.'pc_claude_stdio.py'=$candidate.ToLowerInvariant();Save ($root+'\config.json') $policy
  Save ($release+'\staged.json') @{at=[DateTimeOffset]::UtcNow.ToString('o');code=$code;policy=(Get-FileHash ($root+'\config.json')).Hash;connector=$candidate;tests='92 Python native-runtime tests, including 43 history-recovery fixtures, and exact authenticated Motor transcript passed; no native inference'}
 }finally{$lease.Dispose()}
 'STAGED; host and native peers preserved';return
}
if($Phase -eq 'rollback'){
 if((Get-Service KhadangRouter).Status -ne 'Stopped' -or (Test-Path ($release+'\activated.json'))){throw 'Rollback only before native activation; otherwise reconcile'}
 $b=Get-Content ($release+'\before.json') -Raw|ConvertFrom-Json
 $tmp=$b.connector+'.rollback';Copy-Item ($release+'\previous-connector.py') $tmp;Set-Acl $tmp (Get-Acl $b.connector);[IO.File]::Replace($tmp,$b.connector,[System.Management.Automation.Language.NullString]::Value)
 Copy-Item ($release+'\previous-config.json') ($root+'\config.json') -Force;Protect ($root+'\config.json')
 Copy-Item ($release+'\previous-probe.json') ($root+'\state\probe.json') -Force;Protect ($root+'\state\probe.json')
 StartObserver;RestoredTasks;'ROLLED BACK; no inputs replayed';return
}
$stage=Get-Content ($release+'\staged.json') -Raw|ConvertFrom-Json
if((Get-FileHash ($root+'\config.json')).Hash -ne $stage.policy){throw 'Staged policy changed'}
if($Phase -eq 'probe'){
 if((Get-Service KhadangRouter).Status -ne 'Stopped' -or (Test-Path ($release+'\accepted.json'))){throw 'Fresh fenced probe required'}
 StartObserver $true;$end=[DateTimeOffset]::UtcNow.AddSeconds(50)
 try{
  do{Start-Sleep -Milliseconds 500;$proof=Get-Content ($root+'\state\probe.json') -Raw|ConvertFrom-Json
   if($proof.policySha256 -eq $stage.policy -and [DateTimeOffset]$proof.testedAt -gt [DateTimeOffset]$stage.at){break}
  }while([DateTimeOffset]::UtcNow -lt $end)
 }finally{Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30))}
 if(-not $proof.verified -or -not $proof.credentialAndCodeDenied -or -not $proof.nativeWindowsSandboxVerified -or -not $proof.nativeLinuxCommandOwnerVerified -or $proof.modelInference -or $proof.telegramPolling -or $proof.routerSha256 -ne $code -or $proof.policySha256 -ne $stage.policy -or [DateTimeOffset]$proof.testedAt -le [DateTimeOffset]$stage.at){throw 'Fresh SYSTEM security proof failed'}
 Save ($release+'\generic-proof.json') $proof
 $old=Get-Content ($release+'\previous-probe.json') -Raw|ConvertFrom-Json
 if(-not $old.nativeLinuxClaudeLaunchVerified -or -not $old.nativeLinuxClaudeToolOwnerVerified -or -not $old.nativeLinuxClaudeContinuityVerified){throw 'Existing native acceptance missing'}
 foreach($field in @('nativeLinuxClaudeLaunchVerified','nativeLinuxClaudeToolOwnerVerified','nativeLinuxClaudeContinuityVerified','nativeLinuxClaudeAcceptance')){$proof|Add-Member $field $old.$field -Force}
 $proof|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='History reader compatibility for exact task run IDs, structured text queue receipts and correlated asynchronous Agent completions only; native binary, launch, permissions, wire protocol and host/router code unchanged';nativeModelTestsRerun=$false} -Force
 Save ($root+'\state\probe.json') $proof;Save ($release+'\accepted.json') @{at=[DateTimeOffset]::UtcNow.ToString('o');policy=$stage.policy}
 'SECURITY PROBE PASSED; unchanged native-runtime acceptance explicitly retained';return
}
if($Phase -eq 'activate'){
 if((Get-Service KhadangRouter).Status -ne 'Stopped' -or -not (Test-Path ($release+'\accepted.json')) -or (Test-Path ($release+'\activated.json'))){throw 'Fresh accepted activation required'}
 Save ($release+'\activated.json') @{at=[DateTimeOffset]::UtcNow.ToString('o');replay=0}
 try{StartObserver}finally{RestoredTasks}
 'ACTIVATED; verify native Motor and Telegram delivery';return
}
$before=Get-Content ($release+'\before.json') -Raw|ConvertFrom-Json
$end=[DateTimeOffset]::UtcNow.AddSeconds(50)
do{
 $s=Status;$m=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $pin})
 $missingPeers=@($before.status.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and $_.binding.ThreadId -ne $pin -and $_.nativeConnected}|Where-Object {
  $oldPeer=$_;@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $oldPeer.binding.ThreadId -and $_.nativeConnected -and $_.pid -eq $oldPeer.pid}).Count -ne 1})
 if([DateTimeOffset]$s.at -gt [DateTimeOffset]$stage.at -and $m.Count -eq 1 -and $m[0].nativeConnected -and -not $m[0].held -and -not $missingPeers.Count){break}
 Start-Sleep -Milliseconds 500
}while([DateTimeOffset]::UtcNow -lt $end)
$motor=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $pin})
if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddSeconds(-30) -or $motor.Count -ne 1 -or -not $motor[0].nativeConnected -or $motor[0].held -or $motor[0].admission.Blocking -or
 (Bindings) -cne $before.bindings -or (Unknown) -cne $before.unknown -or (HostIdentity) -cne $before.host -or $s.nativeLinuxPid -ne $before.status.nativeLinuxPid){throw 'Exact native recovery not confirmed; inspect without replay'}
foreach($peer in @($before.status.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and $_.binding.ThreadId -ne $pin -and $_.nativeConnected})){
 $now=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $peer.binding.ThreadId})
 if($now.Count -ne 1 -or -not $now[0].nativeConnected -or $now[0].pid -ne $peer.pid){throw 'Existing native peer changed'}
}
Save ($release+'\verified.json') @{at=$s.at;motor=$motor[0];hostPreserved=$true;bindingsPreserved=$true;uncertaintyPreserved=$true;inputReplay=0;peerWorkersPreserved=$true}
'VERIFIED: Motor connected and unheld; same history, bindings, native peers and uncertain receipts preserved'
