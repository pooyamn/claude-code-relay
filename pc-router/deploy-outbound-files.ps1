param([Parameter(Mandatory=$true)][ValidateSet('prepare','fence','stage','probe','accept','activate','verify')][string]$Phase,
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{32}$')][string]$Generation,
 [Parameter(Mandatory=$true)][ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$CodeSha256,
 [Parameter(Mandatory=$true)][ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$ConnectorSha256)
# Pinned owner-requested outbound fix. Exactly one already-authorized DUT X
# attachment repair; no model prompt, invented input, session switch or poller.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$nativeRoot='C:\ProgramData\OracovaNativeRemote'
$release="$root\release-$Generation";$package="$nativeRoot\codex-connector-$Generation"
$oldCode='8574D5AE0A79C6B9D870648BA172952D56F14D0C630A137A105C1606CD282AF0'
$oldPolicy='04934665D6699D3AF39594A09C368BDAD5C0C8B0E245AE59C0EE1E4DFBBBA02A'
$pin='01a1122c-c62d-75f2-9b47-9ad9adcdf7d5';$project='/Users/pouya/.openclaw/workspace/ai-hil/hardware/duts/dut-x'
$normal='"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Exact PC administrator required'}
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544');$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18');$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
function Protect([string]$Path,[bool]$Directory,[bool]$Readable=$false){
 if((Get-Item $Path).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Literal artifact required'}
 if($Directory){$acl=[Security.AccessControl.DirectorySecurity]::new();$inherit=[Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'}
 else{$acl=[Security.AccessControl.FileSecurity]::new();$inherit=[Security.AccessControl.InheritanceFlags]::None}
 $acl.SetOwner($admin);$acl.SetAccessRuleProtection($true,$false)
 foreach($sid in @($admin,$system)){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl',$inherit,'None','Allow'))}
 if($Readable){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($owner,'ReadAndExecute',$inherit,'None','Allow'))};Set-Acl $Path $acl
}
function Save([string]$Path,$Value){[IO.File]::WriteAllText($Path,($Value|ConvertTo-Json -Depth 100),[Text.UTF8Encoding]::new($false));Protect $Path $false}
function Original {if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $oldCode -or (Get-FileHash "$root\config.json").Hash -ne $oldPolicy){throw 'Production changed; preserve'}}
function Stopped {if((Get-Service KhadangRouter).Status.ToString() -ne 'Stopped' -or (Get-ScheduledTask Oracova-KhadangStartup).State.ToString() -ne 'Disabled'){throw 'Stopped fenced router required'}}
foreach($entry in @(@("$nativeRoot\inspect-state.ps1",'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2'),@("$nativeRoot\stage-dut-topic.ps1",'0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF'))){if((Get-FileHash $entry[0]).Hash -ne $entry[1]){throw 'Protected helper changed'}}
function ImportSql([string]$File,[string]$Class){
 $t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($File,[ref]$t,[ref]$e)
 $def=$a.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type' -and $n.Extent.Text.Contains("class $Class")},$true)
 if($e.Count -or -not $def){throw 'Pinned SQL helper missing'};if(-not ($Class -as [type])){& ([ScriptBlock]::Create($def.Extent.Text))}
}
if($Phase -eq 'prepare'){
 Original;if(Test-Path "$release\prepared.json"){throw 'Preparation already exists; reconcile'}
 if((Get-FileHash "$release\candidate\KhadangRouter.dll").Hash -ne $CodeSha256 -or (Get-FileHash "$release\pc_native_stdio.py").Hash -ne $ConnectorSha256){throw 'Reviewed artifact digest required'}
 $output=(& "$release\candidate\KhadangRouter.exe" --self-test-files) -join "`n";if($LASTEXITCODE -ne 0){throw 'Windows outbound tests failed'}
 Save "$release\file-tests.json" @{output=$output;code=$CodeSha256;at=[DateTimeOffset]::UtcNow.ToString('o')}
 $p=Get-Content "$root\config.json" -Raw|ConvertFrom-Json
 if(Test-Path $package){throw 'Package generation already exists'};New-Item -ItemType Directory $package|Out-Null;Protect $package $true $true
 New-Item -ItemType Directory "$package\relay_core"|Out-Null;Protect "$package\relay_core" $true $true
 foreach($f in $p.LinuxCodex.FileSha256.PSObject.Properties){
  $from=Join-Path $p.LinuxCodex.PackageRoot $f.Name;if((Get-FileHash $from).Hash -ne $f.Value){throw 'Accepted package changed'}
  $to=Join-Path $package $f.Name;Copy-Item $from $to;Protect $to $false $true
 }
 Copy-Item "$release\pc_native_stdio.py" "$package\pc_native_stdio.py" -Force;Protect "$package\pc_native_stdio.py" $false $true
 if((Get-FileHash "$package\pc_native_stdio.py").Hash -ne $ConnectorSha256){throw 'Sealed connector mismatch'}
 Save "$release\prepared.json" @{code=$CodeSha256;connector=$ConnectorSha256;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='prepared';productionChanged=$false;windowsFileTests=$output}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'fence'){
 Original;if(Test-Path "$release\fenced.json"){throw 'Already fenced; reconcile'}
 $tests=Get-Content "$release\windows-tests.json" -Raw|ConvertFrom-Json
 if(-not $tests.passed -or $tests.code -ne $CodeSha256){throw 'Full Windows regression suite required'}
 ImportSql "$nativeRoot\inspect-state.ps1" 'RouterReceipts'
 $s=Get-Content "$root\state\status.json" -Raw|ConvertFrom-Json
 if((Get-Service KhadangRouter).Status.ToString() -ne 'Running' -or $s.unknown -or @($s.bindings).Count -ne 15 -or $s.nativeLinuxPid -ne 479){throw 'Expected healthy fifteen routes required'}
 $bubbles=[RouterReceipts]::Read("SELECT value FROM meta WHERE key LIKE 'bubble/%'")
 foreach($row in $bubbles){$b=$row[0]|ConvertFrom-Json;if($b.sendUnknown -or @($b.pendingAnswers).Count -or @($b.pendingResponses).Count -or $b.backend -eq 'claude' -and ($b.busy -or $b.claudeState -ne 'idle')){throw 'Pending output or active Claude; do not stop'}}
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 if($svc.PathName -cne $normal -or $svc.StartName -ne 'LocalSystem'){throw 'Expected protected service required'}
 Save "$release\before.json" @{pid=$s.nativeLinuxPid;serviceMode=$svc.StartMode;bindings=[RouterReceipts]::Read('SELECT payload FROM bindings ORDER BY chat,topic');bubbles=$bubbles;inputOperations=[RouterReceipts]::Read("SELECT id,kind,status FROM operations WHERE kind IN ('native/turn/start','native/turn/steer','claude/user/send-now','claude/control/answer') ORDER BY id");at=[DateTimeOffset]::UtcNow.ToString('o')}
 Copy-Item "$root\config.json" "$release\previous-config.json";Copy-Item "$root\state\probe.json" "$release\previous-probe.json"
 Save "$release\startup-before.json" @{state=(Get-ScheduledTask Oracova-KhadangStartup).State.ToString()}
 Disable-ScheduledTask Oracova-KhadangStartup|Out-Null;Stop-ScheduledTask Oracova-KhadangStartup
 try{Stop-Service KhadangRouter}catch{if((Get-Service KhadangRouter).Status.ToString() -ne 'Stopped'){throw}}
 (Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(10));Stopped
 Save "$release\fenced.json" @{at=[DateTimeOffset]::UtcNow.ToString('o')};@{phase='fenced'}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'stage'){
 Stopped;Original;if(Test-Path "$release\staged.json"){throw 'Already staged; reconcile'}
 ImportSql "$nativeRoot\stage-dut-topic.ps1" 'PcbaRegistry'
 $exclusive=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null;$transaction=$false
 try{
  $db=[PcbaRegistry]::new()
  if([int]$db.Read("SELECT (SELECT COUNT(*) FROM operations WHERE status IN ('attempting','unknown') AND kind NOT LIKE 'telegram/edit%')+(SELECT COUNT(*) FROM updates WHERE status IN ('dispatching','unknown','received'))")[0][0]){throw 'Uncertain/pending action; preserve'}
  if($db.Read("SELECT id FROM operations WHERE kind IN ('telegram/sendPhoto','telegram/sendDocument')").Length -or $db.Read("SELECT key FROM meta WHERE key='outbound-repair/dut-x-20261006'").Length){throw 'Existing upload or repair; reconcile before resend'}
  $binding=$db.Read("SELECT payload FROM bindings WHERE chat=-1004395661179 AND topic=4901")[0][0]|ConvertFrom-Json
  if($binding.ThreadId -ne $pin -or $binding.Workspace -ne $project -or $binding.Backend -ne 'codex' -or $binding.Runtime -ne 'linux'){throw 'Exact preserved DUT X route required'}
  $bubble=$db.Read("SELECT value FROM meta WHERE key='bubble/$pin'")[0][0]|ConvertFrom-Json
  if($bubble.held -or $bubble.sendUnknown -or @($bubble.pendingAnswers).Count -or @($bubble.pendingResponses).Count){throw 'DUT X uncertain output; preserve'}
  $null=$db.Read("VACUUM INTO '$release\previous-router.db'");Protect "$release\previous-router.db" $false
  Copy-Item "$root\bin" "$release\previous-bin" -Recurse
  $p=Get-Content "$root\config.json" -Raw|ConvertFrom-Json;$p.LinuxCodex.PackageRoot=$package;$p.LinuxCodex.FileSha256.'pc_native_stdio.py'=$ConnectorSha256.ToLowerInvariant()
  Save "$release\candidate-config.json" $p
  $files=@(@{Path="$project/kicad-hier/placement-overview.png";Sha256=$null;Size=$null;Document=$false;Message=$null;SendUnknown=$false;Failure=$null},@{Path="$project/dist/dut-x-initial-placement.zip";Sha256=$null;Size=$null;Document=$true;Message=$null;SendUnknown=$false;Failure=$null})
  $answer=@{Candidate='';Explicit=$true;Completed=$true;Parts=@();Files=$files}
  $bubble.pendingAnswers=@($answer) # Preserve all delivered prose/bubbles; files only.
  $null=$db.Read('BEGIN IMMEDIATE');$transaction=$true
  $json=$bubble|ConvertTo-Json -Depth 100 -Compress;$hex=([BitConverter]::ToString([Text.Encoding]::UTF8.GetBytes($json))).Replace('-','')
  $null=$db.Read("UPDATE meta SET value=CAST(X'$hex' AS TEXT) WHERE key='bubble/$pin'")
  $receipt=@{thread=$pin;chat=[long]-1004395661179;topic=4901;files=$files;generation=$Generation;at=[DateTimeOffset]::UtcNow.ToString('o')}|ConvertTo-Json -Depth 10 -Compress;$hex=([BitConverter]::ToString([Text.Encoding]::UTF8.GetBytes($receipt))).Replace('-','')
  $null=$db.Read("INSERT INTO meta VALUES('outbound-repair/dut-x-20261006',CAST(X'$hex' AS TEXT))")
  $null=$db.Read('COMMIT');$transaction=$false
  Copy-Item "$release\candidate-config.json" "$root\config.json" -Force;Protect "$root\config.json" $false
  Copy-Item "$release\candidate\*" "$root\bin" -Recurse -Force;Get-ChildItem "$root\bin" -Recurse -Force|ForEach-Object {Protect $_.FullName $_.PSIsContainer}
  if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $CodeSha256){throw 'Staged code mismatch'}
  Save "$release\staged.json" @{code=$CodeSha256;policy=(Get-FileHash "$root\config.json").Hash;at=[DateTimeOffset]::UtcNow.ToString('o')}
 }catch{if($transaction){$null=$db.Read('ROLLBACK')};throw}finally{if($db){$db.Dispose()};$exclusive.Dispose()}
 @{phase='staged';sessionsPreserved=$true;filesOnlyRepair=$true}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'probe'){
 Stopped;$svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --probe-service --config "'+$root+'\config.json"');StartMode='Manual'}
 if($r.ReturnValue -ne 0){throw 'Probe service path failed'};Start-Service KhadangRouter
 @{phase='probe-running';modelInference=$false;telegramPolling=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'accept'){
 Stopped;$staged=Get-Content "$release\staged.json" -Raw|ConvertFrom-Json;$proof=Get-Content "$root\state\probe.json" -Raw|ConvertFrom-Json;$old=Get-Content "$release\previous-probe.json" -Raw|ConvertFrom-Json
 if($proof.routerSha256 -ne $CodeSha256 -or $proof.policySha256 -ne $staged.policy -or -not $proof.verified -or -not $proof.credentialAndCodeDenied -or -not $proof.aclProbeWithoutProviderSandbox -or -not $proof.nativeWindowsSandboxVerified -or -not $proof.nativeLinuxCodexVerified -or -not $proof.nativeLinuxCommandOwnerVerified -or $proof.nativeOwnerSid -ne $owner.Value -or $proof.modelInference -or $proof.telegramPolling -or [DateTimeOffset]$proof.testedAt -le [DateTimeOffset]$staged.at -or $old.routerSha256 -ne $oldCode -or $old.policySha256 -ne $oldPolicy -or -not $old.nativeLinuxClaudeLaunchVerified -or -not $old.nativeLinuxClaudeToolOwnerVerified -or -not $old.nativeLinuxClaudeContinuityVerified){throw 'Fresh OS proof and existing Claude acceptance required'}
 $p=Get-Content "$root\config.json" -Raw|ConvertFrom-Json;$prior=Get-Content "$release\previous-config.json" -Raw|ConvertFrom-Json
 if(($p.LinuxClaude|ConvertTo-Json -Depth 100 -Compress) -cne ($prior.LinuxClaude|ConvertTo-Json -Depth 100 -Compress)){throw 'Claude launcher changed; acceptance cannot be reused'}
 Copy-Item "$root\state\probe.json" "$release\generic-proof.json"
 $proof.nativeLinuxClaudeLaunchVerified=$true;$proof.nativeLinuxClaudeToolOwnerVerified=$true;$proof.nativeLinuxClaudeContinuityVerified=$true
 $proof|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Outbound delivery only; native Claude executable, connector, inputs and session pins unchanged';priorCode=$oldCode;modelTestsRerun=$false} -Force
 Save "$root\state\probe.json" $proof;Save "$release\accepted.json" @{code=$CodeSha256;policy=$staged.policy;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='accepted';freshOsProof=$true}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'activate'){
 Stopped;$accepted=Get-Content "$release\accepted.json" -Raw|ConvertFrom-Json
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $accepted.code -or (Get-FileHash "$root\config.json").Hash -ne $accepted.policy){throw 'Accepted artifacts changed'}
 $before=Get-Content "$release\before.json" -Raw -Encoding UTF8|ConvertFrom-Json
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=$normal;StartMode=$before.serviceMode}
 if($r.ReturnValue -ne 0){throw 'Normal service path failed'};Start-Service KhadangRouter
 @{phase='activated';modelPromptSent=$false}|ConvertTo-Json -Compress;return
}
ImportSql "$nativeRoot\inspect-state.ps1" 'RouterReceipts'
$s=Get-Content "$root\state\status.json" -Raw|ConvertFrom-Json;$before=Get-Content "$release\before.json" -Raw -Encoding UTF8|ConvertFrom-Json;$accepted=Get-Content "$release\accepted.json" -Raw|ConvertFrom-Json
if((Get-Service KhadangRouter).Status.ToString() -ne 'Running' -or $s.unknown -or @($s.nativeSessions).Count -ne 15 -or $s.nativeLinuxPid -ne $before.pid -or [DateTimeOffset]$s.at -le [DateTimeOffset]$accepted.at -or @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Fresh live routes and unchanged daemon required'}
if(([RouterReceipts]::Read('SELECT payload FROM bindings ORDER BY chat,topic')|ConvertTo-Json -Compress) -cne ($before.bindings|ConvertTo-Json -Compress)){throw 'Registry changed'}
$uploads=[RouterReceipts]::Read("SELECT kind,payload,result FROM operations WHERE kind IN ('telegram/sendPhoto','telegram/sendDocument') AND status='confirmed'")
if($uploads.Length -ne 2){throw 'Two confirmed media uploads required'}
$receipts=@();foreach($row in $uploads){$sent=$row[2]|ConvertFrom-Json;$payload=$row[1]|ConvertFrom-Json;if($sent.chat.id -ne -1004395661179 -or $sent.message_thread_id -ne 4901 -or $payload.message_thread_id -ne 4901 -or $sent.message_id -le 0){throw 'Upload destination mismatch'};$receipts+=@{kind=$row[0];filename=$payload.filename;size=$payload.size;sha256=$payload.sha256;message=$sent.message_id}}
if(@($receipts|Where-Object {$_.kind -eq 'telegram/sendPhoto' -and $_.filename -eq 'placement-overview.png'}).Count -ne 1 -or @($receipts|Where-Object {$_.kind -eq 'telegram/sendDocument' -and $_.filename -eq 'dut-x-initial-placement.zip'}).Count -ne 1){throw 'Exact PNG and ZIP receipts required'}
if(([RouterReceipts]::Read("SELECT id,kind,status FROM operations WHERE kind IN ('native/turn/start','native/turn/steer','claude/user/send-now','claude/control/answer') ORDER BY id")|ConvertTo-Json -Compress) -cne ($before.inputOperations|ConvertTo-Json -Compress)){throw 'Native input activity changed; inspect, do not claim zero replay'}
$startup=Get-Content "$release\startup-before.json" -Raw|ConvertFrom-Json;if($startup.state -ne 'Disabled'){Enable-ScheduledTask Oracova-KhadangStartup|Out-Null}
Save "$release\live-verified.json" @{files=$receipts;routes=15;unknown=0;nativeDaemonUnchanged=$true;nativeInputsSent=0;startupRestored=$true;at=[DateTimeOffset]::UtcNow.ToString('o')}
Get-Content "$release\live-verified.json" -Raw
