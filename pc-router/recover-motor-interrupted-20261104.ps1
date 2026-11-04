$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$hostRoot='C:\ProgramData\KhadangClaudeHost';$native='C:\ProgramData\OracovaNativeRemote'
$pin='8cd2d34c-0805-4705-8197-d11de0728499';$workspace='/Users/pouya/.openclaw/workspace/motorcontrol-plant'
$release=$root+'\recover-motor-interrupted-20261104';$folder=$hostRoot+'\state\'+$pin
$expected='645d2771ef0158a769ad4895f006fdf14a2752bfdee542dace2acc192ebb468d'
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
 $h=Get-Service KhadangClaudeHost;$h.Stop();$h.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(40))
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
   $workerDb.Read("SELECT key FROM meta WHERE key='claude/reset/$pin' OR (key LIKE 'claude/request/$pin/%' AND json_extract(value,'$.status')='pending')").Length){throw 'Uncertain private input or approval; no waiver'}
  $binding=$db.Read('SELECT payload FROM bindings WHERE chat=-1003550185469 AND topic=14439')[0][0]|ConvertFrom-Json
  if($binding.ThreadId -cne $pin -or $binding.Workspace -cne $workspace -or $binding.Backend -ne 'claude' -or $binding.Runtime -ne 'linux'){throw 'Protected exact binding changed'}
  $bubble=$db.Read("SELECT value FROM meta WHERE key='bubble/$pin'")[0][0]|ConvertFrom-Json
  $recovery=$workerDb.Read("SELECT value FROM meta WHERE key='claude/recovery/$pin'")[0][0]|ConvertFrom-Json
  if($recovery.state -ne 'connected' -or $recovery.sha256 -cne '22da1dc44da4f2032ff932b16d1f318f23c3fdb85f38efd837c26aaabc9c0de3' -or
   $bubble.sendUnknown -or @($bubble.pendingAnswers).Count -or @($bubble.pendingResponses).Count -or @($bubble.pendingFiles).Count -or
   @($bubble.finalAnswer.Parts).Count -or @($bubble.finalAnswer.Files).Count){throw 'Unexpected checkpoint or unsettled output/approval'}
  Save ($release+'\previous-bubble.json') $bubble;Save ($release+'\previous-recovery.json') $recovery
  Save ($release+'\previous-private-bubble.json') @($workerDb.Read("SELECT value FROM meta WHERE key='bubble/$pin'"))
  $audit=@{schema='ccrelay.owner_interrupted_model_recovery.v1';approval='Pouya direct controller message: Topic dead again; preserve exact Motorcontrol session and repair';session=$pin;
   history=@{path=$history;bytes=21795323;sha256=$expected};pendingTools=0;pendingQueue=0;pendingAbsorbedCommands=0;
   unfinishedTask=@{id='bhgssdo83';tool='toolu_01K4FBLwiEQNWCm3vnxFPXfh';command='Read-only until route-tool.done / sleep / cut / sed status watcher';disposition='terminated by intervening WSL boot; not rerun; no completion claimed'};
   terminalModelTurn=$false;modelDisposition='Retain unfinished turn evidence; stop continuation and accept only new explicit input';lastToolResult='pilot rc=0 at21:58:25.388Z; recorded result retained, not replayed';
   nativeInputsReplayed=0;transcriptModified=$false;externalDeliveryClaimed=$false;at=[DateTimeOffset]::UtcNow}
  Save ($release+'\audit.json') $audit
  $p=Get-Content -Raw ($root+'\config.json')|ConvertFrom-Json;$checkpoint=$p.LinuxClaude.PackageRoot+'\handoff-'+$pin+'.json'
  if((Get-FileHash $checkpoint).Hash.ToLowerInvariant() -cne $recovery.sha256){throw 'Checkpoint differs from private custody'}
  Copy-Item $checkpoint ($release+'\previous-checkpoint.json');Protect ($release+'\previous-checkpoint.json')
  $new=@{schema='ccrelay.personal_claude_handoff.v1';session_id=$pin;workspace=$workspace;source_writer='quiesced';uncertain_actions=@();history=$audit.history;profile='/Users/pouya/.claude'}
  Save ($release+'\reviewed-checkpoint.json') $new
  $tmp=$checkpoint+'.reviewed-interruption';Copy-Item ($release+'\reviewed-checkpoint.json') $tmp;Set-Acl $tmp (Get-Acl $checkpoint)
  [IO.File]::Replace($tmp,$checkpoint,[System.Management.Automation.Language.NullString]::Value)
  $recovery.sha256=(Get-FileHash $checkpoint).Hash.ToLowerInvariant();$recovery|Add-Member ownerInterruptedReview $audit -Force
  $bubble.busy=$false;$bubble.claudeState='idle';$bubble.held=$true;$bubble.status='Held — Claude stream disconnected';$bubble.nativeStatus=$bubble.status
  $null=$workerDb.Read("UPDATE meta SET value=CAST(X'$(Hex $recovery)' AS TEXT) WHERE key='claude/recovery/$pin'")
  $null=$workerDb.Read("INSERT INTO meta(key,value) VALUES('bubble/$pin',CAST(X'$(Hex $bubble)' AS TEXT)) ON CONFLICT(key) DO UPDATE SET value=excluded.value")
  $null=$db.Read("UPDATE meta SET value=CAST(X'$(Hex $bubble)' AS TEXT) WHERE key='bubble/$pin'")
  Save ($release+'\staged.json') @{at=[DateTimeOffset]::UtcNow;checkpointSha256=$recovery.sha256;inputReplay=0}
 }finally{if($workerDb){$workerDb.Dispose()};if($db){$db.Dispose()};if($wl){$wl.Dispose()};$lease.Dispose()}
}finally{
 if((Get-Service KhadangClaudeHost).Status -eq 'Stopped'){Start-Service KhadangClaudeHost}
 if((Get-Service KhadangRouter).Status -eq 'Stopped'){Start-Service KhadangRouter}
 foreach($t in $tasks){$t.task.Enabled=[bool]$t.enabled}
}
'Exact interrupted model checkpoint reconciled; no historical tool or input replay. Verify readiness and actual Telegram response.'
