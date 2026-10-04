param([Parameter(Mandatory=$true)][ValidateSet('fence','stage','activate','verify')][string]$Phase)
# Fixed owner-approved enrollment only. No code/policy change, prompts or replay.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$nativeRoot='C:\ProgramData\OracovaNativeRemote'
$generation='7f2e3d3bfa76474e9a0657261ce5a7bf'
$release="$root\release-$generation";$package="$nativeRoot\codex-connector-$generation"
$code='B1FA6AD0895F63E33035606A018F7609E252C42D7B26CAB8E062ED3FA66270D7'
$policyDigest='7B6FA30311045122DEF25F07642EEF507DEB50AEFDFEA7F78D2BF0162E4D6D0B'
$thread='01a1093b-fcd5-73a3-b248-83872cccab11'
$controller='01a0facd-1bc0-7d23-95d6-c32fde0c62db'
$web='01a104a6-9fce-74a3-bdb0-e6dc04237ce7'
$interruptedHold='Held '+[char]0x2014+' reconcile interrupted turn' # PS5 no-BOM-safe source.
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Exact PC administrator required'}
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544');$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
$helper="$nativeRoot\migrate-lab-topics-65fc17bfcb9d47a190ab128b096bba5d.ps1"
if((Get-FileHash $helper).Hash -ne '86F3D550CBA51D280CE2D6BCDCBD7A3C3B1B1CBB7435FE9BC54590C0F87E6513' -or
 (Get-FileHash "$nativeRoot\stage-dut-topic.ps1").Hash -ne '0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF' -or
 (Get-FileHash "$nativeRoot\inspect-state.ps1").Hash -ne 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2'){throw 'Protected helper changed'}
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Helper parse failed'}
foreach($name in @('Protect','Save','Inspect')){$f=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true);if(-not $f){throw 'Missing helper'};. ([ScriptBlock]::Create($f.Extent.Text))}
function Original {
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code -or (Get-FileHash "$root\config.json").Hash -ne $policyDigest){throw 'Live code/policy changed; preserve'}
 $p=Get-Content "$root\config.json" -Raw|ConvertFrom-Json
 if($p.OwnerId -ne 110123423 -or $p.BotUsername -ne 'TheKhadangBot' -or -not $p.LinuxClaude.GuardedRecovery -or
  @($p.AdditionalChats|Where-Object {$_.Chat -eq -1003550185469 -and $_.IsForum}).Count -ne 1){throw 'Reviewed existing admission/recovery policy required'}
}
function SafeView($s){
 if($s.status.unknown -or @($s.bindings).Count -ne 12 -or @($s.status.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Twelve original bindings, connected Claude and no uncertain inputs required'}
 foreach($m in @($s.metadata|Where-Object {$_.key -like 'bubble/*'})){
  $b=$m.value
  if($b.sendUnknown -or @($b.pendingResponses).Count){throw 'Uncertain/pending delivery; do not fence'}
  if($b.busy -and ($m.key -ne "bubble/$controller" -or $b.held -or -not $b.turn)){throw 'Other active work or controller without recoverable exact turn'}
  if($b.held -and ($m.key -ne "bubble/$web" -or $b.busy -or $b.turn -or $b.status -ne $interruptedHold)){throw 'Unexpected hold; preserve'}
 }
}
function Stopped {if((Get-Service KhadangRouter).Status.ToString() -ne 'Stopped' -or (Get-ScheduledTask Oracova-KhadangStartup).State.ToString() -ne 'Disabled'){throw 'Stopped router and fenced startup required'}}
Original
$proof=Get-Content "$package\proof\result.json" -Raw -Encoding UTF8|ConvertFrom-Json;$binding=$proof.newPcBinding
if(-not $proof.complete -or -not $proof.handoffPersistedAndReadBack -or $proof.modelsStarted -or $proof.unknownEffects -ne 0 -or
 $proof.handoffSha256 -ne '7838378f68d3d79857b5889ff9d0c3d34cb78b11476d7d4802b6ca594d642bef' -or
 $binding.ThreadId -ne $thread -or $binding.Chat -ne -1003550185469 -or $binding.Topic -ne 6004 -or
 $binding.Backend -ne 'codex' -or $binding.Runtime -ne 'linux' -or $binding.Workspace -ne '/Users/pouya/.openclaw/workspace/kicad-copilot-research' -or
 (Get-ScheduledTask "Oracova-ManagedCodexProof-$generation").State.ToString() -ne 'Disabled'){throw 'Exact completed native checkpoint and fenced creation task required'}
if($Phase -eq 'fence'){
 if(Test-Path $release){throw 'Previous enrollment attempt; inspect without replay'}
 $s=Inspect;SafeView $s
 $service=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$task=Get-ScheduledTask Oracova-KhadangStartup
 if($service.State -ne 'Running' -or $service.StartName -ne 'LocalSystem' -or
  $service.PathName -cne ('"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"') -or
  $task.Actions.Count -ne 1 -or $task.Actions[0].Arguments -cne '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\ProgramData\OracovaNativeRemote\router-startup.ps1"'){throw 'Expected service/watchdog required'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 Save "$release\before.json" @{bindings=$s.bindings;nativeLinuxPid=$s.status.nativeLinuxPid;nativePid=$s.status.nativePid;controller=(@($s.metadata|Where-Object key -eq "bubble/$controller"))[0].value;
  inputOperations=@($s.receipts|Where-Object kind -in @('native/turn/start','native/turn/steer','claude/user/send-now','claude/control/answer'));at=[DateTimeOffset]::UtcNow.ToString('o')}
 [IO.File]::WriteAllText("$release\startup-before.xml",(Export-ScheduledTask Oracova-KhadangStartup),[Text.UTF8Encoding]::new($false))
 Copy-Item "$root\config.json" "$release\previous-config.json";Copy-Item "$root\state\probe.json" "$release\previous-probe.json"
 $capture='C:\ProgramData\OracovaMigration\kicad-cutover-'+$generation
 if(Test-Path $capture){throw 'Existing private capture; inspect'}
 $parent=Get-Acl 'C:\ProgramData\OracovaMigration'
 if(-not $parent.AreAccessRulesProtected -or (Get-Item 'C:\ProgramData\OracovaMigration').Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Protected migration parent required'}
 New-Item -ItemType Directory $capture|Out-Null;Protect $capture $true
 Copy-Item '\\wsl.localhost\Ubuntu-24.04\Users\pouya\.migration\kicad-cutover-TDGdy4Ga\*' $capture -Recurse
 Get-ChildItem $capture -Recurse -Force|ForEach-Object {Protect $_.FullName $_.PSIsContainer}
 $source=Get-Content "$capture\source\receipt.json" -Raw|ConvertFrom-Json
 if($source.phase -ne 'source-kicad-topic-fenced' -or $source.topic -ne 6004 -or $source.remainingBindings -ne 2 -or
  (Get-FileHash "$capture\source\source-history.private.json").Hash -ne '8D8FCCE53D23087FE2E259A1BFB6EC31AF65679D652ED4A0CBE1C5AE26899D24' -or
  (Get-FileHash "$capture\source\source-manifest.json").Hash -ne '9A3CE8E8B870EFC944DFFFE2257FF7EBE17301E693CDB4B1E45261E6034162FE'){throw 'Source fence/history changed'}
 Disable-ScheduledTask Oracova-KhadangStartup|Out-Null;Stop-ScheduledTask Oracova-KhadangStartup
 Stop-Service KhadangRouter -ErrorAction Continue
 (Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(10));Stopped
 Save "$release\fenced.json" @{sourceCapture=$capture;codeAndPolicyUnchanged=$true;nativeHostsRestarted=$false;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='fenced';nativeHostsRestarted=$false}|ConvertTo-Json -Compress;return
}
$fence=Get-Content "$release\fenced.json" -Raw|ConvertFrom-Json
if($Phase -eq 'stage'){
 Stopped;if(Test-Path "$release\staged.json"){throw 'Prior staging attempt; inspect'}
 $t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile("$nativeRoot\stage-dut-topic.ps1",[ref]$t,[ref]$e)
 $def=$a.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type' -and $n.Extent.Text -like '*class PcbaRegistry*'},$true)
 if($e.Count -or -not $def){throw 'Protected SQLite helper missing'}
 if(-not ('PcbaRegistry' -as [type])){& ([ScriptBlock]::Create($def.Extent.Text))}
 $exclusive=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null;$transaction=$false
 try{
  $db=[PcbaRegistry]::new()
  if([int]$db.Read("SELECT (SELECT COUNT(*) FROM operations WHERE status IN ('attempting','unknown') AND kind NOT LIKE 'telegram/edit%')+(SELECT COUNT(*) FROM updates WHERE status IN ('dispatching','unknown','received'))")[0][0]){throw 'Uncertain native/initial delivery; preserve'}
  $prior=$db.Read('SELECT payload FROM bindings ORDER BY chat,topic')
  if($prior.Length -ne 12 -or $db.Read('SELECT payload FROM bindings WHERE chat=-1003550185469 AND topic=6004').Length){throw 'Unexpected registry or enrollment already exists'}
  $before=Get-Content "$release\before.json" -Raw -Encoding UTF8|ConvertFrom-Json
  if((@($prior|ForEach-Object {$_[0]|ConvertFrom-Json})|Sort-Object Chat,Topic|ConvertTo-Json -Depth 20 -Compress) -cne ($before.bindings|Sort-Object Chat,Topic|ConvertTo-Json -Depth 20 -Compress)){throw 'Existing bindings changed'}
  $unrelated=$db.UnrelatedDigest();$backup="$release\previous-router.db"
  if(Test-Path $backup){throw 'Snapshot already exists; no replay'}
  $null=$db.Read("VACUUM INTO '"+$backup+"'");Protect $backup $false
  $null=$db.Read('BEGIN IMMEDIATE');$transaction=$true
  $json=$binding|ConvertTo-Json -Depth 8 -Compress;$hex=([BitConverter]::ToString([Text.Encoding]::UTF8.GetBytes($json))).Replace('-','')
  $null=$db.Read("INSERT INTO bindings(chat,topic,payload) VALUES(-1003550185469,6004,CAST(X'"+$hex+"' AS TEXT))")
  $retained=$db.Read('SELECT payload FROM bindings WHERE NOT(chat=-1003550185469 AND topic=6004) ORDER BY chat,topic')
  if($db.UnrelatedDigest() -ne $unrelated -or ($retained|ConvertTo-Json -Compress) -cne ($prior|ConvertTo-Json -Compress)){throw 'Unrelated ledger changed'}
  Original;$null=$db.Read('COMMIT');$transaction=$false
  Save "$release\staged.json" @{binding=$binding;unrelatedLedgerSha256=$unrelated;policyUnchanged=$true;existingBindingsPreserved=$true;at=[DateTimeOffset]::UtcNow.ToString('o')}
 }catch{if($transaction){$null=$db.Read('ROLLBACK')};throw}finally{if($db){$db.Dispose()};$exclusive.Dispose()}
 @{phase='staged';existingBindingsPreserved=$true;policyUnchanged=$true}|ConvertTo-Json -Compress;return
}
$staged=Get-Content "$release\staged.json" -Raw|ConvertFrom-Json
if($Phase -eq 'activate'){
 Stopped;Start-Service KhadangRouter
 @{phase='activation-started';nativeHostsRestarted=$false;modelPromptSent=$false}|ConvertTo-Json -Compress;return
}
$s=Inspect;$before=Get-Content "$release\before.json" -Raw -Encoding UTF8|ConvertFrom-Json
if($s.service -ne 'Running' -or [DateTimeOffset]$s.status.at -le [DateTimeOffset]$staged.at -or $s.status.unknown -or @($s.bindings).Count -ne 13 -or
 @($s.status.nativeSessions).Count -ne 13 -or @($s.status.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count -or
 $s.status.nativeLinuxPid -ne $before.nativeLinuxPid){throw 'Fresh thirteen routes, seven connected Claude and unchanged managed Linux host required'}
# nativePid is the router-owned Windows stdio child, recreated by every normal
# service start (Program.cs), not the independently supervised remote host.
$retained=@($s.bindings|Where-Object { -not ($_.Chat -eq -1003550185469 -and $_.Topic -eq 6004)})
if(($retained|Sort-Object Chat,Topic|ConvertTo-Json -Depth 20 -Compress) -cne ($before.bindings|Sort-Object Chat,Topic|ConvertTo-Json -Depth 20 -Compress)){throw 'Existing route changed'}
$new=@($s.status.nativeSessions|Where-Object {$_.binding.Chat -eq -1003550185469 -and $_.binding.Topic -eq 6004})
if($new.Count -ne 1 -or $new[0].binding.ThreadId -ne $thread){throw 'Exact KiCad native attachment missing'}
$newState=@($s.metadata|Where-Object key -eq "bubble/$thread")
if($newState.Count -ne 1 -or $newState[0].value.held -or $newState[0].value.busy -or $newState[0].value.sendUnknown -or
 @($newState[0].value.pendingResponses).Count -or $newState[0].value.status -ne 'Ready'){throw 'Exact KiCad bubble receipt not ready'}
$webState=@($s.metadata|Where-Object key -eq "bubble/$web")[0].value
if(-not $webState.held -or $webState.status -ne $interruptedHold){throw 'Web hold unexpectedly changed'}
$inputs=@($s.receipts|Where-Object kind -in @('native/turn/start','native/turn/steer','claude/user/send-now','claude/control/answer'))
if(($inputs|ConvertTo-Json -Depth 8 -Compress) -cne ($before.inputOperations|ConvertTo-Json -Depth 8 -Compress)){throw 'New/replayed native input observed; inspect'}
Enable-ScheduledTask Oracova-KhadangStartup|Out-Null
Save "$release\live-verified.json" @{routes=13;topic=6004;thread=$thread;backend='codex';existingBindingsPreserved=$true;policyUnchanged=$true;connectedClaude=7;managedLinuxHostUnchanged=$true;routerWindowsStdioRecreated=($s.status.nativePid -ne $before.nativePid);replayedInputs=0;webHoldPreserved=$true;phoneRoundTripVerified=$false;startupRestored=$true;at=[DateTimeOffset]::UtcNow.ToString('o')}
Get-Content "$release\live-verified.json" -Raw
