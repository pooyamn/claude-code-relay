param([Parameter(Mandatory=$true)][ValidateSet('prepare','fence','stage','probe','accept','activate','verify')][string]$Phase)
# One owner-requested existing session. This is a pinned release recipe, not
# generic authorization to enroll arbitrary paths or replay native inputs.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$nativeRoot='C:\ProgramData\OracovaNativeRemote'
$generation='577db05e734d4bec830c7a20b86b129f'
$release="$root\release-$generation";$package="$nativeRoot\codex-connector-$generation"
$incoming='C:\Users\pou\workspaces\khadang-android.xxNyRy'
$oldCode='B1FA6AD0895F63E33035606A018F7609E252C42D7B26CAB8E062ED3FA66270D7'
$oldPolicy='7B6FA30311045122DEF25F07642EEF507DEB50AEFDFEA7F78D2BF0162E4D6D0B'
$code='1AB012CA5A0A7E75739C62799D3A280F7916D76BEEE677475F7AE41092AFF1FD'
$connector='36E0910AB58C635DE84AE9396AC598302116F2BC2AD86EC2252210A4FD7524A5'
$thread='01a104a5-c705-71b1-8614-c193d97da290';$controller='01a0facd-1bc0-7d23-95d6-c32fde0c62db'
$web='01a104a6-9fce-74a3-bdb0-e6dc04237ce7'
$normal='"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Exact PC administrator required'}
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544');$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
$helper="$nativeRoot\migrate-lab-topics-65fc17bfcb9d47a190ab128b096bba5d.ps1"
foreach($entry in @(@($helper,'86F3D550CBA51D280CE2D6BCDCBD7A3C3B1B1CBB7435FE9BC54590C0F87E6513'),@("$nativeRoot\stage-dut-topic.ps1",'0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF'),@("$nativeRoot\inspect-state.ps1",'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2'))){if((Get-FileHash $entry[0]).Hash -ne $entry[1]){throw 'Protected helper changed'}}
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Helper parse failed'}
foreach($name in @('Protect','Save','Inspect')){$f=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true);if(-not $f){throw 'Missing helper'};. ([ScriptBlock]::Create($f.Extent.Text))}
function Original {
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $oldCode -or (Get-FileHash "$root\config.json").Hash -ne $oldPolicy){throw 'Production changed; preserve'}
}
function Stopped {if((Get-Service KhadangRouter).Status.ToString() -ne 'Stopped' -or (Get-ScheduledTask Oracova-KhadangStartup).State.ToString() -ne 'Disabled'){throw 'Stopped fenced router required'}}
$created=Get-Content "$nativeRoot\codex-topic-$thread\result.json" -Raw|ConvertFrom-Json
if($created.phase -ne 'created-not-bound' -or $created.thread -ne $thread -or $created.chat -ne -1003550185469 -or $created.topic -ne 13750 -or $created.name -ne 'Android phone'){throw 'Exact durable creation receipt required'}
$binding=[ordered]@{Chat=[long]$created.chat;Topic=[int]$created.topic;Name=$created.name;Workspace='/Users/pouya/android router';ThreadId=$thread;Backend='codex';Runtime='linux'}
if($Phase -eq 'prepare'){
 Original
 if((Test-Path $package) -or (Test-Path "$release\prepared.json")){throw 'Existing preparation; reconcile'}
 if((Get-FileHash "$release\candidate\KhadangRouter.dll").Hash -ne $code -or (Get-FileHash "$incoming\pc_native_stdio.py").Hash -ne $connector){throw 'Reviewed artifacts required'}
 $p=Get-Content "$root\config.json" -Raw|ConvertFrom-Json
 New-Item -ItemType Directory $package|Out-Null;Protect $package $true $true
 New-Item -ItemType Directory "$package\relay_core"|Out-Null;Protect "$package\relay_core" $true $true
 foreach($f in $p.LinuxCodex.FileSha256.PSObject.Properties){
  $from=Join-Path $p.LinuxCodex.PackageRoot $f.Name;if((Get-FileHash $from).Hash -ne $f.Value){throw 'Accepted connector changed'}
  $to=Join-Path $package $f.Name;Copy-Item $from $to;Protect $to $false $true
 }
 Copy-Item "$incoming\pc_native_stdio.py" "$package\pc_native_stdio.py" -Force;Protect "$package\pc_native_stdio.py" $false $true
 if((Get-FileHash "$package\pc_native_stdio.py").Hash -ne $connector){throw 'Protected adapter mismatch'}
 Save "$release\prepared.json" @{code=$code;connector=$connector;binding=$binding;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='prepared';productionChanged=$false}|ConvertTo-Json -Compress;return
}
$prepared=Get-Content "$release\prepared.json" -Raw|ConvertFrom-Json
if($Phase -eq 'fence'){
 Original;if(Test-Path "$release\fenced.json"){throw 'Fence already attempted; reconcile'}
 $s=Inspect;$p=Get-Content "$root\config.json" -Raw|ConvertFrom-Json
 if($s.service -ne 'Running' -or $s.status.unknown -or @($s.bindings).Count -ne 13 -or $p.OwnerId -ne 110123423 -or $p.BotUsername -ne 'TheKhadangBot' -or -not $p.LinuxClaude.GuardedRecovery -or @($s.status.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Expected healthy thirteen routes required'}
 foreach($m in @($s.metadata|Where-Object {$_.key -like 'bubble/*'})){
  $b=$m.value
  if($b.sendUnknown -or @($b.pendingResponses).Count -or ($b.busy -and ($m.key -ne "bubble/$controller" -or $b.held -or -not $b.turn)) -or ($b.held -and $m.key -ne "bubble/$web")){throw 'Pending delivery or other active work; do not fence'}
 }
 $service=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$task=Get-ScheduledTask Oracova-KhadangStartup
 if($service.StartName -ne 'LocalSystem' -or $service.PathName -cne $normal -or $task.Actions.Count -ne 1 -or $task.Actions[0].Arguments -cne '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\ProgramData\OracovaNativeRemote\router-startup.ps1"'){throw 'Expected service/watchdog required'}
 Save "$release\before.json" @{bindings=$s.bindings;nativeLinuxPid=$s.status.nativeLinuxPid;nativePid=$s.status.nativePid;web=(@($s.metadata|Where-Object key -eq "bubble/$web"))[0].value;controller=(@($s.metadata|Where-Object key -eq "bubble/$controller"))[0].value;inputOperations=@($s.receipts|Where-Object kind -in @('native/turn/start','native/turn/steer','claude/user/send-now','claude/control/answer'));at=[DateTimeOffset]::UtcNow.ToString('o')}
 [IO.File]::WriteAllText("$release\startup-before.xml",(Export-ScheduledTask Oracova-KhadangStartup),[Text.UTF8Encoding]::new($false))
 Copy-Item "$root\config.json" "$release\previous-config.json";Copy-Item "$root\state\probe.json" "$release\previous-probe.json"
 Disable-ScheduledTask Oracova-KhadangStartup|Out-Null;Stop-ScheduledTask Oracova-KhadangStartup
 try{Stop-Service KhadangRouter}catch{if((Get-Service KhadangRouter).Status.ToString() -ne 'Stopped'){throw}}
 (Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(10));Stopped
 Save "$release\fenced.json" @{nativeHostsRestarted=$false;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='fenced';nativeHostsRestarted=$false}|ConvertTo-Json -Compress;return
}
$fence=Get-Content "$release\fenced.json" -Raw|ConvertFrom-Json
if($Phase -eq 'stage'){
 Stopped;Original;if(Test-Path "$release\staged.json"){throw 'Staging already attempted; reconcile'}
 $t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile("$nativeRoot\stage-dut-topic.ps1",[ref]$t,[ref]$e)
 $def=$a.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type' -and $n.Extent.Text -like '*class PcbaRegistry*'},$true)
 if($e.Count -or -not $def){throw 'SQLite helper missing'}
 if(-not ('PcbaRegistry' -as [type])){& ([ScriptBlock]::Create($def.Extent.Text))}
 $exclusive=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null;$transaction=$false
 try{
  $db=[PcbaRegistry]::new()
  if([int]$db.Read("SELECT (SELECT COUNT(*) FROM operations WHERE status IN ('attempting','unknown') AND kind NOT LIKE 'telegram/edit%')+(SELECT COUNT(*) FROM updates WHERE status IN ('dispatching','unknown','received'))")[0][0]){throw 'Uncertain delivery; preserve'}
  $prior=$db.Read('SELECT payload FROM bindings ORDER BY chat,topic')
  if($prior.Length -ne 13 -or $db.Read("SELECT payload FROM bindings WHERE (chat=-1003550185469 AND topic=13750) OR json_extract(payload,'$.ThreadId')='$thread'").Length){throw 'Unexpected registry or duplicate enrollment'}
  $before=Get-Content "$release\before.json" -Raw -Encoding UTF8|ConvertFrom-Json
  # The PS5 native-command inspection view can corrupt Unicode display names.
  # Match routing identity there, but preserve and compare actual SQLite bytes.
  if((@($prior|ForEach-Object {$_[0]|ConvertFrom-Json})|Sort-Object Chat,Topic|Select-Object Chat,Topic,Workspace,ThreadId,Backend,Runtime|ConvertTo-Json -Depth 20 -Compress) -cne ($before.bindings|Sort-Object Chat,Topic|Select-Object Chat,Topic,Workspace,ThreadId,Backend,Runtime|ConvertTo-Json -Depth 20 -Compress)){throw 'Routing identity changed'}
  Save "$release\registry-before.json" @{payloads=$prior}
  $unrelated=$db.UnrelatedDigest();$backup="$release\previous-router.db";if(Test-Path $backup){throw 'Existing snapshot; reconcile'}
  $null=$db.Read("VACUUM INTO '"+$backup+"'");Protect $backup $false
  Copy-Item "$root\bin" "$release\previous-bin" -Recurse
  $p=Get-Content "$root\config.json" -Raw|ConvertFrom-Json;$p.LinuxCodex.PackageRoot=$package;$p.LinuxCodex.FileSha256.'pc_native_stdio.py'=$connector.ToLowerInvariant()
  Save "$release\candidate-config.json" $p
  $null=$db.Read('BEGIN IMMEDIATE');$transaction=$true
  $json=$binding|ConvertTo-Json -Depth 8 -Compress;$hex=([BitConverter]::ToString([Text.Encoding]::UTF8.GetBytes($json))).Replace('-','')
  $null=$db.Read("INSERT INTO bindings(chat,topic,payload) VALUES(-1003550185469,13750,CAST(X'"+$hex+"' AS TEXT))")
  $retained=$db.Read('SELECT payload FROM bindings WHERE NOT(chat=-1003550185469 AND topic=13750) ORDER BY chat,topic')
  if($db.UnrelatedDigest() -ne $unrelated -or ($retained|ConvertTo-Json -Compress) -cne ($prior|ConvertTo-Json -Compress)){throw 'Unrelated ledger changed'}
  $null=$db.Read('COMMIT');$transaction=$false
  Copy-Item "$release\candidate-config.json" "$root\config.json" -Force;Protect "$root\config.json" $false
  Copy-Item "$release\candidate\*" "$root\bin" -Force -Recurse;Get-ChildItem "$root\bin" -Recurse -Force|ForEach-Object {Protect $_.FullName $_.PSIsContainer}
  if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code){throw 'Staged code digest'}
  Save "$release\staged.json" @{code=$code;policy=(Get-FileHash "$root\config.json").Hash;binding=$binding;unrelatedLedgerSha256=$unrelated;at=[DateTimeOffset]::UtcNow.ToString('o')}
 }catch{if($transaction){$null=$db.Read('ROLLBACK')};throw}finally{if($db){$db.Dispose()};$exclusive.Dispose()}
 @{phase='staged';existingBindingsPreserved=$true}|ConvertTo-Json -Compress;return
}
$staged=Get-Content "$release\staged.json" -Raw|ConvertFrom-Json
if($Phase -eq 'probe'){
 Stopped;$service=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $r=Invoke-CimMethod -InputObject $service -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --probe-service --config "'+$root+'\config.json"');StartMode='Manual'}
 if($r.ReturnValue -ne 0){throw 'Probe service configuration failed'}
 Start-Service KhadangRouter;@{phase='probe-running';modelInference=$false;telegramPolling=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'accept'){
 Stopped;$p=Get-Content "$root\state\probe.json" -Raw|ConvertFrom-Json;$old=Get-Content "$release\previous-probe.json" -Raw|ConvertFrom-Json
 if($p.policySha256 -ne $staged.policy -or $p.routerSha256 -ne $code -or -not $p.verified -or -not $p.credentialAndCodeDenied -or -not $p.aclProbeWithoutProviderSandbox -or -not $p.nativeWindowsSandboxVerified -or -not $p.nativeLinuxCodexVerified -or -not $p.nativeLinuxCommandOwnerVerified -or $p.nativeOwnerSid -ne $owner.Value -or $p.modelInference -or $p.telegramPolling -or [DateTimeOffset]$p.testedAt -le [DateTimeOffset]$staged.at -or $old.policySha256 -ne $oldPolicy -or $old.routerSha256 -ne $oldCode -or -not $old.nativeLinuxClaudeLaunchVerified -or -not $old.nativeLinuxClaudeToolOwnerVerified -or -not $old.nativeLinuxClaudeContinuityVerified){throw 'Fresh OS proof and unchanged Claude acceptance required'}
 $current=Get-Content "$root\config.json" -Raw|ConvertFrom-Json;$prior=Get-Content "$release\previous-config.json" -Raw|ConvertFrom-Json
 if(($current.LinuxClaude|ConvertTo-Json -Depth 30 -Compress) -cne ($prior.LinuxClaude|ConvertTo-Json -Depth 30 -Compress)){throw 'Claude connector changed; prior acceptance is not reusable'}
 Copy-Item "$root\state\probe.json" "$release\generic-proof.json"
 $p.nativeLinuxClaudeLaunchVerified=$true;$p.nativeLinuxClaudeToolOwnerVerified=$true;$p.nativeLinuxClaudeContinuityVerified=$true
 $p|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Codex-only literal workspace admission; Claude connector, native executable, input paths and saved IDs unchanged; live reconnect must be verified';priorRouterSha256=$oldCode;modelsRerun=$false;at=[DateTimeOffset]::UtcNow.ToString('o')} -Force
 Save "$root\state\probe.json" $p;Save "$release\accepted.json" @{code=$code;policy=$staged.policy;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='accepted';freshOsProof=$true}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'activate'){
 Stopped;$accepted=Get-Content "$release\accepted.json" -Raw|ConvertFrom-Json
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $accepted.code -or (Get-FileHash "$root\config.json").Hash -ne $accepted.policy){throw 'Accepted artifacts changed'}
 $service=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $service -MethodName Change -Arguments @{PathName=$normal;StartMode='Manual'}
 if($r.ReturnValue -ne 0){throw 'Normal service configuration failed'}
 Start-Service KhadangRouter;@{phase='activation-started';modelPromptSent=$false}|ConvertTo-Json -Compress;return
}
$s=Inspect;$before=Get-Content "$release\before.json" -Raw -Encoding UTF8|ConvertFrom-Json;$accepted=Get-Content "$release\accepted.json" -Raw|ConvertFrom-Json
if($s.service -ne 'Running' -or [DateTimeOffset]$s.status.at -le [DateTimeOffset]$accepted.at -or $s.status.unknown -or @($s.bindings).Count -ne 14 -or @($s.status.nativeSessions).Count -ne 14 -or @($s.status.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count -or $s.status.nativeLinuxPid -ne $before.nativeLinuxPid){throw 'Fresh fourteen routes, connected Claude and unchanged Linux daemon required'}
$retained=@($s.bindings|Where-Object {-not ($_.Chat -eq -1003550185469 -and $_.Topic -eq 13750)})
if(($retained|Sort-Object Chat,Topic|Select-Object Chat,Topic,Workspace,ThreadId,Backend,Runtime|ConvertTo-Json -Depth 20 -Compress) -cne ($before.bindings|Sort-Object Chat,Topic|Select-Object Chat,Topic,Workspace,ThreadId,Backend,Runtime|ConvertTo-Json -Depth 20 -Compress)){throw 'Existing route changed'}
$registryBefore=Get-Content "$release\registry-before.json" -Raw -Encoding UTF8|ConvertFrom-Json
$rt=$null;$re=$null;$ra=[Management.Automation.Language.Parser]::ParseFile("$nativeRoot\inspect-state.ps1",[ref]$rt,[ref]$re)
$rd=$ra.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type' -and $n.Extent.Text -like '*class RouterReceipts*'},$true)
if($re.Count -or -not $rd){throw 'Read-only registry helper missing'}
if(-not ('RouterReceipts' -as [type])){& ([ScriptBlock]::Create($rd.Extent.Text))}
$registryRetained=[RouterReceipts]::Read('SELECT payload FROM bindings WHERE NOT(chat=-1003550185469 AND topic=13750) ORDER BY chat,topic')
if(($registryRetained|ConvertTo-Json -Compress) -cne ($registryBefore.payloads|ConvertTo-Json -Compress)){throw 'Original registry payload changed'}
$new=@($s.status.nativeSessions|Where-Object {$_.binding.Chat -eq -1003550185469 -and $_.binding.Topic -eq 13750})
$bubble=@($s.metadata|Where-Object key -eq "bubble/$thread")
if($new.Count -ne 1 -or $new[0].binding.ThreadId -ne $thread -or $new[0].binding.Workspace -ne $binding.Workspace -or $bubble.Count -ne 1 -or $bubble[0].value.held -or $bubble[0].value.sendUnknown -or @($bubble[0].value.pendingResponses).Count){throw 'Exact Android attachment missing or held'}
$webNow=@($s.metadata|Where-Object key -eq "bubble/$web")[0].value
if($webNow.held -ne $before.web.held -or $webNow.status -ne $before.web.status){throw 'Web hold changed'}
$inputs=@($s.receipts|Where-Object kind -in @('native/turn/start','native/turn/steer','claude/user/send-now','claude/control/answer'))
if(($inputs|ConvertTo-Json -Depth 8 -Compress) -cne ($before.inputOperations|ConvertTo-Json -Depth 8 -Compress)){throw 'New or replayed native input observed; inspect'}
Enable-ScheduledTask Oracova-KhadangStartup|Out-Null
Save "$release\live-verified.json" @{routes=14;topic=13750;thread=$thread;backend='codex';existingBindingsPreserved=$true;connectedClaude=7;managedLinuxHostUnchanged=$true;replayedInputs=0;webHoldPreserved=$true;phoneRoundTripVerified=$false;startupRestored=$true;at=[DateTimeOffset]::UtcNow.ToString('o')}
Get-Content "$release\live-verified.json" -Raw
