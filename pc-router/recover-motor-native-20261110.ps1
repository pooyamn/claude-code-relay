param([Parameter(Mandatory=$true)][string]$AuditSha256)
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$PSDefaultParameterValues['Get-Content:Encoding']='UTF8'
$root='C:\ProgramData\KhadangRouter';$hostRoot='C:\ProgramData\KhadangClaudeHost';$native='C:\ProgramData\OracovaNativeRemote'
$pin='8cd2d34c-0805-4705-8197-d11de0728499';$release=$root+'\recover-motor-native-20261110'
$old='2702841a79a54a13e9731a5872a0dce5f6f5778738fe804dd76abce6ec36cae9'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if(-not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed administrator required'}
$helper='C:\Users\pou\AppData\Local\Temp\deploy-switch-isolation-20261014.ps1'
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Helper changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Hex','Bindings','Unknown','HostIdentity','ExactTask')){
 $d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true);. ([scriptblock]::Create($d.Extent.Text))
}
LoadSql ($native+'\inspect-state.ps1') 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
LoadSql ($native+'\stage-dut-topic.ps1') '0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF' 'PcbaRegistry'
$auditSource='C:\Users\pou\AppData\Local\Temp\motor-recovery-audit-20261110.json'
if((Get-FileHash $auditSource).Hash -ne $AuditSha256 -or (Test-Path ($release+'\before.json'))){throw 'Fresh reviewed audit required; never repeat an interrupted operation'}
$audit=Get-Content -Raw $auditSource|ConvertFrom-Json
if($audit.schema -ne 'ccrelay.owner_motor_recovery_audit.v1' -or $audit.session -cne $pin -or $audit.workspace -cne '/Users/pouya/.openclaw/workspace/motorcontrol-plant' -or
 $audit.oldCheckpointSha256 -cne $old -or $audit.history.bytes -ne 53439822 -or $audit.history.sha256 -cne '62e184b51ef4b7117a3511aa6a8d5196b52ca90f9e69a498811c2f65a9faf790' -or
 -not $audit.historyQuiescent -or $audit.pendingTools -or $audit.pendingQueue -or $audit.transcriptModified -or $audit.inputReplay -or $audit.regressionChainCompletionClaimed){throw 'Exact non-replaying owner audit required'}
function HistoryProof{
 $line=(& C:\Windows\System32\wsl.exe -d Ubuntu-24.04 -u pou --exec /usr/bin/sha256sum $audit.history.path)-join ''
 if($LASTEXITCODE -or -not $line.StartsWith($audit.history.sha256+' ')){throw 'Audited history changed'}
 $writers=(& C:\Windows\System32\wsl.exe -d Ubuntu-24.04 -u pou --exec /usr/bin/pgrep -af ('[c]laude.*'+$pin+'|[p]c_claude_stdio.py.*'+$pin))-join ''
 if($LASTEXITCODE -ne 1 -or $writers){throw 'Existing exact writer must not be replaced'}
}
if((Get-FileHash ($root+'\bin\KhadangRouter.dll')).Hash -ne 'BD6CF699E3BD92ABC86C552C4F5BAC11BFDAA73876979A4AED98E7CF548F1B86'){throw 'Reviewed deployment changed'}
$policy=Get-Content -Raw ($root+'\config.json')|ConvertFrom-Json;$cp=$policy.LinuxClaude.PackageRoot+'\handoff-'+$pin+'.json'
if((Get-FileHash $cp).Hash.ToLowerInvariant() -cne $old){throw 'Checkpoint changed'}
HistoryProof
$before=Get-Content -Raw ($root+'\state\status.json')|ConvertFrom-Json
$motor=@($before.nativeSessions|Where-Object {$_.binding.ThreadId -eq $pin})
if([DateTimeOffset]$before.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $motor.Count -ne 1 -or $motor[0].pid -ne 0 -or $motor[0].nativeConnected -or $motor[0].busy -or $motor[0].admission.Blocking){throw 'Only the unavailable exact Motor worker may recover'}
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
$tasks=@('Oracova-KhadangStartup','Oracova-KhadangWatchdog')|ForEach-Object {$t=ExactTask $_;@{task=$t;enabled=$t.Enabled}}
Save ($release+'\before.json') @{status=$before;bindings=(Bindings);unknown=(Unknown);host=(HostIdentity);supervisors=@($tasks|ForEach-Object {@{name=$_.task.Name;enabled=$_.enabled}})}
Copy-Item $auditSource ($release+'\audit.json');Protect ($release+'\audit.json')
try{
 foreach($t in $tasks){$t.task.Enabled=$false;if($t.task.State -eq 4){$t.task.Stop(0)}}
 try{Stop-Service KhadangRouter}catch{};(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30))
 HistoryProof
 $lease=[IO.File]::Open($root+'\state\exclusive.lock','Open','ReadWrite','None');$workerLease=$null;$db=$null;$worker=$null
 try{
  $folder=$hostRoot+'\state\'+$pin
  $workerLease=[IO.File]::Open($folder+'\broker.lease','Open','ReadWrite','None')
  $db=[PcbaRegistry]::new()
  $a=[Management.Automation.Language.Parser]::ParseFile(($native+'\stage-dut-topic.ps1'),[ref]$null,[ref]$null)
  $d=$a.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type'},$true)
  . ([scriptblock]::Create($d.Extent.Text.Replace('PcbaRegistry','MotorNov10Write').Replace($root+'\state\router.db',$folder+'\broker.db')))
  $worker=[MotorNov10Write]::new()
  if($db.Read("SELECT id FROM updates WHERE status IN ('received','dispatching','unknown')").Length -or
   $worker.Read("SELECT id FROM operations WHERE status IN ('unknown','attempting') AND kind<>'telegram/editMessageText'").Length -or
   $worker.Read("SELECT intent FROM broker_calls WHERE status IN ('unknown','attempting','submitted')").Length -or
   $worker.Read("SELECT id FROM broker_replies WHERE status IN ('unknown','attempting','submitted')").Length -or
   $worker.Read("SELECT id FROM broker_requests WHERE status IN ('pending','replying','reply-submitted')").Length -or
   $worker.Read("SELECT key FROM meta WHERE key LIKE 'claude/request/$pin/%' AND json_extract(value,'$.status')='pending'").Length){throw 'Uncertain input or approval remains held'}
  $binding=$db.Read('SELECT payload FROM bindings WHERE chat=-1003550185469 AND topic=14439')[0][0]|ConvertFrom-Json
  if($binding.ThreadId -cne $pin -or $binding.Backend -ne 'claude' -or $binding.Workspace -cne $audit.workspace){throw 'Exact binding changed'}
  $recovery=$worker.Read("SELECT value FROM meta WHERE key='claude/recovery/$pin'")[0][0]|ConvertFrom-Json
  if($recovery.state -ne 'connected' -or $recovery.sha256 -cne $old -or $recovery.model -ne 'claude-fable-5-2'){throw 'Recovery state changed'}
  Copy-Item $cp ($release+'\previous-checkpoint.json');Protect ($release+'\previous-checkpoint.json')
  Save ($release+'\previous-recovery.json') $recovery
  $new=@{schema='ccrelay.personal_claude_handoff.v1';session_id=$pin;workspace=$audit.workspace;source_writer='quiesced';uncertain_actions=@();history=$audit.history;profile='/Users/pouya/.claude'}
  Save ($release+'\reviewed-checkpoint.json') $new
  $tmp=$cp+'.reviewed-nov10';Copy-Item ($release+'\reviewed-checkpoint.json') $tmp;Set-Acl $tmp (Get-Acl $cp);[IO.File]::Replace($tmp,$cp,[System.Management.Automation.Language.NullString]::Value)
  $recovery.sha256=(Get-FileHash $cp).Hash.ToLowerInvariant();$recovery|Add-Member ownerRecoveryReview ($release+'\audit.json') -Force
  $null=$worker.Read("UPDATE meta SET value=CAST(X'$(Hex $recovery)' AS TEXT) WHERE key='claude/recovery/$pin'")
  $null=$db.Read("UPDATE meta SET value=CAST(X'$(Hex $recovery)' AS TEXT) WHERE key='claude/recovery/$pin'")
  $saved=Get-Content -Raw ($release+'\before.json')|ConvertFrom-Json
  if((Bindings) -cne $saved.bindings -or (Unknown) -cne $saved.unknown -or (HostIdentity) -cne $saved.host){throw 'Unrelated state changed'}
  Save ($release+'\staged.json') @{checkpointSha256=$recovery.sha256;inputReplay=0;nativeWorkersStopped=0;at=[DateTimeOffset]::UtcNow}
 }finally{if($worker){$worker.Dispose()};if($db){$db.Dispose()};if($workerLease){$workerLease.Dispose()};$lease.Dispose()}
}finally{
 if((Get-Service KhadangClaudeHost).Status -ne 'Running'){throw 'Independent host unexpectedly stopped; do not replace live peers'}
 if((Get-Service KhadangRouter).Status -eq 'Stopped'){Start-Service KhadangRouter}
 foreach($t in $tasks){$t.task.Enabled=[bool]$t.enabled}
}
'Motor checkpoint renewed; verify exact worker and actual delivery before claiming restored.'
