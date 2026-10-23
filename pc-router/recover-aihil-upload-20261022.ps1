param([ValidateSet('restore','resume-restore','verify')][string]$Phase='restore',
 [ValidateSet('legacy','v10')][string]$Upload='legacy')
# Scoped owner-requested recovery of Ai Dispatch/1876. Keep the uncertain old
# upload and original input receipts; never replay either or restart native work.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote';$temp='C:\Users\pou\AppData\Local\Temp'
$release="$root\recover-aihil-upload-20261022";$pin='2c0bce31-f586-4d5e-9422-4be550763ed8'
$op='c613e526888849cbbf4e1d6a1d61c999';$key="bubble/$pin"
$filename='oracova-yc-cut1b.mp4';$fileHash='416e18af04bdb9076eca935c376ad143575e6c6e2b7a7441810548824e35cbfd';$fileSize=9352387
if($Upload -eq 'v10'){
 $release="$root\recover-aihil-upload-v10-20261022";$op='cdcc419b7fed44878ff7170ddbf1bc48'
 $filename='oracova-yc-v10.mp4';$fileHash='217c6366f41a9b3674f62245236f8e61d77372a02e845cd2eb2c85dca1fb55c5';$fileSize=6081232
}
$code='D0028E06D93781B15BD202B7360636C9B401A87BE82C262AFB7E27AF3EC4BAD3'
$policy='6271B521E9C069618384FD6632088C7FAF06FDD1CBCB8A7CBCDC36E77215192C'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$helper="$temp\deploy-switch-isolation-20261014.ps1"
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helpers changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Unknown','Bindings','HostIdentity','Hex','ExactTask','Fenced')){
 $d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true)
 if(-not $d){throw 'Missing helper'};. ([ScriptBlock]::Create($d.Extent.Text))
}
$helper="$temp\deploy-web-menu-proof-20261022.ps1"
if((Get-FileHash $helper).Hash -ne 'C02D912692A3811174D8B6190F8AF37982E4543F44C05D88A13E3556BF6F0958'){throw 'Lifecycle helpers changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Status','SafeStop','RestoreSupervisors')){
 $d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true)
 if(-not $d){throw 'Missing lifecycle helper'};. ([ScriptBlock]::Create($d.Extent.Text))
}
LoadSql "$native\inspect-state.ps1" 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code -or (Get-FileHash "$root\config.json").Hash -ne $policy){throw 'Current artifacts changed; preserve'}
if($Phase -in @('restore','resume-restore')){
 if($Phase -eq 'restore' -and (Test-Path $release)){throw 'Existing recovery evidence; inspect, never repeat automatically'}
 if($Phase -eq 'resume-restore' -and (-not (Test-Path "$release\before.json") -or (Test-Path "$release\previous-router.db") -or (Test-Path "$release\restored.json"))){throw 'Resume only the proven pre-mutation stop failure'}
 $s=Status;$target=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $pin})
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 18 -or $target.Count -ne 1 -or
  -not $target[0].held -or $target[0].busy -or -not $target[0].claudeConnected -or
  @($s.nativeSessions|Where-Object {$_.binding.Runtime -eq 'windows' -and ($_.busy -or -not $_.nativeConnected)}).Count -or
  @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Fresh idle target and independent native custody required'}
 $tests=(& "$root\bin\KhadangRouter.exe" --self-test-output-recovery)-join "`n"
 if($LASTEXITCODE -or $tests -notmatch '^Passed [0-9]+ unlimited-output/backlog checks'){throw 'Output recovery regressions failed'}
 if($Phase -eq 'restore'){New-Item -ItemType Directory $release|Out-Null;Protect $release $true}
 $before=@{bindings=(Bindings);host=(HostIdentity);held=@($s.nativeSessions|Where-Object held|ForEach-Object {$_.binding.ThreadId});pid=$target[0].pid;
  startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled;tests=$tests;at=[DateTimeOffset]::UtcNow.ToString('o')}
 if($Phase -eq 'resume-restore'){
  $original=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json
  if($original.bindings -cne $before.bindings -or $original.host -cne $before.host -or $original.pid -ne $before.pid){throw 'Pre-mutation custody changed'}
  $before.startup=$original.startup;$before.watchdog=$original.watchdog
 }
 Save "$release\before.json" $before
 try{
  try{SafeStop}catch{
   # A failed stop is not authority to kill. Retry the idempotent service
   # control once only, with supervisors fenced and owned work freshly idle.
   if((Get-Service KhadangRouter).Status -ne 'Stopped'){
    $fresh=Status
    if([DateTimeOffset]$fresh.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or @($fresh.nativeSessions|Where-Object {$_.binding.Runtime -eq 'windows' -and ($_.busy -or -not $_.nativeConnected)}).Count){throw 'Owned work unobserved; do not retry stop'}
    foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){if((ExactTask $name).Enabled){throw 'Supervisor fence lost'}}
    try{Stop-Service KhadangRouter}catch{if((Get-Service KhadangRouter).Status -ne 'Stopped'){throw}}
    (Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30))
   }
   Fenced
  }
  LoadSql "$native\stage-dut-topic.ps1" '0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF' 'PcbaRegistry'
  $lease=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null
  try{
   $db=[PcbaRegistry]::new()
   if($db.Read("SELECT id FROM updates WHERE status IN ('received','dispatching','unknown')").Length -or
    $db.Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Unsettled intake/effects; preserve'}
   $before.unknown=Unknown;Save "$release\before.json" $before
   $binding=$db.Read('SELECT payload FROM bindings WHERE chat=-1003550185469 AND topic=1876')[0][0]|ConvertFrom-Json
   $raw=$db.Read("SELECT value FROM meta WHERE key='$key'")[0][0];$b=$raw|ConvertFrom-Json
   $effect=$db.Read("SELECT kind,payload,status FROM operations WHERE id='$op'")[0];$p=$effect[1]|ConvertFrom-Json
   if($binding.ThreadId -ne $pin -or $binding.Workspace -cne '/Users/pouya/.openclaw/workspace/ai-hil' -or $binding.Backend -ne 'claude' -or $binding.Runtime -ne 'linux' -or
    -not $b.held -or $b.busy -or $b.claudeState -ne 'idle' -or $b.sendUnknown -or $null -ne $b.claudeDeliveryHold -or
    $effect[0] -ne 'telegram/sendDocument' -or $effect[2] -ne 'unknown' -or $p.chat_id -ne $binding.Chat -or $p.message_thread_id -ne $binding.Topic -or
    $p.filename -cne $filename -or $p.sha256 -ne $fileHash -or $p.size -ne $fileSize){throw 'Exact idle topic and historical upload required'}
   if($db.Read("SELECT key FROM meta WHERE key='claude/reset/$pin' OR (key LIKE 'claude/request/$pin/%' AND json_extract(value,'$.status')='pending')").Length){throw 'Native reset or approval pending; preserve'}
   $answers=@($b.finalAnswer)+@($b.pendingAnswers)+@($b.pendingResponses|ForEach-Object finalAnswer)
   if(@($answers|ForEach-Object Parts|Where-Object SendUnknown).Count -or @($b.pendingResponses|Where-Object {$_.sendUnknown -and $null -eq $_.message}).Count){throw 'Uncertain text remains; preserve'}
   $unknown=@($answers|ForEach-Object Files|Where-Object SendUnknown)
   if($unknown.Count -ne 1 -or $unknown[0].Path -cne ($binding.Workspace+'/media/yc-video/'+$p.filename) -or $unknown[0].Sha256 -ne $p.sha256 -or $unknown[0].Size -ne $p.size -or $unknown[0].Message){throw 'Exact uncertain upload/outbox match required'}
   $null=$db.Read("VACUUM INTO '$release\previous-router.db'");Protect "$release\previous-router.db"
   Save "$release\original-bubble.json" ($raw|ConvertFrom-Json)
   $quarantine=@{schema='ccrelay.owner_output_quarantine.v1';operation=$op;chat=$binding.Chat;topic=$binding.Topic;workspace=$binding.Workspace;
    payloadSha256=[BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($effect[1]))).Replace('-','').ToLowerInvariant();
    action='retain-no-resend';file=$unknown[0];reason='Owner-requested topic recovery; retain ambiguous old video without retry';at=[DateTimeOffset]::UtcNow.ToString('o')}
   foreach($answer in $answers){if($null -ne $answer){$answer.Files=@($answer.Files|Where-Object {-not $_.SendUnknown})}}
   $b.held=$false;$b.status='Ready';$b.nativeStatus='Ready'
   $envelope=@{binding=$binding;bubble=$b}|ConvertTo-Json -Depth 100 -Compress
   $validation=($envelope|& "$root\bin\KhadangRouter.exe" --validate-outbox)-join "`n"
   if($LASTEXITCODE){throw 'Recovered outbox invalid'};$v=$validation|ConvertFrom-Json
   if(-not $v.valid -or $v.uncertain){throw 'Other outbox uncertainty; preserve'}
   Save "$release\quarantined-upload.json" $quarantine
   $null=$db.Read('BEGIN IMMEDIATE')
   try{
    if($db.Read("SELECT key FROM meta WHERE key='owner-output-quarantine/$op'").Length){throw 'Existing quarantine; reconcile'}
    $null=$db.Read("INSERT INTO meta VALUES('owner-output-quarantine/$op',CAST(X'$(Hex $quarantine)' AS TEXT))")
    $null=$db.Read("UPDATE meta SET value=CAST(X'$(Hex $b)' AS TEXT) WHERE key='$key'")
    $null=$db.Read('COMMIT')
   }catch{$null=$db.Read('ROLLBACK');throw}
   Save "$release\restored.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');inputsReplayed=0;uncertainUploadsResent=0;filesRetained=1;otherOutboxPreserved=$true}
  }finally{if($db){$db.Dispose()};$lease.Dispose()}
  if((Unknown) -cne $before.unknown -or (Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host){throw 'Unrelated custody changed'}
 }finally{
  if((Get-Service KhadangRouter).Status -eq 'Stopped'){Start-Service KhadangRouter}
  RestoreSupervisors $before
 }
 [IO.File]::ReadAllText("$release\restored.json");return
}
$before=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json
$restored=[IO.File]::ReadAllText("$release\restored.json")|ConvertFrom-Json
$end=[DateTimeOffset]::UtcNow.AddSeconds(50)
do{
 $s=Status;$target=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $pin})
 if([DateTimeOffset]$s.at -gt [DateTimeOffset]$restored.at -and [DateTimeOffset]$s.lastPollAttempt -gt [DateTimeOffset]$restored.at){break}
 Start-Sleep -Milliseconds 500
}while([DateTimeOffset]::UtcNow -lt $end)
if((Get-Service KhadangRouter).Status -ne 'Running' -or [DateTimeOffset]$s.at -le [DateTimeOffset]$restored.at -or [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or
 [DateTimeOffset]$s.lastPollAttempt -le [DateTimeOffset]$restored.at -or -not $s.nativeTransportHealthy -or -not $s.backgroundHealthy -or
 $s.nativeLinuxPid -ne 479 -or $target.Count -ne 1 -or $target[0].held -or -not $target[0].claudeConnected -or $target[0].pid -ne $before.pid -or
 (Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host -or (Unknown) -cne $before.unknown){throw 'Fresh topic health/custody not confirmed'}
$otherHeld=@($s.nativeSessions|Where-Object {$_.held -and $_.binding.ThreadId -ne $pin}|ForEach-Object {$_.binding.ThreadId})
if(($otherHeld|Sort-Object|ConvertTo-Json -Compress) -cne (@($before.held|Where-Object {$_ -ne $pin})|Sort-Object|ConvertTo-Json -Compress)){throw 'Other-topic holds changed'}
RestoreSupervisors $before
Save "$release\verified.json" @{at=$s.at;chat=-1003550185469;topic=1876;connected=$true;held=$false;nativePid=$target[0].pid;registryPreserved=$true;unknownReceiptsPreserved=$true;inputsReplayed=0;uncertainUploadsResent=0;tests=$before.tests}
[IO.File]::ReadAllText("$release\verified.json")
