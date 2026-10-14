param([Parameter(Mandatory=$true)][ValidateSet('prepare','stage','reconcile-stage','probe','activate','verify')][string]$Phase,
 [Parameter(Mandatory=$true)][ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$ManifestSha256)
# Exact Headfix repair: preserve native custody and other-topic uncertainty.
# A failed BEFORE-LAUNCH control can continue only after absence-of-effects
# evidence, retaining its reserved destination and original captured handoff.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote'
$release="$root\release-switch-isolation-20261014";$temp='C:\Users\pou\AppData\Local\Temp'
$oldCode='BA71E22CB633BCC4070EB832EC8E846F78A573F0D65FD164DBC1A6E86F9D00A2'
$code='27AF49C2BBB2409BB33DA9D49BE28B123F8480955ED62DE82C91C6A8FDBCC946'
$policyHash='70AB674B2B297489C6C5D78965335B3E5B738E15C7F9FBCAB9D51D1A78D8A205'
$pin='01a135f7-8d8a-7243-9349-0aa41e1ed02f';$target='9140d09f-b2ac-40da-bc1a-197f3e4a5a25'
$intentKey='model-switch/-1003550185469/13949';$bubbleKey='bubble/'+$pin
$normal='"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
function Protect($Path,[bool]$Directory=$false){
 $acl=if($Directory){[Security.AccessControl.DirectorySecurity]::new()}else{[Security.AccessControl.FileSecurity]::new()}
 $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'));$acl.SetAccessRuleProtection($true,$false)
 foreach($sid in @('S-1-5-18','S-1-5-32-544')){
  $r=if($Directory){[Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','ContainerInherit,ObjectInherit','None','Allow')}else{[Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','Allow')}
  $acl.AddAccessRule($r)
 };Set-Acl -LiteralPath $Path -AclObject $acl
}
function Save($Path,$Value){[IO.File]::WriteAllText($Path,($Value|ConvertTo-Json -Depth 100),[Text.UTF8Encoding]::new($false));Protect $Path}
function LoadSql($Path,$Digest,$Class){
 if((Get-FileHash $Path).Hash -ne $Digest){throw 'Protected database helper changed'}
 $a=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$null,[ref]$null)
 $d=$a.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type' -and $n.Extent.Text -like ('*class '+$Class+'*')},$true)
 if(-not ($Class -as [type])){& ([ScriptBlock]::Create($d.Extent.Text))}
}
Write-Output 'Deployment: loading protected read-only inspector'
LoadSql "$native\inspect-state.ps1" 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
Write-Output 'Deployment: inspector ready'
function Original{if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $oldCode -or (Get-FileHash "$root\config.json").Hash -ne $policyHash){throw 'Production changed; preserve'}}
function Unknown{[RouterReceipts]::Read("SELECT id,kind,payload,status FROM operations WHERE status='unknown' AND kind<>'telegram/editMessageText' ORDER BY +id")|ConvertTo-Json -Compress}
function Bindings{[RouterReceipts]::Read('SELECT payload FROM bindings ORDER BY chat,topic')|ConvertTo-Json -Compress}
function HostIdentity{[IO.File]::ReadAllText('C:\ProgramData\KhadangClaudeHost\host.json')}
function Hex($Value){([BitConverter]::ToString([Text.Encoding]::UTF8.GetBytes(($Value|ConvertTo-Json -Depth 100 -Compress)))).Replace('-','')}
function ExactTask($Name){
 $found=@($script:taskScheduler.GetFolder('\').GetTasks(1)|Where-Object {$_.Name -ceq $Name})
 if($found.Count -ne 1){throw 'Exact existing scheduled task required'};return ,$found[0]
}
function Fenced{if((Get-Service KhadangRouter).Status -ne 'Stopped' -or (ExactTask 'Oracova-KhadangStartup').Enabled -or (ExactTask 'Oracova-KhadangWatchdog').Enabled){throw 'Fenced router required'}}
if($Phase -ne 'prepare'){Write-Output 'Deployment: connecting task scheduler';$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect();Write-Output 'Deployment: scheduler ready'}
if($Phase -eq 'prepare'){
 Original;if(Test-Path $release){throw 'Existing release; inspect instead of repeating'}
 if((Get-FileHash "$temp\router-switch-manifest-20261014.json").Hash -ne $ManifestSha256){throw 'Reviewed manifest required'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 Copy-Item "$temp\router-switch-manifest-20261014.json" "$release\manifest.json"
 if((Get-FileHash "$release\manifest.json").Hash -ne $ManifestSha256){throw 'Copied manifest mismatch'}
 New-Item -ItemType Directory "$release\candidate"|Out-Null;Protect "$release\candidate" $true
 $m=Get-Content "$release\manifest.json" -Raw -Encoding UTF8|ConvertFrom-Json
 foreach($file in $m.PSObject.Properties){
  if($file.Name -notmatch '^[A-Za-z0-9_.-]+$'){throw 'Invalid candidate filename'}
  $p=Join-Path "$release\candidate" $file.Name;Copy-Item (Join-Path "$temp\router-switch-isolation-20261014" $file.Name) $p
  if((Get-FileHash $p).Hash -ne $file.Value){throw 'Sealed candidate mismatch'}
 }
 if((Get-FileHash "$release\candidate\KhadangRouter.dll").Hash -ne $code){throw 'Wrong candidate code'}
 $tests=(& "$release\candidate\KhadangRouter.exe" --self-test) -join "`n"
 if($LASTEXITCODE -ne 0){throw 'Sealed full Windows tests failed; no deployment'}
 Save "$release\prepared.json" @{code=$code;tests=$tests;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='prepared';tests=$tests;productionChanged=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'stage'){
 Write-Output 'Stage: checking production'
 Original;if(-not (Test-Path "$release\prepared.json") -or (Test-Path "$release\before.json")){throw 'Fresh prepared stage required'}
 $s=Get-Content "$root\state\status.json" -Raw -Encoding UTF8|ConvertFrom-Json
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 17){throw 'Fresh exact registry/native daemon required'}
 Write-Output 'Stage: snapshotting unchanged native custody and task state'
 $hostSnapshot=HostIdentity;Write-Output 'Stage: native identity captured'
 $unknownSnapshot=Unknown;Write-Output 'Stage: uncertain receipt captured'
 $bindingsSnapshot=Bindings;Write-Output 'Stage: bindings captured'
 $startupEnabled=(ExactTask 'Oracova-KhadangStartup').Enabled;Write-Output 'Stage: startup state captured'
 $watchdogEnabled=(ExactTask 'Oracova-KhadangWatchdog').Enabled;Write-Output 'Stage: watchdog state captured'
 Save "$release\before.json" @{host=$hostSnapshot;unknown=$unknownSnapshot;bindings=$bindingsSnapshot;startup=$startupEnabled;watchdog=$watchdogEnabled;at=[DateTimeOffset]::UtcNow.ToString('o')}
 Write-Output 'Stage: protected snapshot written'
 Copy-Item "$root\state\probe.json" "$release\previous-probe.json"
 Write-Output 'Stage: fencing router-only lifecycle'
 foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $name;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
 try{Stop-Service KhadangRouter}catch{};(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 LoadSql "$native\stage-dut-topic.ps1" '0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF' 'PcbaRegistry'
 $lease=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null
 try{
  $db=[PcbaRegistry]::new()
  Write-Output 'Stage: verifying exact prelaunch evidence'
  if($db.Read("SELECT id FROM updates WHERE status IN ('received','dispatching','unknown')").Length -or $db.Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Unsettled native/intake effects; preserve'}
  $route=$db.Read('SELECT payload FROM bindings WHERE chat=-1003550185469 AND topic=13949')[0][0]|ConvertFrom-Json
  $intent=$db.Read("SELECT value FROM meta WHERE key='$intentKey'")[0][0]|ConvertFrom-Json
  $bubble=$db.Read("SELECT value FROM meta WHERE key='$bubbleKey'")[0][0]|ConvertFrom-Json
  $u=$db.Read('SELECT payload,status FROM updates WHERE id=759323066')[0];$msg=($u[0]|ConvertFrom-Json).message
  $policy=Get-Content "$root\config.json" -Raw -Encoding UTF8|ConvertFrom-Json
  $checkpoint=$policy.LinuxClaude.PackageRoot+'\handoff-'+$target+'.json'
  if($route.ThreadId -ne $pin -or $route.Backend -ne 'codex' -or $route.Runtime -ne 'linux' -or $route.Workspace -ne '/Users/pouya/.openclaw/workspace/headfix' -or
   $intent.phase -ne 'opening-destination' -or $intent.requestedModel -ne 'opus' -or $intent.source.ThreadId -ne $pin -or $intent.target.ThreadId -ne $target -or $intent.target.Topic -ne 13949 -or $intent.target.Chat -ne -1003550185469 -or $intent.target.Workspace -cne $route.Workspace -or
   $u[1] -ne 'held-no-replay' -or $msg.text.Trim().ToLowerInvariant() -ne 'cc model opus' -or $msg.from.id -ne $policy.OwnerId -or $msg.from.is_bot -or $msg.chat.id -ne $route.Chat -or $msg.message_thread_id -ne $route.Topic -or $msg.forward_origin -or $msg.sender_chat -or $msg.via_bot -or
   -not $bubble.held -or $bubble.busy -or $bubble.sendUnknown -or @($bubble.pendingResponses).Count -or @($bubble.pendingAnswers).Count -or @($bubble.finalAnswer.Parts+$bubble.finalAnswer.Files|Where-Object SendUnknown).Count -or
   (Test-Path $checkpoint) -or (Test-Path "C:\ProgramData\KhadangClaudeHost\state\$target") -or
   $db.Read("SELECT key FROM meta WHERE instr(key,'$target')>0 AND key NOT LIKE 'model-slot/%'").Length -or
   $db.Read("SELECT id FROM operations WHERE kind LIKE 'claude/%' AND instr(payload,'$target')>0").Length){throw 'Exact original prelaunch failure/no native effect required'}
  $history='/Users/pouya/.claude/projects/-Users-pouya--openclaw-workspace-headfix/'+$target+'.jsonl'
  & wsl.exe -d Ubuntu-24.04 -u pou --exec /usr/bin/python3 -I -c "from pathlib import Path; import sys; sys.exit(12 if Path('$history').exists() else 0)"
  if($LASTEXITCODE -ne 0){throw 'Reserved native history exists; no fresh continuation'}
  foreach($row in $db.Read("SELECT kind,payload FROM operations WHERE status='unknown' AND kind<>'telegram/editMessageText'")){
   $effect=$row[1]|ConvertFrom-Json
   if($row[0] -notin @('telegram/sendMessage','telegram/sendRichMessage','telegram/sendPhoto','telegram/sendDocument') -or $effect.chat_id -ge 0 -or $effect.message_thread_id -le 0 -or ($effect.chat_id -eq $route.Chat -and $effect.message_thread_id -eq $route.Topic)){throw 'Native/unscoped/Headfix uncertainty; preserve'}
  }
  $first=Get-Content "$root\state\input-held-759323066.json" -Raw -Encoding UTF8|ConvertFrom-Json
  if($first.errorType -ne 'InvalidDataException'){throw 'Failure was not the known prelaunch admission rejection'}
  $null=$db.Read("VACUUM INTO '$release\previous-router.db'")
  Save "$release\prelaunch-evidence.json" @{originalIntent=$intent;originalBubble=$bubble;originalUpdateStatus=$u[1];historyAbsent=$true;checkpointAbsent=$true;hostStateAbsent=$true;noNativeEffects=$true}
  $intent.phase='prelaunch-reconciled';$intent|Add-Member nativeLaunchAttempted $false -Force;$intent|Add-Member handoffSent $false -Force
  $bubble.held=$false;$bubble.status='Ready';$bubble.tail+="`nOwner-requested repair: continuing original model switch; no prior Claude launch or handoff occurred.`n"
  $db.Read('BEGIN IMMEDIATE')|Out-Null
  try{
   $null=$db.Read("UPDATE meta SET value=CAST(X'$(Hex $intent)' AS TEXT) WHERE key='$intentKey'")
   $null=$db.Read("UPDATE meta SET value=CAST(X'$(Hex $bubble)' AS TEXT) WHERE key='$bubbleKey'")
   # Only the proven prelaunch control returns to dispatch. Held later text
   # and all uncertain actions are preserved, never automatically resent.
   $null=$db.Read("UPDATE updates SET status='received' WHERE id=759323066 AND status='held-no-replay'")
   $db.Read('COMMIT')|Out-Null
  }catch{$db.Read('ROLLBACK')|Out-Null;throw}
  Copy-Item "$root\bin" "$release\previous-bin" -Recurse
  Copy-Item "$release\candidate\*" "$root\bin" -Force;Get-ChildItem "$root\bin" -File|ForEach-Object {Protect $_.FullName}
 }finally{if($db){$db.Dispose()};$lease.Dispose()}
 $before=Get-Content "$release\before.json" -Raw -Encoding UTF8|ConvertFrom-Json
 if((Unknown) -cne $before.unknown -or (Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host){throw 'Unrelated uncertainty/registry/native host changed'}
 Save "$release\staged.json" @{code=$code;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='staged';nativeHostChanged=$false;uncertainActionsReplayed=0;firstHandoffPending=$true}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'reconcile-stage'){
 Fenced
 if((Test-Path "$release\staged.json") -or -not (Test-Path "$release\prelaunch-evidence.json") -or
  (Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code -or (Get-FileHash "$root\config.json").Hash -ne $policyHash){throw 'Exact interrupted stage required'}
 $before=Get-Content "$release\before.json" -Raw -Encoding UTF8|ConvertFrom-Json
 if((Unknown) -cne $before.unknown -or (Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host){throw 'Original snapshot changed'}
 $i=[RouterReceipts]::Read("SELECT value FROM meta WHERE key='$intentKey'")[0][0]|ConvertFrom-Json
 if($i.phase -ne 'prelaunch-reconciled' -or $i.source.ThreadId -ne $pin -or $i.target.ThreadId -ne $target -or $i.nativeLaunchAttempted -or $i.handoffSent -or
  [RouterReceipts]::Read('SELECT status FROM updates WHERE id=759323066')[0][0] -ne 'received' -or
  [RouterReceipts]::Read("SELECT id FROM operations WHERE kind LIKE 'claude/%' AND instr(payload,'$target')>0").Length){throw 'Prelaunch continuation changed; do not repeat'}
 Save "$release\staged.json" @{code=$code;at=[DateTimeOffset]::UtcNow.ToString('o');snapshotEncodingCorrected=$true}
 @{phase='stage-reconciled';newNativeInputs=0;registryAndUncertaintyUnchanged=$true}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'probe'){
 Fenced;$svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --probe-service --config "'+$root+'\config.json"');StartMode='Manual'}
 if($r.ReturnValue){throw 'Probe service path failed'};Start-Service KhadangRouter
 $stage=Get-Content "$release\staged.json" -Raw -Encoding UTF8|ConvertFrom-Json;$end=[DateTimeOffset]::UtcNow.AddSeconds(50)
 do{$p=Get-Content "$root\state\probe.json" -Raw -Encoding UTF8|ConvertFrom-Json;if($p.routerSha256 -eq $code -and $p.verified -and [DateTimeOffset]$p.testedAt -gt [DateTimeOffset]$stage.at){break};Start-Sleep -Seconds 1}while([DateTimeOffset]::UtcNow -lt $end)
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 if($p.routerSha256 -ne $code -or $p.policySha256 -ne $policyHash -or -not $p.verified -or -not $p.credentialAndCodeDenied -or -not $p.nativeWindowsSandboxVerified -or -not $p.nativeLinuxCommandOwnerVerified -or $p.modelInference -or $p.telegramPolling -or [DateTimeOffset]$p.testedAt -le [DateTimeOffset]$stage.at){throw 'Fresh exact OS proof required'}
 $old=Get-Content "$release\previous-probe.json" -Raw -Encoding UTF8|ConvertFrom-Json
 if(-not $old.nativeLinuxClaudeContinuityVerified){throw 'Prior unchanged native acceptance required'}
 Save "$release\generic-proof.json" $p
 foreach($field in @('nativeLinuxClaudeLaunchVerified','nativeLinuxClaudeToolOwnerVerified','nativeLinuxClaudeContinuityVerified','nativeLinuxClaudeAcceptance')){if($old.PSObject.Properties[$field]){$p|Add-Member $field $old.$field -Force}}
 $p|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Router-only exact-topic switch admission; protected native host, connectors and policy unchanged';nativeModelTestsRerun=$false} -Force
 Save "$root\state\probe.json" $p;Save "$release\accepted.json" @{code=$code;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='probe-accepted';modelInference=$false;telegramPolling=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'activate'){
 Fenced;if(-not (Test-Path "$release\accepted.json") -or (Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code -or (Get-FileHash "$root\config.json").Hash -ne $policyHash){throw 'Exact accepted candidate required'}
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=$normal;StartMode='Manual'}
 if($r.ReturnValue){throw 'Normal service path failed'};Start-Service KhadangRouter
 @{phase='activated';sourceHistoryPreserved=$true;reservedDestination=$target}|ConvertTo-Json -Compress;return
}
$s=Get-Content "$root\state\status.json" -Raw -Encoding UTF8|ConvertFrom-Json;$before=Get-Content "$release\before.json" -Raw -Encoding UTF8|ConvertFrom-Json
$intent=[RouterReceipts]::Read("SELECT value FROM meta WHERE key='$intentKey'")[0][0]|ConvertFrom-Json
$h=@($s.nativeSessions|Where-Object {$_.binding.Chat -eq -1003550185469 -and $_.binding.Topic -eq 13949})
if((Get-Service KhadangRouter).Status -ne 'Running' -or [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 17 -or
 $h.Count -ne 1 -or $h[0].binding.ThreadId -ne $target -or $h[0].binding.Backend -ne 'claude' -or -not $h[0].claudeConnected -or $h[0].held -or $intent.phase -ne 'committed' -or (HostIdentity) -cne $before.host -or (Unknown) -cne $before.unknown){throw 'Actual exact switch/unchanged host/retained uncertainty not confirmed'}
$sent=[RouterReceipts]::Read("SELECT id FROM operations WHERE kind='claude/user/send-now' AND status='confirmed' AND json_extract(payload,'$.SessionId')='$target'")
if($sent.Length -ne 1){throw 'Exactly one confirmed first handoff required'}
foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$enabled=if($name -like '*Startup'){$before.startup}else{$before.watchdog};if($enabled){(ExactTask $name).Enabled=$true}}
Save "$release\verified.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');routes=17;headfixBackend='claude';session=$target;firstHandoffs=1;unrelatedUnknownRetained=$true;nativeHostAndCodexPreserved=$true;laterHeldTextReplayed=$false}
Get-Content "$release\verified.json" -Raw
