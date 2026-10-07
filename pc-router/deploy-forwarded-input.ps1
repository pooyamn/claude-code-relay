param([Parameter(Mandatory=$true)][ValidateSet('prepare','fence','stage','probe','accept','activate','verify')][string]$Phase,
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{32}$')][string]$Generation,
 [Parameter(Mandatory=$true)][ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$CodeSha256)
# Owner-requested forwarded-file input fix. No input replay, native
# daemon restart, approval, account change, provider switch, or new poller.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$nativeRoot='C:\ProgramData\OracovaNativeRemote';$release="$root\release-$Generation"
$oldCode='3D6AA46818D7F566B857FD8D7110F7AF45E2194B54BEFCFC318B60F2FBA2A228'
$oldPolicy='5D5CE94F33EA9A925C872C58C2EACDA04FE6F9EBD112D878C20E6661795BB699'
$normal='"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Exact PC administrator required'}
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544');$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18');$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
$helper="$nativeRoot\migrate-lab-topics-65fc17bfcb9d47a190ab128b096bba5d.ps1"
foreach($entry in @(@($helper,'86F3D550CBA51D280CE2D6BCDCBD7A3C3B1B1CBB7435FE9BC54590C0F87E6513'),@("$nativeRoot\inspect-state.ps1",'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2'),@("$nativeRoot\stage-dut-topic.ps1",'0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF'))){if((Get-FileHash $entry[0]).Hash -ne $entry[1]){throw 'Protected helper changed'}}
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$t,[ref]$e)
foreach($name in @('Protect','Save')){$def=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true);if($e.Count -or -not $def){throw 'Protected helper syntax'};. ([ScriptBlock]::Create($def.Extent.Text))}
function WriteReceipt([string]$Path,$Value){Save $Path $Value;Protect $Path $false}
function Sql([string]$File,[string]$Class){$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($File,[ref]$t,[ref]$e);$d=$a.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type' -and $n.Extent.Text.Contains("class $Class")},$true);if($e.Count -or -not $d){throw 'Protected SQL helper syntax'};if(-not ($Class -as [type])){& ([ScriptBlock]::Create($d.Extent.Text))}}
function Original {if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $oldCode -or (Get-FileHash "$root\config.json").Hash -ne $oldPolicy){throw 'Production changed; preserve'}}
function Stopped {if((Get-Service KhadangRouter).Status.ToString() -ne 'Stopped' -or (Get-ScheduledTask Oracova-KhadangStartup).State.ToString() -ne 'Disabled'){throw 'Stopped fenced router required'}}
Sql "$nativeRoot\inspect-state.ps1" 'RouterReceipts'
if($Phase -eq 'prepare'){
 Original;if(Test-Path "$release\prepared.json"){throw 'Already prepared; reconcile'}
 if((Get-FileHash "$release\candidate\KhadangRouter.dll").Hash -ne $CodeSha256){throw 'Exact reviewed code required'}
 $output=(& "$release\candidate\KhadangRouter.exe" --self-test) -join "`n";if($LASTEXITCODE -ne 0){throw 'Windows router tests failed'}
 WriteReceipt "$release\prepared.json" @{code=$CodeSha256;output=$output;at=[DateTimeOffset]::UtcNow.ToString('o')}
 WriteReceipt "$release\windows-tests.json" @{code=$CodeSha256;output=$output;passed=$true;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='prepared';productionChanged=$false;tests=$output}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'fence'){
 Original;if(Test-Path "$release\fenced.json"){throw 'Already fenced; reconcile'}
 $tests=Get-Content "$release\windows-tests.json" -Raw|ConvertFrom-Json
 if(-not $tests.passed -or $tests.code -ne $CodeSha256){throw 'Full Windows regression suite required'}
 $s=Get-Content "$root\state\status.json" -Raw|ConvertFrom-Json
 if((Get-Service KhadangRouter).Status.ToString() -ne 'Running' -or $s.unknown -or @($s.bindings).Count -ne 16 -or $s.nativeLinuxPid -ne 479 -or [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-2) -or @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Expected connected sixteen routes required'}
 $bubbles=[RouterReceipts]::Read("SELECT key,value FROM meta WHERE key LIKE 'bubble/%'")
 foreach($row in $bubbles){$b=$row[1]|ConvertFrom-Json;if($b.sendUnknown -or @($b.finalAnswer.Parts|Where-Object SendUnknown).Count -or @($b.finalAnswer.Files|Where-Object SendUnknown).Count -or @($b.pendingAnswers|ForEach-Object {$_.Parts+$_.Files}|Where-Object SendUnknown).Count -or $b.backend -eq 'claude' -and ($b.busy -or $b.claudeState -ne 'idle')){throw 'Unknown output or active Claude; preserve'}}
 foreach($row in $bubbles){$b=$row[1]|ConvertFrom-Json;$id=$row[0].Substring(7);$route=@($s.bindings|Where-Object ThreadId -eq $id)
  if($b.busy -and ($route.Count -ne 1 -or $route[0].Runtime -ne 'linux' -or $route[0].Backend -ne 'codex' -or $b.held -or -not $b.turn)){throw 'Only independently supervised exact Linux turns may remain busy'}
 }
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";if($svc.PathName -cne $normal -or $svc.StartName -ne 'LocalSystem'){throw 'Expected protected service required'}
 WriteReceipt "$release\before.json" @{pid=$s.nativeLinuxPid;serviceMode=$svc.StartMode;bindings=[RouterReceipts]::Read('SELECT payload FROM bindings ORDER BY chat,topic');bubbles=$bubbles;inputOperations=[RouterReceipts]::Read("SELECT id,kind,status FROM operations WHERE kind IN ('native/turn/start','native/turn/steer','claude/user/send-now','claude/control/answer') ORDER BY id");at=[DateTimeOffset]::UtcNow.ToString('o')}
 Copy-Item "$root\config.json" "$release\previous-config.json";Copy-Item "$root\state\probe.json" "$release\previous-probe.json"
 WriteReceipt "$release\startup-before.json" @{state=(Get-ScheduledTask Oracova-KhadangStartup).State.ToString()}
 Disable-ScheduledTask Oracova-KhadangStartup|Out-Null;Stop-ScheduledTask Oracova-KhadangStartup
 try{Stop-Service KhadangRouter}catch{};(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Stopped
 WriteReceipt "$release\fenced.json" @{at=[DateTimeOffset]::UtcNow.ToString('o')};@{phase='fenced'}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'stage'){
 Stopped;Original;if(Test-Path "$release\staged.json"){throw 'Already staged; reconcile'}
 Sql "$nativeRoot\stage-dut-topic.ps1" 'PcbaRegistry'
 $exclusive=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null;$transaction=$false
 try{
  $db=[PcbaRegistry]::new()
  if([int]$db.Read("SELECT (SELECT COUNT(*) FROM operations WHERE status IN ('attempting','unknown') AND kind<>'telegram/editMessageText')+(SELECT COUNT(*) FROM updates WHERE status IN ('dispatching','unknown','received'))")[0][0]){throw 'Unknown/pending effects; preserve'}
  $prior=$db.UnrelatedDigest();$bindings=$db.Read('SELECT payload FROM bindings ORDER BY chat,topic')
  $null=$db.Read("VACUUM INTO '$release\previous-router.db'");Protect "$release\previous-router.db" $false;Copy-Item "$root\bin" "$release\previous-bin" -Recurse
  Copy-Item "$release\candidate\*" "$root\bin" -Recurse -Force;Get-ChildItem "$root\bin" -Recurse -Force|ForEach-Object {Protect $_.FullName $_.PSIsContainer}
  if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $CodeSha256 -or (Get-FileHash "$root\config.json").Hash -ne $oldPolicy){throw 'Staged code or unchanged policy mismatch'}
  if($db.UnrelatedDigest() -ne $prior -or ($db.Read('SELECT payload FROM bindings ORDER BY chat,topic')|ConvertTo-Json -Compress) -cne ($bindings|ConvertTo-Json -Compress)){throw 'Registry/ledger unexpectedly changed'}
  WriteReceipt "$release\staged.json" @{code=$CodeSha256;policy=$oldPolicy;at=[DateTimeOffset]::UtcNow.ToString('o')}
 }catch{if($transaction){$null=$db.Read('ROLLBACK')};throw}finally{if($db){$db.Dispose()};$exclusive.Dispose()}
 @{phase='staged';sessionsPreserved=$true;inputsResent=0}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'probe'){
 Stopped;$svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --probe-service --config "'+$root+'\config.json"');StartMode='Manual'}
 if($r.ReturnValue -ne 0){throw 'Probe service path failed'};Start-Service KhadangRouter;@{phase='probe-running';modelInference=$false;telegramPolling=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'accept'){
 Stopped;$stage=Get-Content "$release\staged.json" -Raw|ConvertFrom-Json;$proof=Get-Content "$root\state\probe.json" -Raw|ConvertFrom-Json;$old=Get-Content "$release\previous-probe.json" -Raw|ConvertFrom-Json
 if($proof.routerSha256 -ne $CodeSha256 -or $proof.policySha256 -ne $oldPolicy -or -not $proof.verified -or -not $proof.credentialAndCodeDenied -or -not $proof.aclProbeWithoutProviderSandbox -or -not $proof.nativeWindowsSandboxVerified -or -not $proof.nativeLinuxCodexVerified -or -not $proof.nativeLinuxCommandOwnerVerified -or $proof.nativeOwnerSid -ne 'S-1-5-21-71459778-1164188569-2276148161-1001' -or $proof.modelInference -or $proof.telegramPolling -or [DateTimeOffset]$proof.testedAt -le [DateTimeOffset]$stage.at -or $old.routerSha256 -ne $oldCode -or $old.policySha256 -ne $oldPolicy -or -not $old.nativeLinuxClaudeLaunchVerified -or -not $old.nativeLinuxClaudeToolOwnerVerified -or -not $old.nativeLinuxClaudeContinuityVerified){throw 'Fresh OS proof and unchanged Claude acceptance required'}
 if((Get-FileHash "$root\config.json").Hash -ne $oldPolicy){throw 'Protected policy changed'}
 Copy-Item "$root\state\probe.json" "$release\generic-proof.json";$proof.nativeLinuxClaudeLaunchVerified=$true;$proof.nativeLinuxClaudeToolOwnerVerified=$true;$proof.nativeLinuxClaudeContinuityVerified=$true
 $p=Get-Content "$root\config.json" -Raw|ConvertFrom-Json
 foreach($file in $p.LinuxClaude.FileSha256.PSObject.Properties){if((Get-FileHash (Join-Path $p.LinuxClaude.PackageRoot $file.Name)).Hash -ne $file.Value){throw 'Native Claude connector changed'}}
 $proof|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Human forward-content admission only; native dispatch, Claude launchers, connector and protected policy unchanged';priorCode=$oldCode;modelTestsRerun=$false} -Force
 WriteReceipt "$root\state\probe.json" $proof;WriteReceipt "$release\accepted.json" @{code=$CodeSha256;policy=$oldPolicy;at=[DateTimeOffset]::UtcNow.ToString('o')};@{phase='accepted';freshOsProof=$true}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'activate'){
 Stopped;$null=Get-Content "$release\accepted.json" -Raw|ConvertFrom-Json
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $CodeSha256 -or (Get-FileHash "$root\config.json").Hash -ne $oldPolicy){throw 'Accepted artifacts changed'}
 $before=Get-Content "$release\before.json" -Raw -Encoding UTF8|ConvertFrom-Json;$svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=$normal;StartMode=$before.serviceMode}
 if($r.ReturnValue -ne 0){throw 'Normal service path failed'};Start-Service KhadangRouter;@{phase='activated';nativeInputsSent=0}|ConvertTo-Json -Compress;return
}
$s=Get-Content "$root\state\status.json" -Raw|ConvertFrom-Json;$accepted=Get-Content "$release\accepted.json" -Raw|ConvertFrom-Json;$before=Get-Content "$release\before.json" -Raw -Encoding UTF8|ConvertFrom-Json
if((Get-Service KhadangRouter).Status.ToString() -ne 'Running' -or $s.unknown -or @($s.nativeSessions).Count -ne 16 -or $s.nativeLinuxPid -ne $before.pid -or [DateTimeOffset]$s.at -le [DateTimeOffset]$accepted.at -or @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Fresh connected routes and unchanged daemon required'}
foreach($row in $before.bubbles){$old=$row[1]|ConvertFrom-Json;if(-not $old.held){continue};$current=[RouterReceipts]::Read("SELECT value FROM meta WHERE key='$($row[0])'")[0][0]|ConvertFrom-Json;if(-not $current.held){throw 'Existing hold changed'}}
if(([RouterReceipts]::Read('SELECT payload FROM bindings ORDER BY chat,topic')|ConvertTo-Json -Compress) -cne ($before.bindings|ConvertTo-Json -Compress)){throw 'Registry changed'}
if(([RouterReceipts]::Read("SELECT id,kind,status FROM operations WHERE kind IN ('native/turn/start','native/turn/steer','claude/user/send-now','claude/control/answer') ORDER BY id")|ConvertTo-Json -Compress) -cne ($before.inputOperations|ConvertTo-Json -Compress)){throw 'Native input activity changed; inspect before claiming zero replay'}
$startup=Get-Content "$release\startup-before.json" -Raw|ConvertFrom-Json;if($startup.state -ne 'Disabled'){Enable-ScheduledTask Oracova-KhadangStartup|Out-Null}
WriteReceipt "$release\live-verified.json" @{forwardedFilesEnabled=$true;forwardedControlsDenied=$true;routes=16;unknown=0;heldSessions=$s.heldSessions;nativeDaemonUnchanged=$true;nativeInputsSent=0;historicalInputRetained=$true;startupRestored=$true;at=[DateTimeOffset]::UtcNow.ToString('o')}
Get-Content "$release\live-verified.json" -Raw
