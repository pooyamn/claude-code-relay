param([Parameter(Mandatory=$true)][ValidateSet('prepare','fence','stage','probe','accept','activate','verify')][string]$Phase,
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{32}$')][string]$Generation,
 [Parameter(Mandatory=$true)][ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$CodeSha256)
# October 7 exact router-only release. Never stop/update the persistent Claude
# host or shared Codex daemon. Repair one observed unsent commentary answer;
# no native input, goal mutation, approval or replay is authorized here.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$nativeRoot='C:\ProgramData\OracovaNativeRemote';$hostRoot='C:\ProgramData\KhadangClaudeHost';$release="$root\release-$Generation"
$oldCode='A2E3E8B6B0A71684A513D270E0F06D21F3A12560B99CA67AF9032F969BCFE369'
$oldPolicy='70AB674B2B297489C6C5D78965335B3E5B738E15C7F9FBCAB9D51D1A78D8A205'
$oldStartup='2B4692B2F9DDD8B3F73A42186546D3B892326C32A319FF816586AC3ED94D5665'
$normal='"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Exact PC administrator required'}
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544');$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18');$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
$helper="$nativeRoot\migrate-lab-topics-65fc17bfcb9d47a190ab128b096bba5d.ps1"
foreach($entry in @(@($helper,'86F3D550CBA51D280CE2D6BCDCBD7A3C3B1B1CBB7435FE9BC54590C0F87E6513'),@("$nativeRoot\inspect-state.ps1",'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2'),@("$nativeRoot\stage-dut-topic.ps1",'0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF'))){if((Get-FileHash $entry[0]).Hash -ne $entry[1]){throw 'Protected helper changed'}}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save')){$def=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true);. ([ScriptBlock]::Create($def.Extent.Text))}
function Receipt([string]$Path,$Value){Save $Path $Value;Protect $Path $false}
function Sql([string]$File,[string]$Class){$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($File,[ref]$t,[ref]$e);$d=$a.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type' -and $n.Extent.Text.Contains("class $Class")},$true);if($e.Count -or -not $d){throw 'Protected SQL helper syntax'};if(-not ($Class -as [type])){& ([ScriptBlock]::Create($d.Extent.Text))}}
Sql "$nativeRoot\inspect-state.ps1" 'RouterReceipts'
function Original {if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $oldCode -or (Get-FileHash "$root\config.json").Hash -ne $oldPolicy -or (Get-FileHash "$nativeRoot\router-startup.ps1").Hash -ne $oldStartup){throw 'Production changed; preserve'}}
function Fenced {if((Get-Service KhadangRouter).Status.ToString() -ne 'Stopped' -or (Get-ScheduledTask Oracova-KhadangStartup).State.ToString() -ne 'Disabled'){throw 'Stopped fenced router required'}}
function HostIdentity {
 if((Get-Service KhadangClaudeHost).Status.ToString() -ne 'Running' -or (Get-FileHash "$hostRoot\bin\KhadangRouter.dll").Hash -ne $oldCode){throw 'Unchanged live Claude host required'}
 return @{host=(Get-Content "$hostRoot\host.json" -Raw -Encoding UTF8|ConvertFrom-Json);workers=@(Get-ChildItem "$hostRoot\state" -Directory|Sort-Object Name|ForEach-Object {Get-Content "$($_.FullName)\endpoint.json" -Raw -Encoding UTF8|ConvertFrom-Json})}
}
function Inputs {[RouterReceipts]::Read("SELECT id,kind,status FROM operations WHERE kind IN ('native/turn/start','native/turn/steer','claude/user/send-now','claude/control/answer') ORDER BY id")}
function Healthy {
 $s=Get-Content "$root\state\status.json" -Raw -Encoding UTF8|ConvertFrom-Json
 if((Get-Service KhadangRouter).Status.ToString() -ne 'Running' -or $s.unknown -or @($s.bindings).Count -ne 16 -or $s.nativeLinuxPid -ne 479 -or [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-2) -or @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Fresh sixteen routes/seven connections/unchanged Codex required'}
 foreach($row in [RouterReceipts]::Read("SELECT value FROM meta WHERE key LIKE 'bubble/%'")){
  $b=$row[0]|ConvertFrom-Json
  foreach($r in @($b)+@($b.pendingResponses)){if($r.sendUnknown -and $null -eq $r.message -or @($r.finalAnswer.Parts+$r.finalAnswer.Files|Where-Object SendUnknown).Count){throw 'Unknown output; preserve'}}
  if(@($b.pendingAnswers|ForEach-Object {$_.Parts+$_.Files}|Where-Object SendUnknown).Count){throw 'Unknown goal output; preserve'}
 }
 return $s
}
if($Phase -eq 'prepare'){
 Original;if(Test-Path "$release\prepared.json"){throw 'Already prepared; reconcile'}
 if((Get-FileHash "$release\candidate\KhadangRouter.dll").Hash -ne $CodeSha256){throw 'Reviewed candidate required'}
 $output=(& "$release\candidate\KhadangRouter.exe" --self-test) -join "`n";if($LASTEXITCODE -ne 0){throw 'Full Windows regression failed; production untouched'}
 Receipt "$release\prepared.json" @{code=$CodeSha256;tests=$output;passed=$true;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='prepared';tests=$output;productionChanged=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'fence'){
 Original;$p=Get-Content "$release\prepared.json" -Raw -Encoding UTF8|ConvertFrom-Json;if(-not $p.passed -or $p.code -ne $CodeSha256){throw 'Windows tests required'}
 if(Test-Path "$release\before.json"){throw 'Already fenced; reconcile'};$null=Healthy
 Receipt "$release\before.json" @{bindings=[RouterReceipts]::Read('SELECT payload FROM bindings ORDER BY chat,topic');inputs=(Inputs);host=(HostIdentity);bubbles=[RouterReceipts]::Read("SELECT key,value FROM meta WHERE key LIKE 'bubble/%'");startup=(Get-ScheduledTask Oracova-KhadangStartup).State.ToString();at=[DateTimeOffset]::UtcNow.ToString('o')}
 Copy-Item "$root\state\probe.json" "$release\previous-probe.json";Copy-Item "$root\config.json" "$release\previous-config.json"
 Disable-ScheduledTask Oracova-KhadangStartup|Out-Null;Stop-ScheduledTask Oracova-KhadangStartup
 try{Stop-Service KhadangRouter}catch{};(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 Receipt "$release\fenced.json" @{at=[DateTimeOffset]::UtcNow.ToString('o')};@{phase='fenced';nativeAgentsStopped=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'stage'){
 Fenced;Original;if(Test-Path "$release\staged.json"){throw 'Already staged; reconcile'}
 Sql "$nativeRoot\stage-dut-topic.ps1" 'PcbaRegistry'
 $exclusive=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null
 try{
  $db=[PcbaRegistry]::new();if([int]$db.Read("SELECT (SELECT COUNT(*) FROM operations WHERE status IN ('attempting','unknown') AND kind<>'telegram/editMessageText')+(SELECT COUNT(*) FROM updates WHERE status IN ('dispatching','unknown','received'))")[0][0]){throw 'Pending/uncertain effects; preserve'}
  if(-not (Test-Path "$release\previous-router.db")){$null=$db.Read("VACUUM INTO '$release\previous-router.db'");Protect "$release\previous-router.db" $false}
  # Recover the exact answer whose item was observed by the old router and
  # excluded solely by its commentary phase. Never infer acceptance from text.
  $pin='01a11701-137a-76c2-b997-5f5d0a9c96e0';$item='msg_05d25002b4c18463016ac6efdd2b2c87d29ac6513e686c7c65';$repair='goal-reply-repair/759322835'
  $text="Earlier reply to Progress ? (18:20 PDT):`n`n**About 60/100 (estimated).** 45 recovered modules compile and pass their checks. Clock-control recovery is in progress; the complete firmware build and hardware testing remain unfinished.`n"
  $binding=$db.Read("SELECT payload FROM bindings WHERE chat=-1004393585932 AND topic=2")[0][0]|ConvertFrom-Json
  $b=$db.Read("SELECT value FROM meta WHERE key='bubble/$pin'")[0][0]|ConvertFrom-Json
  # The goal may have moved to another turn while tests ran. In that case
  # confirm the historical displayed answer, not a cleared per-turn item set.
  $observed=$db.Read("SELECT id FROM operations WHERE kind='telegram/editMessageText' AND status='confirmed' AND json_extract(payload,'$.chat_id')=-1004393585932 AND json_extract(payload,'$.message_id')=105 AND instr(json_extract(payload,'$.text'),'About 60/100 (estimated).')>0 AND instr(json_extract(payload,'$.text'),'45 recovered modules compile and pass their checks.')>0")
  if($binding.ThreadId -ne $pin -or $binding.Backend -ne 'codex' -or $binding.Runtime -ne 'linux' -or $b.held -or ($b.completedItems -notcontains $item -and $observed.Length -lt 1) -or $db.Read("SELECT key FROM meta WHERE key='$repair'").Length -or
   $db.Read("SELECT id FROM operations WHERE kind='telegram/sendMessage' AND json_extract(payload,'$.chat_id')=-1004393585932 AND instr(json_extract(payload,'$.text'),'About 60/100')>0").Length -or
   $db.Read("SELECT id FROM updates WHERE id=759322835 AND status='accepted' AND json_extract(payload,'$.message.text')='Progress ?' AND json_extract(payload,'$.message.from.id')=110123423").Length -ne 1){throw 'Exact unsent observed reply/owner request required'}
  # Use the candidate's actual rendering/extraction so the repair follows the
  # same output code, not independently maintained Markdown conversion.
  $rendered=($text|& "$release\candidate\KhadangRouter.exe" --render-answer) -join "`n";if($LASTEXITCODE -ne 0){throw 'Candidate repair rendering failed'}
  $answer=$rendered|ConvertFrom-Json;if(-not $answer.Completed -or @($answer.Parts).Count -ne 1 -or @($answer.Files).Count -or -not $answer.Parts[0].Part.Text.Contains('About 60/100')){throw 'Rendered repair differs'}
  $b.pendingAnswers=@($b.pendingAnswers)+@($answer)
  $db.Read('BEGIN IMMEDIATE')|Out-Null
  try{
   $hex=([BitConverter]::ToString([Text.Encoding]::UTF8.GetBytes(($b|ConvertTo-Json -Depth 100 -Compress)))).Replace('-','');$null=$db.Read("UPDATE meta SET value=CAST(X'$hex' AS TEXT) WHERE key='bubble/$pin'")
   $receipt=@{item=$item;update=759322835;thread=$pin;nativeReplay=$false;at=[DateTimeOffset]::UtcNow.ToString('o')}|ConvertTo-Json -Compress;$hex=([BitConverter]::ToString([Text.Encoding]::UTF8.GetBytes($receipt))).Replace('-','');$null=$db.Read("INSERT INTO meta VALUES('$repair',CAST(X'$hex' AS TEXT))")
   $db.Read('COMMIT')|Out-Null
  }catch{$db.Read('ROLLBACK')|Out-Null;throw}
  Copy-Item "$root\bin" "$release\previous-bin" -Recurse
  Copy-Item "$release\candidate\*" "$root\bin" -Recurse -Force;Get-ChildItem "$root\bin" -Recurse -Force|ForEach-Object {Protect $_.FullName $_.PSIsContainer}
  Receipt "$release\staged.json" @{code=$CodeSha256;policy=(Get-FileHash "$root\config.json").Hash;at=[DateTimeOffset]::UtcNow.ToString('o');repairQueued=$true}
 }finally{if($db){$db.Dispose()};$exclusive.Dispose()}
 @{phase='staged';nativeInputsSent=0;hostUpdated=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'probe'){
 Fenced;$svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --probe-service --config "'+$root+'\config.json"');StartMode='Manual'};if($r.ReturnValue){throw 'Probe service path failed'}
 Start-Service KhadangRouter;@{phase='probe-running';modelInference=$false;telegramPolling=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'accept'){
 Fenced;$stage=Get-Content "$release\staged.json" -Raw -Encoding UTF8|ConvertFrom-Json;$p=Get-Content "$root\state\probe.json" -Raw -Encoding UTF8|ConvertFrom-Json;$old=Get-Content "$release\previous-probe.json" -Raw -Encoding UTF8|ConvertFrom-Json
 if($p.routerSha256 -ne $CodeSha256 -or $p.policySha256 -ne $oldPolicy -or -not $p.verified -or -not $p.credentialAndCodeDenied -or -not $p.aclProbeWithoutProviderSandbox -or -not $p.nativeWindowsSandboxVerified -or -not $p.nativeLinuxCodexVerified -or -not $p.nativeLinuxCommandOwnerVerified -or -not $p.nativePersistentClaudeHostAclDenied -or $p.modelInference -or $p.telegramPolling -or [DateTimeOffset]$p.testedAt -le [DateTimeOffset]$stage.at -or $old.routerSha256 -ne $oldCode -or $old.policySha256 -ne $oldPolicy -or -not $old.nativeLinuxClaudeContinuityVerified){throw 'Fresh OS proof and prior native acceptance required'}
 Copy-Item "$root\state\probe.json" "$release\generic-proof.json"
 foreach($field in @('nativeLinuxClaudeLaunchVerified','nativeLinuxClaudeToolOwnerVerified','nativeLinuxClaudeContinuityVerified','nativeLinuxClaudeAcceptance')){if($old.PSObject.Properties[$field]){$p|Add-Member $field $old.$field -Force}}
 $p|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Router-only goal reply rendering; protected config, native connector and independent host unchanged';priorCode=$oldCode;modelTestsRerun=$false} -Force
 Receipt "$root\state\probe.json" $p;Receipt "$release\accepted.json" @{code=$CodeSha256;policy=$oldPolicy;at=[DateTimeOffset]::UtcNow.ToString('o')};@{phase='accepted';hostUpdated=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'activate'){
 Fenced;if(-not (Test-Path "$release\accepted.json") -or (Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $CodeSha256 -or (Get-FileHash "$root\config.json").Hash -ne $oldPolicy){throw 'Exact accepted code/config required'};$null=HostIdentity
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=$normal;StartMode='Manual'};if($r.ReturnValue){throw 'Normal service path failed'}
 Start-Service KhadangRouter;@{phase='activated';nativeInputsSent=0}|ConvertTo-Json -Compress;return
}
$s=Healthy;$before=Get-Content "$release\before.json" -Raw -Encoding UTF8|ConvertFrom-Json
if(((HostIdentity)|ConvertTo-Json -Depth 100 -Compress) -cne ($before.host|ConvertTo-Json -Depth 100 -Compress) -or
 ([RouterReceipts]::Read('SELECT payload FROM bindings ORDER BY chat,topic')|ConvertTo-Json -Compress) -cne ($before.bindings|ConvertTo-Json -Compress) -or
 ((Inputs)|ConvertTo-Json -Compress) -cne ($before.inputs|ConvertTo-Json -Compress)){throw 'Host generation, registry or input receipts changed; inspect'}
$sent=[RouterReceipts]::Read("SELECT json_extract(result,'$.message_id') FROM operations WHERE kind='telegram/sendMessage' AND status='confirmed' AND json_extract(payload,'$.chat_id')=-1004393585932 AND json_extract(payload,'$.message_thread_id')=2 AND instr(json_extract(payload,'$.text'),'About 60/100')>0")
if($sent.Length -ne 1 -or -not $sent[0][0]){throw 'Exact repaired reply delivery not confirmed'}
foreach($row in $before.bubbles){$b=$row[1]|ConvertFrom-Json;if($b.held -and -not ([RouterReceipts]::Read("SELECT value FROM meta WHERE key='$($row[0])'")[0][0]|ConvertFrom-Json).held){throw 'Existing safety hold changed'}}
Receipt "$release\verified.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');routes=16;nativePidsAndHostEpochsUnchanged=$true;nativeInputsSent=0;replyMessage=[int]$sent[0][0];existingHoldsPreserved=$true}
if($before.startup -ne 'Disabled'){Enable-ScheduledTask Oracova-KhadangStartup|Out-Null;Start-ScheduledTask Oracova-KhadangStartup}
@{phase='verified';routes=16;repairMessage=[int]$sent[0][0];nativeInputsSent=0;hostUpdated=$false;startupRestored=$true}|ConvertTo-Json -Compress
