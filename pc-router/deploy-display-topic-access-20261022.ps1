param([Parameter(Mandatory=$true)][ValidateSet('prepare','stage','resume-stage','probe','activate','verify','rollback')][string]$Phase)
# Owner-requested normal access for the exact sender of Display messages 540-542.
# Topic 2 only. No owner rights, forum/global grant or historical input replay.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote';$temp='C:\Users\pou\AppData\Local\Temp'
$release="$root\grant-display-aida-ledger-20261022"
$oldCode='72B601927C23C67F46A232627B14420BDE79EB80A8BE0D6E3AE48F18A8C683C5'
$code='D0028E06D93781B15BD202B7360636C9B401A87BE82C262AFB7E27AF3EC4BAD3'
$oldPolicy='6271B521E9C069618384FD6632088C7FAF06FDD1CBCB8A7CBCDC36E77215192C'
$zip='DA2E51DAF1334EF29EC0B19E023D32722CDC2613DC4745FEE612FFD2B2FC24C8'
$grantKey='topic-participants/-1004393585932/2'
$pin='01a11701-137a-76c2-b997-5f5d0a9c96e0';$forum=[long]-1004393585932;$person=[long]514280801
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$helper="$temp\deploy-switch-isolation-20261014.ps1"
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helper changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Unknown','Bindings','HostIdentity','ExactTask','Fenced','Hex')){$d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true);. ([ScriptBlock]::Create($d.Extent.Text))}
$helper="$temp\deploy-web-menu-proof-20261022.ps1"
if((Get-FileHash $helper).Hash -ne 'C02D912692A3811174D8B6190F8AF37982E4543F44C05D88A13E3556BF6F0958'){throw 'Reviewed lifecycle helpers changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Status','SafeStop','NormalStart','RestoreSupervisors')){$d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true);. ([ScriptBlock]::Create($d.Extent.Text))}
LoadSql "$native\inspect-state.ps1" 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
function Original{if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $oldCode -or (Get-FileHash "$root\config.json").Hash -ne $oldPolicy){throw 'Production changed; preserve'}}
function Member{
 $m=[IO.File]::ReadAllText("$root\grant-display-aida-20261022\member-verified.json")|ConvertFrom-Json
 if($m.chat -ne $forum -or $m.topic -ne 2 -or $m.id -ne $person -or $m.username -ine 'Aida_nz' -or $m.is_bot -or $m.status -notin @('member','administrator','creator') -or [DateTimeOffset]$m.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-15)){throw 'Fresh exact member proof required'}
 if([RouterReceipts]::Read("SELECT id FROM updates WHERE id IN (759324176,759324177,759324178) AND status='denied' AND json_extract(payload,'$.message.chat.id')=$forum AND json_extract(payload,'$.message.message_thread_id')=2 AND json_extract(payload,'$.message.from.id')=$person AND json_extract(payload,'$.message.from.is_bot')=0").Length -ne 3){throw 'Original sender/messages changed; no grant or replay'}
 $b=[RouterReceipts]::Read("SELECT payload FROM bindings WHERE chat=$forum AND topic=2")[0][0]|ConvertFrom-Json
 if($b.ThreadId -ne $pin -or $b.Workspace -cne '/Users/pouya/.openclaw/workspace/futek-ai/display-source-code-recovery' -or $b.Backend -ne 'codex' -or $b.Runtime -ne 'linux'){throw 'Exact existing Display binding required'}
}
function CandidateGrant{
 $g=[IO.File]::ReadAllText("$release\candidate-grant.json")|ConvertFrom-Json
 if(@($g.PSObject.Properties).Count -ne 6 -or $g.Schema -ne 'ccrelay.topic_conversation_access.v1' -or $g.OwnerId -ne 110123423 -or $g.Chat -ne $forum -or $g.Topic -ne 2 -or $g.Workspace -cne '/Users/pouya/.openclaw/workspace/futek-ai/display-source-code-recovery' -or @($g.ParticipantIds).Count -ne 1 -or $g.ParticipantIds[0] -ne $person){throw 'Only the exact owner-approved topic/project grant permitted'}
}
if($Phase -eq 'prepare'){
 Original;Member;if(Test-Path $release){throw 'Existing release; reconcile'}
 if([RouterReceipts]::Read("SELECT key FROM meta WHERE key='$grantKey'").Length){throw 'Existing topic grant preserved; no overwrite'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 if((Get-FileHash "$temp\router-topic-access-ledger-20261022.zip").Hash -ne $zip){throw 'Candidate changed'}
 Copy-Item "$temp\router-topic-access-ledger-20261022.zip" "$release\candidate.zip";Protect "$release\candidate.zip"
 if((Get-FileHash "$release\candidate.zip").Hash -ne $zip){throw 'Sealed archive differs'}
 Add-Type -AssemblyName System.IO.Compression.FileSystem;$archive=[IO.Compression.ZipFile]::OpenRead("$release\candidate.zip")
 try{foreach($e in $archive.Entries){if($e.FullName -notmatch '^[A-Za-z0-9._-]+$' -or $e.Length -gt 200MB -or ($e.ExternalAttributes -shr 16 -band 0xF000) -eq 0xA000){throw 'Unexpected archive entry'}}}finally{$archive.Dispose()}
 [IO.Compression.ZipFile]::ExtractToDirectory("$release\candidate.zip","$release\candidate");Protect "$release\candidate" $true
 if((Get-FileHash "$release\candidate\KhadangRouter.dll").Hash -ne $code){throw 'Sealed code differs'}
 $focused=(& "$release\candidate\KhadangRouter.exe" --self-test-participants)-join "`n";if($LASTEXITCODE -or $focused -notmatch '^Passed 165 participant-access checks'){throw 'Participant authorization regressions failed'}
 $tests=(& "$release\candidate\KhadangRouter.exe" --self-test)-join "`n";if($LASTEXITCODE -or $tests -notmatch '^All 1673 PC-router checks passed'){throw 'Full Windows regressions failed'}
 Copy-Item "$root\config.json" "$release\previous-config.json";Protect "$release\previous-config.json"
 Save "$release\candidate-grant.json" @{Schema='ccrelay.topic_conversation_access.v1';OwnerId=[long]110123423;Chat=$forum;Topic=2;Workspace='/Users/pouya/.openclaw/workspace/futek-ai/display-source-code-recovery';ParticipantIds=@($person)};CandidateGrant
 Save "$release\prepared.json" @{code=$code;policy=$oldPolicy;grant=(Get-FileHash "$release\candidate-grant.json").Hash;focused=$focused;tests=$tests;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='prepared';tests=$tests;focused=$focused;productionChanged=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'rollback'){
 if((Get-FileHash "$release\previous-bin\KhadangRouter.dll").Hash -ne $oldCode -or (Get-FileHash "$release\previous-config.json").Hash -ne $oldPolicy -or (Test-Path "$release\rolled-back-bin")){throw 'Exact rollback required'}
 $before=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json;SafeStop
 Move-Item "$root\bin" "$release\rolled-back-bin";Move-Item "$release\previous-bin" "$root\bin";Copy-Item "$release\previous-config.json" "$root\config.json" -Force;Protect "$root\config.json"
 Copy-Item "$release\previous-probe.json" "$root\state\probe.json" -Force;Protect "$root\state\probe.json";NormalStart;RestoreSupervisors $before
 @{phase='rolled-back';inputReplay=0}|ConvertTo-Json -Compress;return
}
if($Phase -in @('stage','resume-stage')){
 Original;Member;CandidateGrant
 $prep=[IO.File]::ReadAllText("$release\prepared.json")|ConvertFrom-Json
 if((Get-FileHash "$release\candidate-grant.json").Hash -ne $prep.grant){throw 'Reviewed candidate grant changed'}
 if($Phase -eq 'stage'){
  if(Test-Path "$release\before.json"){throw 'Stage already attempted; reconcile'}
  $s=Status;if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or [DateTimeOffset]$s.lastPollAttempt -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 18 -or @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Fresh polling/native custody required'}
  Save "$release\before.json" @{host=(HostIdentity);unknown=(Unknown);bindings=(Bindings);held=@($s.nativeSessions|Where-Object held|ForEach-Object {$_.binding.ThreadId});startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled;at=[DateTimeOffset]::UtcNow.ToString('o')}
  Copy-Item "$root\state\probe.json" "$release\previous-probe.json";Protect "$release\previous-probe.json"
  try{SafeStop}catch{if((Get-Service KhadangRouter).Status -ne 'Stopped'){throw};Fenced}
 }else{
  Fenced;$before=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json
  if((Test-Path "$release\previous-bin") -or (Test-Path "$release\staged.json") -or (Unknown) -cne $before.unknown -or (Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host){throw 'Exact stopped-before-mutation continuation required'}
 }
 if([RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('dispatching','unknown')").Length -or [RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Unsettled effects; preserve'}
 Move-Item "$root\bin" "$release\previous-bin";New-Item -ItemType Directory "$root\bin"|Out-Null;Protect "$root\bin" $true;Copy-Item "$release\candidate\*" "$root\bin";Protect "$root\bin" $true
 LoadSql "$native\stage-dut-topic.ps1" '0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF' 'PcbaRegistry'
 $lease=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null
 try{
  $db=[PcbaRegistry]::new();if($db.Read("SELECT key FROM meta WHERE key='$grantKey'").Length){throw 'Existing grant preserved'}
  $grant=[IO.File]::ReadAllText("$release\candidate-grant.json")|ConvertFrom-Json
  $null=$db.Read("INSERT INTO meta(key,value) VALUES('$grantKey',CAST(X'$(Hex $grant)' AS TEXT))")
  Save "$release\grant-installed.json" @{key=$grantKey;grant=$grant;prior='absent';historicalInputsReplayed=0;at=[DateTimeOffset]::UtcNow.ToString('o')}
 }finally{if($db){$db.Dispose()};$lease.Dispose()}
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code -or (Get-FileHash "$root\config.json").Hash -ne $prep.policy){throw 'Staged artifacts differ'}
 Save "$release\staged.json" @{code=$code;policy=$prep.policy;at=[DateTimeOffset]::UtcNow.ToString('o')};@{phase='staged';nativeWorkersRestarted=0;historicalMessagesReplayed=0}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'probe'){
 Fenced;$stage=[IO.File]::ReadAllText("$release\staged.json")|ConvertFrom-Json
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --probe-service --config "'+$root+'\config.json"');StartMode='Manual'};if($r.ReturnValue){throw 'Probe path failed'};Start-Service KhadangRouter
 $end=[DateTimeOffset]::UtcNow.AddSeconds(55)
 do{$p=[IO.File]::ReadAllText("$root\state\probe.json")|ConvertFrom-Json;if($p.routerSha256 -eq $code -and $p.policySha256 -eq $stage.policy -and $p.verified -and [DateTimeOffset]$p.testedAt -gt [DateTimeOffset]$stage.at){break};Start-Sleep -Milliseconds 500}while([DateTimeOffset]::UtcNow -lt $end)
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 if($p.routerSha256 -ne $code -or $p.policySha256 -ne $stage.policy -or -not $p.verified -or -not $p.credentialAndCodeDenied -or -not $p.nativeWindowsSandboxVerified -or -not $p.nativeLinuxCommandOwnerVerified -or $p.modelInference -or $p.telegramPolling -or [DateTimeOffset]$p.testedAt -le [DateTimeOffset]$stage.at){throw 'Fresh SYSTEM proof required'}
 Save "$release\generic-proof.json" $p;$old=[IO.File]::ReadAllText("$release\previous-probe.json")|ConvertFrom-Json;if(-not $old.nativeLinuxClaudeContinuityVerified){throw 'Unchanged independent Claude acceptance required'}
 CandidateGrant
 foreach($field in @('nativeLinuxClaudeLaunchVerified','nativeLinuxClaudeToolOwnerVerified','nativeLinuxClaudeContinuityVerified','nativeLinuxClaudeAcceptance')){if($old.PSObject.Properties[$field]){$p|Add-Member $field $old.$field -Force}}
 $p|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='One topic-only conversation grant; native launch/dispatch/security settings, checkpoints and independent host unchanged';nativeModelTestsRerun=$false} -Force
 Save "$root\state\probe.json" $p;Save "$release\accepted.json" @{code=$code;policy=$stage.policy;at=[DateTimeOffset]::UtcNow.ToString('o')};@{phase='probe-accepted';modelsStarted=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'activate'){
 Fenced;$a=[IO.File]::ReadAllText("$release\accepted.json")|ConvertFrom-Json
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code -or (Get-FileHash "$root\config.json").Hash -ne $a.policy){throw 'Accepted artifacts changed'}
 NormalStart;@{phase='activated';nativeWorkersRestarted=0}|ConvertTo-Json -Compress;return
}
$before=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json;$a=[IO.File]::ReadAllText("$release\accepted.json")|ConvertFrom-Json;$end=[DateTimeOffset]::UtcNow.AddSeconds(55)
do{try{$s=Status}catch{$s=$null};if($s -and [DateTimeOffset]$s.at -gt [DateTimeOffset]$a.at -and [DateTimeOffset]$s.lastPollAttempt -gt [DateTimeOffset]$a.at){break};Start-Sleep -Milliseconds 500}while([DateTimeOffset]::UtcNow -lt $end)
if((Get-Service KhadangRouter).Status -ne 'Running' -or [DateTimeOffset]$s.at -le [DateTimeOffset]$a.at -or [DateTimeOffset]$s.lastPollAttempt -le [DateTimeOffset]$a.at -or [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 18 -or -not $s.nativeTransportHealthy -or -not $s.backgroundHealthy -or (Unknown) -cne $before.unknown -or (Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host -or @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Fresh polling/custody/health not confirmed'}
CandidateGrant
if([RouterReceipts]::Read("SELECT key FROM meta WHERE key='$grantKey' AND json_extract(value,'$.Schema')='ccrelay.topic_conversation_access.v1' AND json_extract(value,'$.Chat')=$forum AND json_extract(value,'$.Topic')=2 AND json_extract(value,'$.OwnerId')=110123423 AND json_extract(value,'$.ParticipantIds[0]')=$person AND json_array_length(value,'$.ParticipantIds')=1 AND json_extract(value,'$.Workspace')='/Users/pouya/.openclaw/workspace/futek-ai/display-source-code-recovery'").Length -ne 1){throw 'Live exact topic-only grant not confirmed'}
if((Get-FileHash "$root\config.json").Hash -ne $a.policy){throw 'Live policy changed'}
$held=@($s.nativeSessions|Where-Object held|ForEach-Object {$_.binding.ThreadId});if(($held|Sort-Object|ConvertTo-Json -Compress) -cne (@($before.held)|Sort-Object|ConvertTo-Json -Compress)){throw 'Unrelated holds changed'}
RestoreSupervisors $before;Member
Save "$release\verified.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');id=$person;username='Aida_nz';chat=$forum;topic=2;normalMessagingAndFiles=$true;ownerControlsGranted=$false;globalOrForumGrant=$false;routesPreserved=18;daemonPreserved=479;hostPreserved=$true;telegramPolling=$true;supervisorsRestored=$true;deniedInputsReplayed=0;newSenderRoundTripVerified=$false;policy=$a.policy;code=$code}
[IO.File]::ReadAllText("$release\verified.json")
