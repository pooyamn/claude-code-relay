param([ValidateSet('restore','verify')][string]$Phase='restore')
# Clear only the controller's stale transport-observer hold. Preserve its active
# native turn, all input/operation receipts, bindings, other holds and workers.
$ErrorActionPreference='Stop';$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote'
$release="$root\recovery-cc-relay-20261020";$pin='01a0facd-1bc0-7d23-95d6-c32fde0c62db'
$turn='01a15a7b-4f11-7610-bbb3-157d4e103c90'
$code='A0D694DA58801A58F5EEBE1B31BC582707445D58060D4A3EC640EC9759055B33'
$policy='6271B521E9C069618384FD6632088C7FAF06FDD1CBCB8A7CBCDC36E77215192C'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$helper='C:\Users\pou\AppData\Local\Temp\deploy-switch-isolation-20261014.ps1'
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helper differs'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Unknown','Bindings','HostIdentity','ExactTask','Fenced','Hex')){$d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true);if(-not $d){throw 'Helper missing'};. ([ScriptBlock]::Create($d.Extent.Text))}
LoadSql "$native\inspect-state.ps1" 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code -or (Get-FileHash "$root\config.json").Hash -ne $policy){throw 'Exact current code/policy required'}
if($Phase -eq 'restore'){
 if(Test-Path $release){throw 'Retained recovery exists; reconcile'}
 $s=[IO.File]::ReadAllText("$root\state\status.json")|ConvertFrom-Json
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 18 -or @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Fresh current custody required'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 Save "$release\before.json" @{host=(HostIdentity);unknown=(Unknown);bindings=(Bindings);held=@($s.nativeSessions|Where-Object {$_.held -and $_.binding.ThreadId -ne $pin}|ForEach-Object {$_.binding.ThreadId});startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled;at=[DateTimeOffset]::UtcNow.ToString('o')}
 foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $name;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 LoadSql "$native\stage-dut-topic.ps1" '0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF' 'PcbaRegistry'
 $lease=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null
 try{
  $db=[PcbaRegistry]::new()
  if($db.Read("SELECT id FROM updates WHERE status IN ('dispatching','unknown')").Length -or $db.Read("SELECT id FROM operations WHERE (status='attempting' AND kind<>'telegram/editMessageText') OR (status='unknown' AND kind NOT IN ('telegram/editMessageText','telegram/sendDocument'))").Length){throw 'Unsettled native effects; preserve'}
  $binding=$db.Read('SELECT payload FROM bindings WHERE chat=-1003550185469 AND topic=816')[0][0]|ConvertFrom-Json
  $b=$db.Read("SELECT value FROM meta WHERE key='bubble/$pin'")[0][0]|ConvertFrom-Json
  if($binding.ThreadId -ne $pin -or $binding.Workspace -cne '/Users/pouya/.openclaw/workspace/claude-code-relay' -or $binding.Backend -ne 'codex' -or $binding.Runtime -ne 'linux' -or
   -not $b.held -or -not $b.busy -or $b.turn -ne $turn -or $b.sendUnknown -or @($b.pendingAnswers).Count -or @($b.pendingResponses).Count -or @($b.finalAnswer.Parts+$b.finalAnswer.Files|Where-Object SendUnknown).Count){throw 'Exact recoverable controller observer required'}
  foreach($row in $db.Read("SELECT kind,payload FROM operations WHERE status='unknown' AND kind<>'telegram/editMessageText'")){$p=$row[1]|ConvertFrom-Json;if($row[0] -ne 'telegram/sendDocument' -or $p.chat_id -ne -1004393585932 -or $p.message_thread_id -ne 2){throw 'Unclassified/target uncertainty; preserve'}}
  foreach($id in @(759323933,759323936)){if($db.Read("SELECT id FROM updates WHERE id=$id AND status='held-no-replay' AND json_extract(payload,'$.message.chat.id')=-1003550185469 AND json_extract(payload,'$.message.message_thread_id')=816").Length -ne 1){throw 'Original retained input changed'}}
  $null=$db.Read("VACUUM INTO '$release\previous-router.db'");Protect "$release\previous-router.db";Save "$release\original-bubble.json" $b
  # Owner-side native readback confirms this SAME active turn with no active
  # request flags. Do not stop it, clear busy, or start another native turn.
  $b.held=$false;$b.status='Working';$b|Add-Member nativeStatus 'Working' -Force
  $null=$db.Read("UPDATE meta SET value=CAST(X'$(Hex $b)' AS TEXT) WHERE key='bubble/$pin'")
  Save "$release\restored.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');nativeThread=$pin;turn=$turn;messagesReplayed=0;receiptRowsChanged=0;observerOnly=$true}
 }finally{if($db){$db.Dispose()};$lease.Dispose()}
 Start-Service KhadangRouter;@{phase='observer-restored';nativeDaemonRestarted=$false;messagesReplayed=0}|ConvertTo-Json -Compress;return
}
$s=[IO.File]::ReadAllText("$root\state\status.json")|ConvertFrom-Json;$before=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json;$restored=[IO.File]::ReadAllText("$release\restored.json")|ConvertFrom-Json
$b=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $pin})
if((Get-Service KhadangRouter).Status -ne 'Running' -or [DateTimeOffset]$s.at -le [DateTimeOffset]$restored.at -or [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or $b.Count -ne 1 -or $b[0].held -or $b[0].turn -ne $turn -or
 (Bindings) -cne $before.bindings -or (Unknown) -cne $before.unknown -or (HostIdentity) -cne $before.host -or @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Fresh exact controller recovery not confirmed'}
foreach($id in $before.held){if(@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $id -and $_.held}).Count -ne 1){throw 'Unrelated hold changed'}}
foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){(ExactTask $name).Enabled=[bool]$(if($name -like '*Startup'){$before.startup}else{$before.watchdog})}
Save "$release\verified.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');controllerReady=$true;nativeThread=$pin;turn=$turn;messagesReplayed=0;registryPreserved=$true;nativeHostPreserved=$true;startupRestored=$true}
[IO.File]::ReadAllText("$release\verified.json")
