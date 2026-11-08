$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$hostRoot='C:\ProgramData\KhadangClaudeHost';$native='C:\ProgramData\OracovaNativeRemote'
$pin='8cd2d34c-0805-4705-8197-d11de0728499';$workspace='/Users/pouya/.openclaw/workspace/motorcontrol-plant'
$release=$root+'\recover-motor-question-20261107';$folder=$hostRoot+'\state\'+$pin
$expected='5d36e3c696cfbbe205895dde469c223384e2d40b8ff5cb0902062647ddf09482'
$history='/Users/pouya/.claude/projects/-Users-pouya--openclaw-workspace-motorcontrol-plant/'+$pin+'.jsonl'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if(-not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$helper='C:\Users\pou\AppData\Local\Temp\deploy-switch-isolation-20261014.ps1'
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helpers changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Hex','Bindings','Unknown')){$d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true);. ([scriptblock]::Create($d.Extent.Text))}
LoadSql ($native+'\inspect-state.ps1') 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
LoadSql ($native+'\stage-dut-topic.ps1') '0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF' 'PcbaRegistry'
function HistoryProof{
 $output=(& C:\Windows\System32\wsl.exe -d Ubuntu-24.04 -u pou --exec /usr/bin/sha256sum $history)-join ''
 if($LASTEXITCODE -or -not $output.StartsWith($expected+' ')){throw 'Audited exact history changed'}
 $writers=(& C:\Windows\System32\wsl.exe -d Ubuntu-24.04 -u pou --exec /usr/bin/pgrep -af ('[c]laude.*'+$pin+'|[p]c_claude_stdio.py.*'+$pin)) -join ''
 if($LASTEXITCODE -ne 1 -or $writers){throw 'Existing exact native producer must not be replaced'}
}
function Status{Get-Content -Raw ($root+'\state\status.json')|ConvertFrom-Json}
function IdlePeers{
 $s=Status;$claude=@($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude'})
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddSeconds(-30) -or $claude.Count -ne 9 -or
  @($claude|Where-Object {$_.binding.ThreadId -ne $pin -and ($_.busy -or -not $_.nativeConnected -or $_.held -or -not $_.ready)}).Count -or
  @($claude|Where-Object {$_.binding.ThreadId -eq $pin -and ($_.nativeConnected -or $_.pid -ne 0 -or $_.admission.Blocking -ne 0)}).Count -ne 0 -or
  [RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('received','dispatching','unknown')").Length -or
  [RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Only unavailable Motor and idle settled peers may be restarted'}
}
if(Test-Path $release){throw 'Retained recovery exists: inspect, never repeat'}
if((Get-FileHash ($root+'\bin\KhadangRouter.dll')).Hash -ne '7CB14B08DB72972FB2A35CF9CCB13DA60906CAE865DDBECB3BC486092B54C7F2'){throw 'Reviewed deployment changed'}
HistoryProof;IdlePeers
New-Item -ItemType Directory $release|Out-Null;Protect $release $true
$scheduler=New-Object -ComObject Schedule.Service;$scheduler.Connect();$tasks=@()
foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=$scheduler.GetFolder('\').GetTask($name);$tasks+=@{task=$t;enabled=$t.Enabled}}
Save ($release+'\before.json') @{bindings=(Bindings);unknown=(Unknown);status=(Status);supervisors=@($tasks|ForEach-Object {@{name=$_.task.Name;enabled=$_.enabled}})}
try{
 foreach($t in $tasks){$t.task.Enabled=$false;if($t.task.State -eq 4){$t.task.Stop(0)}}
 IdlePeers
 $svc=Get-Service KhadangRouter;$svc.Stop();$svc.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(40))
 # Leave the independent host and all eight healthy Claude processes running.
 HistoryProof
 $lease=[IO.File]::Open($root+'\state\exclusive.lock','Open','ReadWrite','None');$wl=$null;$db=$null;$workerDb=$null
 try{
  $wl=[IO.File]::Open($folder+'\broker.lease','Open','ReadWrite','None');$db=[PcbaRegistry]::new()
  $a=[Management.Automation.Language.Parser]::ParseFile(($native+'\stage-dut-topic.ps1'),[ref]$null,[ref]$null)
  $d=$a.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type'},$true)
  . ([scriptblock]::Create($d.Extent.Text.Replace('PcbaRegistry','MotorRecoveryWrite').Replace($root+'\state\router.db',$folder+'\broker.db')))
  $workerDb=[MotorRecoveryWrite]::new()
  if($workerDb.Read("SELECT id FROM operations WHERE status IN ('unknown','attempting') AND kind<>'telegram/editMessageText'").Length -or
   $workerDb.Read("SELECT intent FROM broker_calls WHERE status IN ('unknown','attempting','submitted')").Length -or
   $workerDb.Read("SELECT id FROM broker_replies WHERE status IN ('unknown','attempting','submitted')").Length -or
   $workerDb.Read("SELECT id FROM broker_requests WHERE status IN ('pending','replying','reply-submitted')").Length -or
   $workerDb.Read("SELECT key FROM meta WHERE key='claude/reset/$pin'").Length){throw 'Uncertain private input or approval; no waiver'}
  $binding=$db.Read('SELECT payload FROM bindings WHERE chat=-1003550185469 AND topic=14439')[0][0]|ConvertFrom-Json
  if($binding.ThreadId -cne $pin -or $binding.Workspace -cne $workspace -or $binding.Backend -ne 'claude' -or $binding.Runtime -ne 'linux'){throw 'Protected exact binding changed'}
  $bubble=$db.Read("SELECT value FROM meta WHERE key='bubble/$pin'")[0][0]|ConvertFrom-Json
  $recovery=$workerDb.Read("SELECT value FROM meta WHERE key='claude/recovery/$pin'")[0][0]|ConvertFrom-Json
  if($recovery.state -ne 'connected' -or $recovery.sha256 -cne 'b1caa4c53423533ca1f0345173b84063751bbf4bca30c86c75a625b760536cc0' -or
   $bubble.sendUnknown -or @($bubble.pendingAnswers).Count -or @($bubble.pendingResponses).Count -or @($bubble.pendingFiles).Count -or
   @($bubble.finalAnswer.Parts).Count -or @($bubble.finalAnswer.Files).Count){throw 'Unexpected checkpoint or unsettled output/approval'}
  $requestKey="claude/request/$pin/be0348ba-8c94-4c77-96a1-a0e43839d7d8"
  $pending=@($workerDb.Read("SELECT key,value FROM meta WHERE key LIKE 'claude/request/$pin/%' AND json_extract(value,'$.status')='pending'"))
  if($pending.Count -ne 1 -or $pending[0][0] -cne $requestKey){throw 'Only one exact proven shutdown-cancelled question may be reconciled'}
  $cancel=$pending[0][1]|ConvertFrom-Json
  if($cancel.frame.request_id -cne 'be0348ba-8c94-4c77-96a1-a0e43839d7d8' -or $cancel.frame.request.tool_name -cne 'AskUserQuestion' -or
   $cancel.frame.request.tool_use_id -cne 'toolu_013pvgP9c1iuekk6a7viYYhz'){throw 'Saved pending question changed'}
  Save ($release+'\previous-request.json') $cancel
  Save ($release+'\previous-bubble.json') $bubble;Save ($release+'\previous-recovery.json') $recovery
  Save ($release+'\previous-private-bubble.json') @($workerDb.Read("SELECT value FROM meta WHERE key='bubble/$pin'"))
  $audit=@{schema='ccrelay.owner_shutdown_question_reconciliation.v1';approval='Pouya direct controller request: Motorcontrol plant topic down again';session=$pin;
   history=@{path=$history;bytes=46109698;sha256=$expected};pendingTools=0;pendingQueue=0;unresolvedBackground=0;
   cancelledRequest=@{id='be0348ba-8c94-4c77-96a1-a0e43839d7d8';toolUseId='toolu_013pvgP9c1iuekk6a7viYYhz';
    resultUuid='adf28d73-83e1-460a-ae79-46bdde1a7c87';at='2026-11-08T01:14:54.782Z';interruptedByShutdown=$true;isError=$true;toolDenialKind='user-rejected';disposition='cancelled, not approved and not answered'};
   modelDisposition='Retain interrupted question/turn evidence; accept only new explicit input';nativeInputsReplayed=0;transcriptModified=$false;externalDeliveryClaimed=$false;at=[DateTimeOffset]::UtcNow}
  Save ($release+'\audit.json') $audit
  $p=Get-Content -Raw ($root+'\config.json')|ConvertFrom-Json;$checkpoint=$p.LinuxClaude.PackageRoot+'\handoff-'+$pin+'.json'
  if((Get-FileHash $checkpoint).Hash.ToLowerInvariant() -cne $recovery.sha256){throw 'Checkpoint differs from private custody'}
  Copy-Item $checkpoint ($release+'\previous-checkpoint.json');Protect ($release+'\previous-checkpoint.json')
  $new=@{schema='ccrelay.personal_claude_handoff.v1';session_id=$pin;workspace=$workspace;source_writer='quiesced';uncertain_actions=@();history=$audit.history;profile='/Users/pouya/.claude'}
  Save ($release+'\reviewed-checkpoint.json') $new
  $tmp=$checkpoint+'.reviewed-interruption';Copy-Item ($release+'\reviewed-checkpoint.json') $tmp;Set-Acl $tmp (Get-Acl $checkpoint)
  [IO.File]::Replace($tmp,$checkpoint,[System.Management.Automation.Language.NullString]::Value)
  $cancel.status='cancelled'
  $cancel|Add-Member ownerShutdownReconciliation $audit -Force
  $null=$workerDb.Read("UPDATE meta SET value=CAST(X'$(Hex $cancel)' AS TEXT) WHERE key='$requestKey'")
  $recovery.sha256=(Get-FileHash $checkpoint).Hash.ToLowerInvariant();$recovery|Add-Member ownerInterruptedReview $audit -Force
  $bubble.busy=$false;$bubble.claudeState='idle';$bubble.held=$true;$bubble.status='Held — Claude stream disconnected';$bubble.nativeStatus=$bubble.status
  $null=$workerDb.Read("UPDATE meta SET value=CAST(X'$(Hex $recovery)' AS TEXT) WHERE key='claude/recovery/$pin'")
  $null=$workerDb.Read("INSERT INTO meta(key,value) VALUES('bubble/$pin',CAST(X'$(Hex $bubble)' AS TEXT)) ON CONFLICT(key) DO UPDATE SET value=excluded.value")
  $null=$db.Read("UPDATE meta SET value=CAST(X'$(Hex $bubble)' AS TEXT) WHERE key='bubble/$pin'")
  Save ($release+'\staged.json') @{at=[DateTimeOffset]::UtcNow;checkpointSha256=$recovery.sha256;inputReplay=0}
 }finally{if($workerDb){$workerDb.Dispose()};if($db){$db.Dispose()};if($wl){$wl.Dispose()};$lease.Dispose()}
}finally{
 if((Get-Service KhadangClaudeHost).Status -ne 'Running'){throw 'Independent host unexpectedly stopped; do not replace live peers'}
 if((Get-Service KhadangRouter).Status -eq 'Stopped'){Start-Service KhadangRouter}
 foreach($t in $tasks){$t.task.Enabled=[bool]$t.enabled}
}
'Exact interrupted model checkpoint reconciled; no historical tool or input replay. Verify readiness and actual Telegram response.'

