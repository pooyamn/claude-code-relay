param([ValidateSet('restore','verify')][string]$Phase='restore')
# Owner-requested observer repair only. Native daemon/session and every original
# input/operation receipt stay intact. Never replay a message or restart a goal.
$ErrorActionPreference='Stop';$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote'
$release="$root\recovery-base-board-20261020";$pin='01a104cc-9a63-7901-8897-abf8aff3dfb3'
$code='A0D694DA58801A58F5EEBE1B31BC582707445D58060D4A3EC640EC9759055B33'
$policy='5A2E3C1B24BCC1638CBCF202472C836DD2A3307411CBFDEE4B874E1C0D51E4DE'
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
 $retained=Test-Path $release
 if($retained -and ((Test-Path "$release\restored.json") -or (Test-Path "$release\previous-router.db"))){throw 'Retained mutation exists; reconcile'}
 if($retained){Fenced}
 if(-not $retained){
 $s=[IO.File]::ReadAllText("$root\state\status.json")|ConvertFrom-Json
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 18 -or @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Fresh current native custody required'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 Save "$release\before.json" @{host=(HostIdentity);unknown=(Unknown);bindings=(Bindings);startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled;at=[DateTimeOffset]::UtcNow.ToString('o')}
 foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $name;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 }
 LoadSql "$native\stage-dut-topic.ps1" '0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF' 'PcbaRegistry'
 $lease=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null
 try{
  $db=[PcbaRegistry]::new()
  if($db.Read("SELECT id FROM updates WHERE status IN ('dispatching','unknown')").Length -or $db.Read("SELECT id FROM operations WHERE (status='attempting' AND kind<>'telegram/editMessageText') OR (status='unknown' AND kind NOT IN ('telegram/editMessageText','telegram/sendDocument'))").Length){throw 'Unsettled native effects; preserve'}
  $binding=$db.Read('SELECT payload FROM bindings WHERE chat=-1004395661179 AND topic=18')[0][0]|ConvertFrom-Json
  $raw=$db.Read("SELECT value FROM meta WHERE key='bubble/$pin'")[0][0];$b=$raw|ConvertFrom-Json
  if($binding.ThreadId -ne $pin -or $binding.Workspace -cne '/Users/pouya/.openclaw/workspace/ai-hil/hardware/augur-1' -or $binding.Backend -ne 'codex' -or $binding.Runtime -ne 'linux' -or
   -not $b.held -or $b.turn -ne '01a15a50-0b9c-7d43-a512-4ec169498e58' -or $b.status -notmatch ('^Held '+[char]0x2014+' input (?<heldUpdate>[0-9]+) not confirmed$') -or $b.sendUnknown -or @($b.pendingAnswers).Count -or @($b.pendingResponses).Count -or @($b.finalAnswer.Parts+$b.finalAnswer.Files|Where-Object SendUnknown).Count){throw 'Exact recoverable Base Board observer required'}
  $heldUpdate=[long]$Matches['heldUpdate']
  if($db.Read("SELECT id FROM updates WHERE id=$heldUpdate AND status='held-no-replay' AND json_extract(payload,'$.message.chat.id')=-1004395661179 AND json_extract(payload,'$.message.message_thread_id')=18").Length -ne 1){throw 'Latest Base Board retained input differs'}
  foreach($row in $db.Read("SELECT kind,payload FROM operations WHERE status='unknown' AND kind<>'telegram/editMessageText'")){$p=$row[1]|ConvertFrom-Json;if($row[0] -ne 'telegram/sendDocument' -or $p.chat_id -ne -1004393585932 -or $p.message_thread_id -ne 2){throw 'Unclassified/target uncertainty; preserve'}}
  foreach($id in @(759323932,759323934)){if($db.Read("SELECT id FROM updates WHERE id=$id AND status='held-no-replay' AND json_extract(payload,'$.message.chat.id')=-1004395661179 AND json_extract(payload,'$.message.message_thread_id')=18").Length -ne 1){throw 'Original held input changed'}}
  $null=$db.Read("VACUUM INTO '$release\previous-router.db'");Protect "$release\previous-router.db"
  Save "$release\original-bubble.json" $b
  # Fresh owner-side native readback established this same latest turn completed.
  # Reset observation only: ResumeCodex independently verifies exact scope again.
  $b.held=$false;$b.busy=$false;$b.status='Ready';$b|Add-Member nativeStatus 'Ready' -Force
  $null=$db.Read("UPDATE meta SET value=CAST(X'$(Hex $b)' AS TEXT) WHERE key='bubble/$pin'")
  Save "$release\restored.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');nativeThread=$pin;messagesReplayed=0;receiptRowsChanged=0;observerOnly=$true}
 }finally{if($db){$db.Dispose()};$lease.Dispose()}
 Start-Service KhadangRouter
 @{phase='observer-restored';nativeDaemonRestarted=$false;messagesReplayed=0}|ConvertTo-Json -Compress;return
}
$s=[IO.File]::ReadAllText("$root\state\status.json")|ConvertFrom-Json;$before=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json;$restored=[IO.File]::ReadAllText("$release\restored.json")|ConvertFrom-Json
$b=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $pin})
if((Get-Service KhadangRouter).Status -ne 'Running' -or [DateTimeOffset]$s.at -le [DateTimeOffset]$restored.at -or [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or $b.Count -ne 1 -or $b[0].held -or
 (Bindings) -cne $before.bindings -or (Unknown) -cne $before.unknown -or (HostIdentity) -cne $before.host -or @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Fresh exact recovery not confirmed'}
foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){(ExactTask $name).Enabled=[bool]$(if($name -like '*Startup'){$before.startup}else{$before.watchdog})}
Save "$release\verified.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');baseBoardReady=$true;nativeThread=$pin;messagesReplayed=0;registryPreserved=$true;nativeHostPreserved=$true;startupRestored=$true}
[IO.File]::ReadAllText("$release\verified.json")
