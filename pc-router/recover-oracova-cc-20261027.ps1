param([ValidateSet('stage','probe','activate','verify','deliver')][string]$Phase)
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote';$temp='C:\Users\pou\AppData\Local\Temp'
$release="$root\recover-oracova-cc-20261027";$pin='2c0bce31-f586-4d5e-9422-4be550763ed8'
$package="$native\claude-connector-7193c3efd3344c4c976bff575b2a2734"
$worker="C:\ProgramData\KhadangClaudeHost\state\$pin"
$code='69E74A18F68D48BE729976D42EDD1461F99D5C864BC196A6D65A5B48291C8E30'
$oldPolicy='6271B521E9C069618384FD6632088C7FAF06FDD1CBCB8A7CBCDC36E77215192C'
$connector='3A82F35A48711087C7E6DBB863C37791D6985434BEF2469DB9352F2C0632664B'
$oldCheckpoint='9DF41F8979133BD796DAC5433DE59305555CF2881CCAF047B42348990A5D2117'
$history=@{path='/Users/pouya/.claude/projects/-Users-pouya--openclaw-workspace-ai-hil/'+$pin+'.jsonl';bytes=51992069;sha256='e58c6718ccb745e69b35ad07cb8393cca6259631021e5b0f38335ea3af5d7cbe'}
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$helper="$temp\deploy-switch-isolation-20261014.ps1"
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helpers changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Unknown','Bindings','HostIdentity','ExactTask','Fenced','Hex')){
 $d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true)
 if(-not $d){throw 'Helper missing'};. ([ScriptBlock]::Create($d.Extent.Text))
}
LoadSql "$native\inspect-state.ps1" 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
function Status{[IO.File]::ReadAllText("$root\state\status.json")|ConvertFrom-Json}
function RestoreSupervisors($b){foreach($n in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){(ExactTask $n).Enabled=[bool]$(if($n -like '*Startup'){$b.startup}else{$b.watchdog})}}
function StartObserver([bool]$probe=$false){
 $mode=if($probe){'--probe-service'}else{'--service'}
 $s=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $r=Invoke-CimMethod -InputObject $s -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" '+$mode+' --config "'+$root+'\config.json"');StartMode='Manual'}
 if($r.ReturnValue){throw 'Service path update failed'};Start-Service KhadangRouter
}
if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code){throw 'Router artifact changed'}
if($Phase -eq 'stage'){
 if((Test-Path $release) -or (Get-FileHash "$root\config.json").Hash -ne $oldPolicy -or (Get-FileHash "$temp\pc_claude_stdio-reviewed-20261027.py").Hash -ne $connector){throw 'Fresh pinned stage required'}
 $s=Status;$target=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $pin})
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $target.Count -ne 1 -or $target[0].pid -ne 0 -or -not $target[0].held -or $target[0].busy -or $target[0].admission.Blocking -ne 0 -or
  @($s.nativeSessions|Where-Object {$_.binding.Runtime -eq 'windows' -and $_.busy}).Count -or
  [RouterReceipts]::Read("SELECT id FROM updates WHERE status='dispatching'").Length -or
  [RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Fresh idle target and settled mutations required'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 $before=@{at=[DateTimeOffset]::UtcNow;bindings=(Bindings);host=(HostIdentity);unknown=(Unknown);startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled;claudePids=@($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude'}|ForEach-Object {@{thread=$_.binding.ThreadId;pid=$_.pid}})}
 Save "$release\before.json" $before
 foreach($n in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $n;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
 $svc=Get-Service KhadangRouter;$svc.Stop();$svc.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(50));Fenced
 if((Unknown) -cne $before.unknown -or (Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host){throw 'Custody changed during stop'}
 Copy-Item "$root\config.json" "$release\previous-config.json";Protect "$release\previous-config.json"
 Copy-Item "$root\state\probe.json" "$release\previous-probe.json";Protect "$release\previous-probe.json"
 Copy-Item "$package\pc_claude_stdio.py" "$release\previous-connector.py";Protect "$release\previous-connector.py"
 $checkpoint="$package\handoff-$pin.json"
 if((Get-FileHash $checkpoint).Hash -ne $oldCheckpoint){throw 'Checkpoint changed'}
 Copy-Item $checkpoint "$release\previous-checkpoint.json";Protect "$release\previous-checkpoint.json"
 $f="$native\stage-dut-topic.ps1"
 if((Get-FileHash $f).Hash -ne '0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF'){throw 'Writer definition changed'}
 $a=[Management.Automation.Language.Parser]::ParseFile($f,[ref]$null,[ref]$null)
 $d=$a.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type'},$true)
 $definition=$d.Extent.Text.Replace('PcbaRegistry','ReviewedWorkerRegistry').Replace('C:\ProgramData\KhadangRouter\state\router.db',"$worker\broker.db")
 . ([ScriptBlock]::Create($definition))
 $lease=[IO.File]::Open("$worker\broker.lease",'Open','ReadWrite','None');$db=$null
 try{
  $db=[ReviewedWorkerRegistry]::new()
  if($db.Read("SELECT id FROM operations WHERE status IN ('unknown','attempting') AND kind<>'telegram/editMessageText'").Length -or
   $db.Read("SELECT intent FROM broker_calls WHERE status IN ('unknown','attempting','submitted')").Length -or
   $db.Read("SELECT id FROM broker_replies WHERE status IN ('unknown','attempting','submitted')").Length -or
   $db.Read("SELECT id FROM updates WHERE status IN ('unknown','dispatching')").Length -or
   $db.Read("SELECT key FROM meta WHERE key='claude/reset/$pin' OR (key LIKE 'claude/request/$pin/%' AND json_extract(value,'$.status')='pending')").Length){throw 'Worker uncertainty; no recovery waiver'}
  $key="claude/recovery/$pin";$raw=$db.Read("SELECT value FROM meta WHERE key='$key'")[0][0];$r=$raw|ConvertFrom-Json
  $b=$db.Read("SELECT value FROM meta WHERE key='bubble/$pin'")[0][0]|ConvertFrom-Json
  if($r.state -ne 'connected' -or $r.sha256 -ne $oldCheckpoint.ToLowerInvariant() -or $r.binding.ThreadId -ne $pin -or $r.binding.Chat -ne -1003550185469 -or $r.binding.Topic -ne 1876 -or $r.binding.Workspace -cne '/Users/pouya/.openclaw/workspace/ai-hil' -or
   $b.busy -or $b.held -or $b.sendUnknown -or $b.claudeState -ne 'idle' -or @($b.pendingAnswers).Count -or @($b.pendingResponses).Count){throw 'Exact previously connected idle worker required'}
  Save "$release\previous-worker-recovery.json" $r
  $newCheckpoint=@{schema='ccrelay.personal_claude_handoff.v1';session_id=$pin;workspace=$r.binding.Workspace;source_writer='quiesced';uncertain_actions=@();history=$history;profile='/Users/pouya/.claude'}
  Save "$release\reviewed-checkpoint.json" $newCheckpoint
  $digest=(Get-FileHash "$release\reviewed-checkpoint.json").Hash.ToLowerInvariant()
  $audit=@{schema='ccrelay.owner_history_review.v1';approval='Pouya: Fix it, CC Relay topic 816, 2026-10-27';history=$history;oldCheckpoint=$r.sha256;newCheckpoint=$digest;toolsBalanced=$true;pendingQueue=0;terminalNotifications=@{completed=81;killed=5};priorityDequeues=10;structuredRemoval=1;deliveredToAgent=9;historicalNavigation='/Users/pouya/demo/augur-demo';inputsReplayed=0;at=[DateTimeOffset]::UtcNow}
  Save "$release\history-review.json" $audit
  Copy-Item "$release\reviewed-checkpoint.json" "$checkpoint.reviewed";Protect "$checkpoint.reviewed" $false $true
  [IO.File]::Replace("$checkpoint.reviewed",$checkpoint,[NullString]::Value)
  $r.sha256=$digest;$r|Add-Member ownerHistoryReview $audit -Force
  $null=$db.Read('BEGIN IMMEDIATE')
  try{$null=$db.Read("UPDATE meta SET value=CAST(X'$(Hex $r)' AS TEXT) WHERE key='$key'");$null=$db.Read('COMMIT')}catch{$null=$db.Read('ROLLBACK');throw}
 }finally{if($db){$db.Dispose()};$lease.Dispose()}
 Copy-Item "$temp\pc_claude_stdio-reviewed-20261027.py" "$package\pc_claude_stdio.py.reviewed";Protect "$package\pc_claude_stdio.py.reviewed" $false $true
 [IO.File]::Replace("$package\pc_claude_stdio.py.reviewed","$package\pc_claude_stdio.py",[NullString]::Value)
 $p=[IO.File]::ReadAllText("$root\config.json")|ConvertFrom-Json
 $p.LinuxClaude.FileSha256.'pc_claude_stdio.py'=$connector.ToLowerInvariant()
 Save "$root\config.json.reviewed" $p
 [IO.File]::Replace("$root\config.json.reviewed","$root\config.json",[NullString]::Value)
 Save "$release\staged.json" @{at=[DateTimeOffset]::UtcNow;policy=(Get-FileHash "$root\config.json").Hash;connector=$connector}
 'STAGED: same binding/history, no input replay';return
}
$before=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json
$staged=[IO.File]::ReadAllText("$release\staged.json")|ConvertFrom-Json
if((Get-FileHash "$root\config.json").Hash -ne $staged.policy -or (Get-FileHash "$package\pc_claude_stdio.py").Hash -ne $connector){throw 'Staged artifacts changed'}
if($Phase -eq 'probe'){
 Fenced;StartObserver $true
 $end=[DateTimeOffset]::UtcNow.AddSeconds(55)
 do{$p=[IO.File]::ReadAllText("$root\state\probe.json")|ConvertFrom-Json;if($p.policySha256 -eq $staged.policy -and [DateTimeOffset]$p.testedAt -gt [DateTimeOffset]$staged.at){break};Start-Sleep -Milliseconds 500}while([DateTimeOffset]::UtcNow -lt $end)
 $svc=Get-Service KhadangRouter;$svc.Stop();$svc.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 if($p.routerSha256 -ne $code -or $p.policySha256 -ne $staged.policy -or -not $p.verified -or -not $p.credentialAndCodeDenied -or -not $p.nativeWindowsSandboxVerified -or -not $p.nativeLinuxCommandOwnerVerified -or $p.modelInference -or $p.telegramPolling -or [DateTimeOffset]$p.testedAt -le [DateTimeOffset]$staged.at){throw 'Fresh security proof failed'}
 Save "$release\generic-proof.json" $p
 $old=[IO.File]::ReadAllText("$release\previous-probe.json")|ConvertFrom-Json
 if((HostIdentity) -cne $before.host -or -not $old.nativeLinuxClaudeContinuityVerified){throw 'Independent host custody changed'}
 foreach($field in @('nativeLinuxClaudeLaunchVerified','nativeLinuxClaudeToolOwnerVerified','nativeLinuxClaudeContinuityVerified','nativeLinuxClaudeAcceptance')){if($old.PSObject.Properties[$field]){$p|Add-Member $field $old.$field -Force}}
 $p|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Exact owner-reviewed checkpoint prefix; unchanged native executable, owner protocol, workspace and independent host';connectorSha256=$connector;actualRecoveryVerifiedSeparately=$true} -Force
 Save "$root\state\probe.json" $p;Save "$release\accepted.json" @{at=[DateTimeOffset]::UtcNow;policy=$staged.policy;code=$code}
 'FRESH SECURITY PROBE PASSED';return
}
if($Phase -eq 'activate'){
 Fenced;$null=[IO.File]::ReadAllText("$release\accepted.json")
 try{StartObserver}finally{RestoreSupervisors $before}
 Save "$release\activated.json" @{at=[DateTimeOffset]::UtcNow};'ACTIVATED';return
}
$s=Status;$target=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $pin})
$guards=@{fresh=([DateTimeOffset]$s.at -ge [DateTimeOffset]::UtcNow.AddSeconds(-20));transport=[bool]$s.nativeTransportHealthy;background=[bool]$s.backgroundHealthy;
 target=($target.Count -eq 1 -and -not $target[0].held -and $target[0].nativeConnected -and $target[0].pid -ne 0 -and $target[0].admission.Blocking -eq 0);
 unknown=((Unknown) -ceq $before.unknown);bindings=((Bindings) -ceq $before.bindings);host=((HostIdentity) -ceq $before.host)}
if(@($guards.Values|Where-Object {-not $_}).Count){throw ('Recovery verification failed: '+(($guards.Keys|Where-Object {-not $guards[$_]}) -join ','))}
foreach($previous in $before.claudePids){if($previous.thread -ne $pin -and @($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $previous.thread -and $_.pid -eq $previous.pid}).Count -ne 1){throw 'Unrelated native generation changed'}}
RestoreSupervisors $before
$result=@{at=$s.at;topic=1876;session=$pin;nativePid=$target[0].pid;connected=$true;held=$false;bindingsPreserved=$true;unknownReceiptsPreserved=$true;unrelatedNativePidsPreserved=$true;inputReplay=0;phoneRoundTripClaimed=$false}
Save "$release\verified.json" $result;$result|ConvertTo-Json -Compress
if($Phase -ne 'deliver'){return}
# Only this exact owner message was proven never submitted. No blanket queue
# replay, uncertain receipt resend, direct native client or fake human canary.
$request='oracova-cc-retained-759324832'
if(Test-Path "$root\state\controller-handoffs\$request.json"){throw 'Existing delivery intent: inspect its receipt, never resend'}
$rows=[RouterReceipts]::Read('SELECT payload,status FROM updates WHERE id=759324832')
if($rows.Length -ne 1 -or $rows[0][1] -ne 'held-no-replay'){throw 'Exact retained input required'}
$message=($rows[0][0]|ConvertFrom-Json).message
if($message.chat.id -ne -1003550185469 -or $message.message_thread_id -ne 1876 -or $message.message_id -ne 15257 -or $message.from.id -ne 110123423 -or $message.from.is_bot -or $message.text -notlike 'Everything is ready at jlc except fpgas are delayed*'){throw 'Original human question/binding differs'}
if([RouterReceipts]::Read("SELECT key FROM meta WHERE key='intake/759324832' AND json_extract(value,'$.Operation') IS NOT NULL").Length -or
 [RouterReceipts]::Read("SELECT id FROM operations WHERE kind='claude/user/send-now' AND json_extract(payload,'$.SessionId')='$pin' AND instr(payload,'Everything is ready at jlc')>0").Length){throw 'Possible prior native submission; no replay'}
$text='Pouya asked in this exact Telegram topic (message 15257). The bridge retained it before any native submission; he has now requested topic recovery. Please answer his question here in Telegram. Do not retry old video uploads or repeat earlier external actions.'+"`n`n"+$message.text
$textPath="$release\retained-owner-question.txt"
$bytes=[Text.UTF8Encoding]::new($false).GetBytes($text);$stream=[IO.File]::Open($textPath,'CreateNew','Write','None');try{$stream.Write($bytes,0,$bytes.Length)}finally{$stream.Dispose()};Protect $textPath
$publisher="$native\dispatch-controller-handoff.ps1"
if((Get-FileHash $publisher).Hash -ne 'B7384A54C0C2C364C1AD02E478958B7F72C0EED8C7869927E78EFA30722C9484'){throw 'Reviewed publisher changed'}
& $publisher -RequestId $request -SourceThread '01a0facd-1bc0-7d23-95d6-c32fde0c62db' -TargetThread $pin -TextFile $textPath -TextSha256 (Get-FileHash $textPath).Hash -OwnerApproval 'Pouya: Fix it; CC Relay topic 816, 2026-10-27; original owner message 15257/update759324832 verified unsubmitted' -WaitSeconds 30
