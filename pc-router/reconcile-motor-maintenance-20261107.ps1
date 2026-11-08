$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$hostRoot='C:\ProgramData\KhadangClaudeHost';$native='C:\ProgramData\OracovaNativeRemote';$temp='C:\Users\pou\AppData\Local\Temp'
$release=$root+'\release-claude-pipe-20261107-v3';$pin='8cd2d34c-0805-4705-8197-d11de0728499';$folder=$hostRoot+'\state\'+$pin
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if(-not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$helper=$temp+'\deploy-switch-isolation-20261014.ps1'
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helpers changed'}
$a=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Hex','Bindings','Unknown','HostIdentity')){$d=$a.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true);. ([scriptblock]::Create($d.Extent.Text))}
LoadSql ($native+'\inspect-state.ps1') 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
LoadSql ($native+'\stage-dut-topic.ps1') '0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF' 'PcbaRegistry'
if((Get-FileHash ($root+'\bin\KhadangRouter.dll')).Hash -ne 'F8C527B3F3611E8F7DD259F93595AA7FAB11D11FC7DA8CF5701468A0B21707C6' -or
 (Get-FileHash ($root+'\config.json')).Hash -ne 'F41B5F544EE550460788BF24B21A907A78CB6DDACB0CD0194B847A95F6C3EB0C' -or
 (Get-FileHash ($temp+'\motor-maintenance-audit-20261107.json')).Hash -ne 'FDAB249089513D5F22BB67C34033D58CAB08502FD3652869CDCF97823A50C5C3' -or
 (Get-FileHash ($temp+'\pc_claude_stdio-pipe-20261107.py')).Hash -ne 'E304EBE837CFF456AE45B3D47F6F90E624DA4B8344B4E5BE6A3AF33111A5309D'){throw 'Exact reviewed artifacts required'}
if(Test-Path ($release+'\motor-maintenance-before.json')){throw 'Reconciliation already attempted; inspect evidence'}
$s=Get-Content ($root+'\state\status.json') -Raw|ConvertFrom-Json;$targets=@($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude'})
if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddSeconds(-30) -or $targets.Count -ne 9 -or
 @($targets|Where-Object {$_.binding.ThreadId -ne $pin -and ($_.busy -or $_.held -or -not $_.ready -or -not $_.nativeConnected)}).Count -or
 @($targets|Where-Object {$_.binding.ThreadId -eq $pin -and ($_.pid -ne 0 -or $_.nativeConnected -or $_.admission.Blocking -ne 0)}).Count -or
 @($s.nativeSessions|Where-Object {$_.binding.Runtime -eq 'windows' -and $_.busy}).Count){throw 'Only unavailable Motor and eight idle connected peers may be reconciled'}
$scheduler=New-Object -ComObject Schedule.Service;$scheduler.Connect();$tasks=@()
foreach($n in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=$scheduler.GetFolder('\').GetTask($n);$tasks+=@{task=$t;enabled=$t.Enabled}}
$before=@{at=[DateTimeOffset]::UtcNow;host=(HostIdentity);bindings=(Bindings);unknown=(Unknown);nativePid=$s.nativeLinuxPid;peers=@($targets|Where-Object {$_.binding.ThreadId -ne $pin}|ForEach-Object {@{session=$_.binding.ThreadId;pid=$_.pid}})}
Save ($release+'\motor-maintenance-before.json') $before
try{
 foreach($t in $tasks){$t.task.Enabled=$false;if($t.task.State -eq 4){$t.task.Stop(0)}}
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(40))
 if((Get-Service KhadangClaudeHost).Status -ne 'Running' -or (HostIdentity) -cne $before.host -or (Bindings) -cne $before.bindings -or (Unknown) -cne $before.unknown){throw 'Observer EOF changed independent custody or uncertain receipts'}
 $audit=Get-Content ($temp+'\motor-maintenance-audit-20261107.json') -Raw|ConvertFrom-Json
 $actual=(& C:\Windows\System32\wsl.exe -d Ubuntu-24.04 -u pou --exec /usr/bin/sha256sum $audit.history.path)-join ''
 if($LASTEXITCODE -or -not $actual.StartsWith($audit.history.sha256+' ')){throw 'Reviewed native history changed'}
 $live=(& C:\Windows\System32\wsl.exe -d Ubuntu-24.04 -u pou --exec /usr/bin/pgrep -af ('[c]laude.*'+$pin+'|[p]c_claude_stdio.py.*'+$pin)) -join ''
 if($LASTEXITCODE -ne 1 -or $live){throw 'Do not replace a live exact native owner'}
 $lease=[IO.File]::Open($root+'\state\exclusive.lock','Open','ReadWrite','None');$wl=$null;$db=$null
 try{
  $wl=[IO.File]::Open($folder+'\broker.lease','Open','ReadWrite','None')
  $a=[Management.Automation.Language.Parser]::ParseFile(($native+'\stage-dut-topic.ps1'),[ref]$null,[ref]$null)
  $d=$a.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type'},$true)
  . ([scriptblock]::Create($d.Extent.Text.Replace('PcbaRegistry','MotorMaintenanceWrite').Replace($root+'\state\router.db',$folder+'\broker.db')))
  $db=[MotorMaintenanceWrite]::new()
  if($db.Read("SELECT id FROM operations WHERE status IN ('attempting','unknown') AND kind<>'telegram/editMessageText'").Length -or
   $db.Read("SELECT intent FROM broker_calls WHERE status IN ('attempting','unknown','submitted')").Length -or
   $db.Read("SELECT id FROM broker_replies WHERE status IN ('attempting','unknown','submitted')").Length -or
   $db.Read("SELECT key FROM meta WHERE key LIKE 'claude/request/$pin/%' AND json_extract(value,'$.status')='pending'").Length -or
   [RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('received','dispatching','unknown')").Length){throw 'Unsettled native input/question; no waiver'}
  $recovery=$db.Read("SELECT value FROM meta WHERE key='claude/recovery/$pin'")[0][0]|ConvertFrom-Json
  $p=Get-Content ($root+'\config.json') -Raw|ConvertFrom-Json;$checkpoint=$p.LinuxClaude.PackageRoot+'\handoff-'+$pin+'.json';$connector=$p.LinuxClaude.PackageRoot+'\pc_claude_stdio.py'
  if($recovery.state -ne 'connected' -or (Get-FileHash $checkpoint).Hash.ToLowerInvariant() -cne $recovery.sha256 -or
   (Get-FileHash $connector).Hash -ne 'BB05B1F927839738567E1C6B7C88110929D1BD9C53E63F0DD531F4527B1E2C57'){throw 'Reviewed checkpoint/connector changed'}
  foreach($entry in @(@{from=$checkpoint;name='motor-checkpoint-before.json'},@{from=$connector;name='connector-before.py'},@{from=($root+'\config.json');name='policy-before-monitor-fix.json'})){Copy-Item $entry.from (Join-Path $release $entry.name);Protect (Join-Path $release $entry.name)}
  Save ($release+'\motor-recovery-before.json') $recovery;Save ($release+'\motor-maintenance-audit.json') $audit
  $new=@{schema='ccrelay.personal_claude_handoff.v1';session_id=$pin;workspace=$audit.workspace;source_writer='quiesced';uncertain_actions=@();history=$audit.history;profile='/Users/pouya/.claude'}
  $tmp=$checkpoint+'.reviewed-maintenance';Save $tmp $new;Set-Acl $tmp (Get-Acl $checkpoint);[IO.File]::Replace($tmp,$checkpoint,[System.Management.Automation.Language.NullString]::Value)
  $recovery.sha256=(Get-FileHash $checkpoint).Hash.ToLowerInvariant();$recovery|Add-Member maintenanceCancellationReview $audit -Force
  $null=$db.Read("UPDATE meta SET value=CAST(X'$(Hex $recovery)' AS TEXT) WHERE key='claude/recovery/$pin'")
  $tmp=$connector+'.reviewed-monitor';Copy-Item ($temp+'\pc_claude_stdio-pipe-20261107.py') $tmp;Set-Acl $tmp (Get-Acl $connector);[IO.File]::Replace($tmp,$connector,[System.Management.Automation.Language.NullString]::Value)
  $p.LinuxClaude.FileSha256.'pc_claude_stdio.py'='e304ebe837cff456ae45b3d47f6f90e624da4b8344b4e5be6a3af33111a5309d'
  $tmp=$root+'\config.json.reviewed-monitor';Save $tmp $p;[IO.File]::Replace($tmp,$root+'\config.json',[System.Management.Automation.Language.NullString]::Value)
  $stage=Get-Content ($release+'\staged.json') -Raw|ConvertFrom-Json;$stage.policy=(Get-FileHash ($root+'\config.json')).Hash;$stage.at=[DateTimeOffset]::UtcNow
  Save ($release+'\staged.json') $stage
  Save ($release+'\motor-maintenance-staged.json') @{at=[DateTimeOffset]::UtcNow;history=$audit.history;policy=$stage.policy;hostPreserved=$true;nativeInputReplay=0;workerRerun=0;outstandingStandaloneTestsPreserved=$true}
 }finally{if($db){$db.Dispose()};if($wl){$wl.Dispose()};$lease.Dispose()}
}catch{foreach($t in $tasks){$t.task.Enabled=[bool]$t.enabled};throw}
'RECONCILED: cancelled worker is not completed/replayed; eight native peers preserved. Fresh policy security probe required before observer activation.'
