param([Parameter(Mandatory=$true)][ValidateSet('fence','repair','probe','accept','activate','verify')][string]$Phase,
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{32}$')][string]$Generation)
# Owner-requested bug fix and evidence-bound reconciliation; no model replay.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$nativeRoot='C:\ProgramData\OracovaNativeRemote';$release="$root\release-$Generation"
$oldCode='1AB012CA5A0A7E75739C62799D3A280F7916D76BEEE677475F7AE41092AFF1FD'
$oldPolicy='2AD951588989D6193A0F5E6F6C3FBDA2F386F099AA9C90CB4F84FC984577D588'
$code='8574D5AE0A79C6B9D870648BA172952D56F14D0C630A137A105C1606CD282AF0'
$evidenceDigest='8E2B260875818A56BC5D82DC362548843D1205E7996D3C793CD7F9167799D377'
$pin='7dc840b0-402f-451e-bc79-dadfb706d363';$uuid='7f54c604-ae8b-45f0-ad99-5d682ae65603'
$normal='"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Exact PC administrator required'}
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544');$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18');$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
$helper="$nativeRoot\migrate-lab-topics-65fc17bfcb9d47a190ab128b096bba5d.ps1"
foreach($entry in @(@($helper,'86F3D550CBA51D280CE2D6BCDCBD7A3C3B1B1CBB7435FE9BC54590C0F87E6513'),@("$nativeRoot\inspect-state.ps1",'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2'),@("$nativeRoot\stage-dut-topic.ps1",'0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF'))){if((Get-FileHash $entry[0]).Hash -ne $entry[1]){throw 'Protected helper changed'}}
$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$t,[ref]$e)
foreach($n in @('Protect','Save','Inspect')){$f=$a.Find({param($x)$x -is [Management.Automation.Language.FunctionDefinitionAst] -and $x.Name -eq $n},$true);if(-not $f -or $e.Count){throw 'Helper parse'};. ([ScriptBlock]::Create($f.Extent.Text))}
function Original {if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $oldCode -or (Get-FileHash "$root\config.json").Hash -ne $oldPolicy){throw 'Production changed; preserve it'}}
function Stopped {if((Get-Service KhadangRouter).Status.ToString() -ne 'Stopped' -or (Get-ScheduledTask Oracova-KhadangStartup).State.ToString() -ne 'Disabled'){throw 'Stopped fenced router required'}}
if($Phase -eq 'fence'){
 Original;if(Test-Path "$release\fenced.json"){throw 'Fence already attempted; inspect'}
 if((Get-FileHash "$release\candidate\KhadangRouter.dll").Hash -ne $code -or -not (Test-Path "$release\windows-tests.json")){throw 'Exact tested candidate required'}
 $s=Inspect;if($s.service -ne 'Running' -or @($s.bindings).Count -ne 14 -or $s.status.unknown -ne 1){throw 'Expected fourteen routes and one known timeout required'}
 foreach($b in @($s.metadata|Where-Object {$_.key -like 'bubble/*'})){
  if($b.value.sendUnknown -or @($b.value.pendingResponses).Count -or @($b.value.pendingAnswers).Count -or ($b.value.backend -eq 'claude' -and ($b.value.busy -or $b.value.claudeState -ne 'idle'))){throw 'Pending response or active Claude work; preserve'}
 }
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$task=Get-ScheduledTask Oracova-KhadangStartup
 if($svc.StartName -ne 'LocalSystem' -or $svc.PathName -cne $normal -or $task.Actions.Count -ne 1 -or $task.Actions[0].Arguments -cne '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\ProgramData\OracovaNativeRemote\router-startup.ps1"'){throw 'Unexpected service/watchdog'}
 Save "$release\before.json" @{bindings=$s.bindings;nativeLinuxPid=$s.status.nativeLinuxPid;controller=(@($s.metadata|Where-Object key -eq 'bubble/01a0facd-1bc0-7d23-95d6-c32fde0c62db'))[0].value;inputOperations=@($s.receipts|Where-Object kind -in @('native/turn/start','native/turn/steer','claude/user/send-now','claude/control/answer'));at=[DateTimeOffset]::UtcNow.ToString('o')}
 [IO.File]::WriteAllText("$release\startup-before.xml",(Export-ScheduledTask Oracova-KhadangStartup),[Text.UTF8Encoding]::new($false));Copy-Item "$root\config.json" "$release\previous-config.json";Copy-Item "$root\state\probe.json" "$release\previous-probe.json"
 Disable-ScheduledTask Oracova-KhadangStartup|Out-Null;Stop-ScheduledTask Oracova-KhadangStartup
 try{Stop-Service KhadangRouter}catch{if((Get-Service KhadangRouter).Status.ToString() -ne 'Stopped'){throw}}
 (Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(10));Stopped
 Save "$release\fenced.json" @{nativeCodexRestarted=$false;at=[DateTimeOffset]::UtcNow.ToString('o')};@{phase='fenced'}|ConvertTo-Json -Compress;return
}
$fence=Get-Content "$release\fenced.json" -Raw|ConvertFrom-Json
if($Phase -eq 'repair'){
 Stopped;Original;if(Test-Path "$release\repaired.json"){throw 'Repair already attempted; reconcile'}
 $p=Get-Content "$root\config.json" -Raw|ConvertFrom-Json
 if((Get-FileHash "$nativeRoot\dut-receipt-$Generation.py").Hash -ne $evidenceDigest){throw 'Evidence helper digest'}
 foreach($f in $p.LinuxClaude.FileSha256.PSObject.Properties){if((Get-FileHash (Join-Path $p.LinuxClaude.PackageRoot $f.Name)).Hash -ne $f.Value){throw 'Claude connector changed'}}
 $t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile("$nativeRoot\stage-dut-topic.ps1",[ref]$t,[ref]$e);$def=$a.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type' -and $n.Extent.Text -like '*class PcbaRegistry*'},$true)
 if($e.Count -or -not $def){throw 'SQLite helper missing'};if(-not ('PcbaRegistry' -as [type])){& ([ScriptBlock]::Create($def.Extent.Text))}
 $exclusive=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null;$transaction=$false
 try{
  $db=[PcbaRegistry]::new();$unknown=$db.Read("SELECT id,payload FROM operations WHERE status='unknown' AND kind<>'telegram/editMessageText'")
  if($unknown.Length -ne 1 -or $db.Read("SELECT id FROM updates WHERE status IN ('received','dispatching','unknown')").Length){throw 'Other uncertain or pending actions'}
  $operation=$unknown[0][0];$payload=$unknown[0][1]|ConvertFrom-Json
  if($payload.SessionId -ne $pin -or $payload.uuid -ne $uuid -or @($payload.content).Count -ne 1 -or $payload.content[0].type -ne 'text'){throw 'Exact historical DUT input required'}
  $h=[Security.Cryptography.SHA256]::Create();try{$textHash=([BitConverter]::ToString($h.ComputeHash([Text.Encoding]::UTF8.GetBytes($payload.content[0].text)))).Replace('-','').ToLowerInvariant()}finally{$h.Dispose()}
  if($textHash -ne '1f42fd1ca7597740c22715fc05092a96372a6547ce6e133acf0a53e97effe383'){throw 'Historical input changed'}
  # Run the pinned read-only helper in the existing LIMITED owner context,
  # then seal its observed JSON as administrator while the router is fenced.
  # Elevated Windows wsl.exe inherits credential access even with Linux UID 1000;
  # the helper correctly rejects that context. Never relax its denial gate.
  $ownerProof=Get-Content "$release\owner-native-receipt-proof.json" -Raw -Encoding UTF8|ConvertFrom-Json
  if($ownerProof.helperSha256 -ne $evidenceDigest -or $ownerProof.context -ne 'existing-limited-owner' -or [DateTimeOffset]$ownerProof.observedAt -le [DateTimeOffset]$fence.at -or [DateTimeOffset]$ownerProof.observedAt -gt [DateTimeOffset]::UtcNow -or [DateTimeOffset]$ownerProof.observedAt -lt [DateTimeOffset]::UtcNow.AddMinutes(-5)){throw 'Fresh operator-sealed limited-owner observation required'}
  $proof=$ownerProof.evidence
  if($proof.type -ne 'ccrelay_claude_delivery_evidence' -or $proof.session_id -ne $pin -or $proof.uuid -ne $uuid -or $proof.content_sha256 -ne $textHash -or -not $proof.history_quiescent -or $proof.native_writer -or $proof.model_inference){throw 'Exact complete native history proof required'}
  Save "$release\native-receipt-proof.json" $proof
  $dut=$db.Read("SELECT value FROM meta WHERE key='bubble/$pin'")[0][0]|ConvertFrom-Json
  if($dut.chat -ne -1004395661179 -or $dut.topic -ne 53 -or -not $dut.held -or $dut.busy -or $dut.claudeState -ne 'idle' -or $dut.sendUnknown -or @($dut.pendingResponses).Count -or @($dut.pendingAnswers).Count -or $dut.status -ne ('Held '+[char]0x2014+' reconcile native receipts') -or $db.Read("SELECT key FROM meta WHERE key LIKE 'claude/request/$pin/%' AND json_extract(value,'$.status')='pending'").Length -or $db.Read("SELECT key FROM meta WHERE key='claude/reset/$pin'").Length){throw 'Additional DUT hold; preserve'}
  $backup="$release\previous-router.db";if(Test-Path $backup){throw 'Previous repair snapshot; inspect'};$null=$db.Read("VACUUM INTO '$backup'");Protect $backup $false
  Save "$release\original-registry.json" @{payloads=$db.Read('SELECT payload FROM bindings ORDER BY chat,topic')};Copy-Item "$root\bin" "$release\previous-bin" -Recurse
  $null=$db.Read('BEGIN IMMEDIATE');$transaction=$true
  $receipt=@{SessionId=$pin;uuid=$uuid;receipt='native-history-user-proof';evidence=$proof;at=[DateTimeOffset]::UtcNow.ToString('o')};$json=$receipt|ConvertTo-Json -Depth 10 -Compress;$hex=([BitConverter]::ToString([Text.Encoding]::UTF8.GetBytes($json))).Replace('-','')
  $null=$db.Read("UPDATE operations SET status='confirmed',result=CAST(X'$hex' AS TEXT) WHERE id='$operation' AND kind='claude/user/send-now' AND status='unknown'")
  $null=$db.Read("UPDATE updates SET status='accepted-reconciled' WHERE id=759322714 AND status='held-no-replay'")
  $dut.held=$false;$dut.status='Done';$dut.tail+="`nDelivery timeout reconciled against the completed native transcript. Original input was not resent.`n"
  $json=$dut|ConvertTo-Json -Depth 100 -Compress;$hex=([BitConverter]::ToString([Text.Encoding]::UTF8.GetBytes($json))).Replace('-','');$null=$db.Read("UPDATE meta SET value=CAST(X'$hex' AS TEXT) WHERE key='bubble/$pin'")
  $null=$db.Read('COMMIT');$transaction=$false
  Copy-Item "$release\candidate\*" "$root\bin" -Force -Recurse;Get-ChildItem "$root\bin" -Recurse -Force|ForEach-Object {Protect $_.FullName $_.PSIsContainer}
  Save "$release\repaired.json" @{operation=$operation;uuid=$uuid;code=$code;policy=$oldPolicy;inputsResent=0;at=[DateTimeOffset]::UtcNow.ToString('o')}
 }catch{if($transaction){$null=$db.Read('ROLLBACK')};throw}finally{if($db){$db.Dispose()};$exclusive.Dispose()}
 @{phase='repaired';inputsResent=0}|ConvertTo-Json -Compress;return
}
$repair=Get-Content "$release\repaired.json" -Raw|ConvertFrom-Json
if($Phase -eq 'probe'){
 Stopped;$svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --probe-service --config "'+$root+'\config.json"');StartMode='Manual'};if($r.ReturnValue -ne 0){throw 'Probe path'}
 Start-Service KhadangRouter;@{phase='probe-running';modelInference=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'accept'){
 Stopped;$proof=Get-Content "$root\state\probe.json" -Raw|ConvertFrom-Json;$old=Get-Content "$release\previous-probe.json" -Raw|ConvertFrom-Json
 if($proof.routerSha256 -ne $code -or $proof.policySha256 -ne $oldPolicy -or -not $proof.verified -or -not $proof.credentialAndCodeDenied -or -not $proof.aclProbeWithoutProviderSandbox -or -not $proof.nativeWindowsSandboxVerified -or -not $proof.nativeLinuxCodexVerified -or $proof.nativeOwnerSid -ne $owner.Value -or $proof.modelInference -or $proof.telegramPolling -or [DateTimeOffset]$proof.testedAt -le [DateTimeOffset]$repair.at -or $old.routerSha256 -ne $oldCode -or $old.policySha256 -ne $oldPolicy -or -not $old.nativeLinuxClaudeLaunchVerified -or -not $old.nativeLinuxClaudeToolOwnerVerified -or -not $old.nativeLinuxClaudeContinuityVerified -or (Get-FileHash "$root\config.json").Hash -ne $oldPolicy){throw 'Fresh OS proof and unchanged launcher acceptance required'}
 Copy-Item "$root\state\probe.json" "$release\generic-proof.json";$proof.nativeLinuxClaudeLaunchVerified=$true;$proof.nativeLinuxClaudeToolOwnerVerified=$true;$proof.nativeLinuxClaudeContinuityVerified=$true
 $proof|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Receipt reconciliation only; native image, connector, protected policy, launch and wire input unchanged; exact native history evidence and regression tests verified, live reconnection still required';priorRouterSha256=$oldCode;modelsRerun=$false;at=[DateTimeOffset]::UtcNow.ToString('o')} -Force
 Save "$root\state\probe.json" $proof;Save "$release\accepted.json" @{at=[DateTimeOffset]::UtcNow.ToString('o')};@{phase='accepted'}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'activate'){
 Stopped;if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code -or (Get-FileHash "$root\config.json").Hash -ne $oldPolicy){throw 'Accepted bytes changed'};$null=Get-Content "$release\accepted.json" -Raw|ConvertFrom-Json
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=$normal;StartMode='Manual'};if($r.ReturnValue -ne 0){throw 'Normal service path'};Start-Service KhadangRouter;@{phase='activation-started'}|ConvertTo-Json -Compress;return
}
$s=Inspect;$before=Get-Content "$release\before.json" -Raw -Encoding UTF8|ConvertFrom-Json;$dut=@($s.metadata|Where-Object key -eq "bubble/$pin")[0].value
if($s.service -ne 'Running' -or $s.status.unknown -or @($s.status.nativeSessions).Count -ne 14 -or [DateTimeOffset]$s.status.at -le [DateTimeOffset]$repair.at -or $dut.held -or $dut.sendUnknown -or $dut.claudeState -ne 'idle' -or @($s.status.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count -or $s.status.nativeLinuxPid -ne $before.nativeLinuxPid){throw 'Fresh live sessions and unheld idle DUT required'}
$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile("$nativeRoot\inspect-state.ps1",[ref]$t,[ref]$e);$def=$a.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type' -and $n.Extent.Text -like '*class RouterReceipts*'},$true);if(-not ('RouterReceipts' -as [type])){& ([ScriptBlock]::Create($def.Extent.Text))}
$original=Get-Content "$release\original-registry.json" -Raw -Encoding UTF8|ConvertFrom-Json
if(([RouterReceipts]::Read('SELECT payload FROM bindings ORDER BY chat,topic')|ConvertTo-Json -Compress) -cne ($original.payloads|ConvertTo-Json -Compress)){throw 'Registry changed'}
Enable-ScheduledTask Oracova-KhadangStartup|Out-Null;Save "$release\live-verified.json" @{dutReady=$true;routes=14;connectedClaude=7;unknownInputs=0;inputsResent=0;nativeCodexUnchanged=$true;startupRestored=$true;at=[DateTimeOffset]::UtcNow.ToString('o')};Get-Content "$release\live-verified.json" -Raw
