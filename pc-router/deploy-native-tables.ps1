param(
 [Parameter(Mandatory=$true)][ValidateSet('prepare','fence','stage','probe','accept','typing','table','activate','verify')][string]$Phase,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$Generation,
 [ValidatePattern('^[0-9A-Fa-f]{64}$')][string]$ArchiveSha256,
 [ValidatePattern('^[0-9A-Fa-f]{64}$')][string]$CandidateSha256,
 [ValidatePattern('^[0-9A-Fa-f]{64}$')][string]$ObserverSha256,
 [ValidatePattern('^[0-9A-Fa-f]{64}$')][string]$InspectorSha256
)
# Owner-requested native Telegram tables in clean final replies. Existing participant policy
# and native authority stay unchanged; the production service is not hot-patched.
# Preserve all twelve bindings, seven Claude histories and active Linux Codex.
# Never replay a native input or claim an uncertain old display edit confirmed.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$nativeRoot='C:\ProgramData\OracovaNativeRemote'
$release="$root\release-$Generation";$package="$nativeRoot\claude-connector-$Generation"
$source="C:\Users\pou\workspaces\native-tables-$Generation"
$oldCode='C4E43DBC313C44D9C33FBBA1F8C4F5F597DA7A952C39A4C80ADD2153BA006DFE'
$oldPolicy='F353990AF7284352B30BC4FFDCC3C8B42C7197015F69545F0684968A4041CD59'
$normal='"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Exact PC administrator maintenance lane required'}
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544');$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile("$nativeRoot\migrate-lab-topics-65fc17bfcb9d47a190ab128b096bba5d.ps1",[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Protected maintenance helper did not parse'}
foreach($name in @('Protect','Save','Inspect')){
 $f=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
 if(-not $f){throw 'Protected helper function missing'};. ([ScriptBlock]::Create($f.Extent.Text))
}
# Each phase may run in a fresh PowerShell process. Load the protected read-only
# SQLite definition here rather than relying on an earlier interactive session.
$receiptTokens=$null;$receiptErrors=$null
$receiptAst=[Management.Automation.Language.Parser]::ParseFile("$nativeRoot\inspect-state.ps1",[ref]$receiptTokens,[ref]$receiptErrors)
$receiptDefinition=$receiptAst.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type' -and $n.Extent.Text -like '*class RouterReceipts*'},$true)
if($receiptErrors.Count -or -not $receiptDefinition){throw 'Protected read-only receipt definition missing'}
if(-not ('RouterReceipts' -as [type])){& ([ScriptBlock]::Create($receiptDefinition.Extent.Text))}
function Original {
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $oldCode -or (Get-FileHash "$root\config.json").Hash -ne $oldPolicy){throw 'Reviewed production changed; preserve it'}
 $s=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 if($s.StartName -ne 'LocalSystem' -or $s.PathName -ne $normal){throw 'Unexpected service identity/path'}
}
function Controller {
 $raw=@(& wsl.exe -d Ubuntu-24.04 -u pou --exec /usr/bin/python3 -I -B ('/mnt/c/ProgramData/OracovaNativeRemote/claude-connector-'+$Generation+'/pc_router_switch_observer.py'))
 if($LASTEXITCODE -ne 0){throw 'Exact controller observation failed'};return (($raw -join "`n")|ConvertFrom-Json)
}
function Quiet($s){
 if(@($s.bindings).Count -ne 12 -or $s.status.unknown){throw 'Twelve existing routes and no unknown native/send effects required'}
 foreach($row in @($s.metadata|Where-Object key -like 'bubble/*')){
  $v=$row.value;$controller=$row.key -eq 'bubble/01a0facd-1bc0-7d23-95d6-c32fde0c62db'
  if($v.held -or -not $controller -and ($v.busy -or $v.sendUnknown -or @($v.pendingResponses).Count -or @($v.pendingAnswers).Count)){throw 'Another session is busy/held; do not interrupt it'}
  if($controller){
   if($v.chat -ne -1003550185469 -or $v.topic -ne 816){throw 'Controller destination changed'}
   foreach($r in @($v)+@($v.pendingResponses)){
    if($r.sendUnknown -and $null -eq $r.message -or @($r.finalAnswer.Parts|Where-Object SendUnknown).Count){throw 'An initial send/final answer is uncertain; never replay it'}
    if($r.sendUnknown){
     $count=[RouterReceipts]::Read("SELECT COUNT(*) FROM operations WHERE kind='telegram/sendMessage' AND status='confirmed' AND json_extract(result,'$.chat.id')=-1003550185469 AND json_extract(result,'$.message_id')=$($r.message)")
     if([int]$count[0][0] -ne 1){throw 'Display edit lacks a unique confirmed original message'}
    }
   }
   if(@($v.pendingAnswers|ForEach-Object {$_.Parts}|Where-Object SendUnknown).Count){throw 'Goal final send is uncertain'}
  }
 }
}
function Stopped {
 if((Get-Service KhadangRouter).Status.ToString() -ne 'Stopped' -or (Get-ScheduledTask Oracova-KhadangStartup).State.ToString() -ne 'Disabled'){throw 'Stopped fenced router required'}
}
if($Phase -eq 'prepare'){
 Original;Quiet (Inspect)
 if((Test-Path $release) -or (Test-Path $package) -or -not $ArchiveSha256 -or -not $CandidateSha256 -or -not $ObserverSha256 -or -not $InspectorSha256){throw 'Fresh generation and reviewed hashes required'}
 foreach($pair in @(@('candidate.zip',$ArchiveSha256),@('pc_router_switch_observer.py',$ObserverSha256),@('inspect_pc_claude_topics.py',$InspectorSha256))){if((Get-FileHash (Join-Path $source $pair[0])).Hash -ne $pair[1]){throw 'Source artifact digest mismatch'}}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 Copy-Item "$source\candidate.zip" "$release\candidate.zip";Protect "$release\candidate.zip" $false
 if((Get-FileHash "$release\candidate.zip").Hash -ne $ArchiveSha256){throw 'Protected archive digest mismatch'}
 Add-Type -AssemblyName System.IO.Compression.FileSystem
 $zip=[IO.Compression.ZipFile]::OpenRead("$release\candidate.zip")
 try{$names=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase);foreach($entry in $zip.Entries){if($entry.FullName -notmatch '^publish/([A-Za-z0-9._-]+)?$' -or $entry.Length -gt 300000000 -or -not $names.Add($entry.FullName)){throw 'Unexpected archive entry'}}}finally{$zip.Dispose()}
 Expand-Archive "$release\candidate.zip" "$release\candidate"
 Get-ChildItem "$release\candidate" -Recurse -Force|ForEach-Object {Protect $_.FullName $_.PSIsContainer}
 if((Get-FileHash "$release\candidate\publish\KhadangRouter.dll").Hash -ne $CandidateSha256 -or -not (Test-Path "$release\candidate\publish\coreclr.dll")){throw 'Exact self-contained Windows build required'}
 & "$release\candidate\publish\KhadangRouter.exe" --self-test
 if($LASTEXITCODE -ne 0){throw 'Actual Windows candidate regressions failed; production untouched'}
 $p=Get-Content "$root\config.json" -Raw|ConvertFrom-Json
 if($p.OwnerId -ne 110123423 -or @($p.ParticipantIds).Count -ne 1 -or $p.ParticipantIds[0] -ne 199200674){throw 'Unexpected current owner/participant policy'}
 New-Item -ItemType Directory $package|Out-Null;Protect $package $true $true
 New-Item -ItemType Directory "$package\relay_core"|Out-Null;Protect "$package\relay_core" $true $true
 foreach($f in $p.LinuxClaude.FileSha256.PSObject.Properties){
  $from=Join-Path $p.LinuxClaude.PackageRoot $f.Name
  if((Get-FileHash $from).Hash -ne $f.Value){throw 'Accepted native connector changed'}
  $to=Join-Path $package $f.Name;Copy-Item $from $to;Protect $to $false $true
  if((Get-FileHash $to).Hash -ne $f.Value){throw 'Protected native connector copy mismatch'}
 }
 foreach($file in @('pc_router_switch_observer.py','inspect_pc_claude_topics.py')){Copy-Item "$source\$file" "$package\$file";Protect "$package\$file" $false $true}
 if((Get-FileHash "$package\pc_router_switch_observer.py").Hash -ne $ObserverSha256 -or (Get-FileHash "$package\inspect_pc_claude_topics.py").Hash -ne $InspectorSha256){throw 'Protected observer digest mismatch'}
 Save "$release\prepared.json" @{code=$CandidateSha256;archive=$ArchiveSha256;observer=$ObserverSha256;inspector=$InspectorSha256;windowsTests=$true;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='prepared-not-live';windowsTests=$true;productionChanged=$false}|ConvertTo-Json -Compress;return
}
$prepared=Get-Content "$release\prepared.json" -Raw|ConvertFrom-Json
if($Phase -eq 'fence'){
 Original;$s=Inspect;Quiet $s
 if((Get-Service KhadangRouter).Status.ToString() -ne 'Running' -or (Test-Path "$release\previous-config.json")){throw 'Unconsumed live fence required'}
 if(@($s.status.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Native stream disconnected; preserve work'}
 $before=Controller;if(@($before.activeFlags).Count){throw 'Controller has a pending request; do not reattach'}
 Save "$release\controller-before.json" $before;Save "$release\prior-bindings.json" $s.bindings
 Copy-Item "$root\config.json" "$release\previous-config.json";Copy-Item "$root\state\probe.json" "$release\previous-probe.json"
 Save "$release\previous-service.json" (Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"|Select-Object PathName,StartMode)
 [IO.File]::WriteAllText("$release\startup-before.xml",(Export-ScheduledTask Oracova-KhadangStartup),[Text.UTF8Encoding]::new($false))
 $task=Get-ScheduledTask Oracova-KhadangStartup
 if($task.Actions.Count -ne 1 -or $task.Actions[0].Arguments -ne '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\ProgramData\OracovaNativeRemote\router-startup.ps1"' -or $task.Principal.UserId -notin @('SYSTEM','NT AUTHORITY\SYSTEM','S-1-5-18')){throw 'Unexpected startup supervisor'}
 Disable-ScheduledTask Oracova-KhadangStartup|Out-Null;Stop-ScheduledTask Oracova-KhadangStartup
 try{Stop-Service KhadangRouter}catch{(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(20))}
 (Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(20))
 $after=Controller
 if($after.turn -ne $before.turn -or $after.goalStatus -ne $before.goalStatus -or @($after.activeFlags).Count){throw 'Controller changed; preserve fenced state'}
 Save "$release\controller-after.json" $after
 @{phase='fenced';service='Stopped';controllerTurnPreserved=$true;bindingsChanged=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'stage'){
 Stopped;Original;Quiet (Inspect)
 if(Test-Path "$release\stage.json"){throw 'Stage already attempted; reconcile, never replay'}
 $unknown=[RouterReceipts]::Read("SELECT (SELECT COUNT(*) FROM operations WHERE status IN ('attempting','unknown') AND kind<>'telegram/editMessageText')+(SELECT COUNT(*) FROM updates WHERE status IN ('dispatching','unknown'))")
 if([int]$unknown[0][0]){throw 'Unknown input/external effect; no change'}
 $after=Controller;$before=Get-Content "$release\controller-after.json" -Raw|ConvertFrom-Json
 if($after.turn -ne $before.turn -or @($after.activeFlags).Count){throw 'Exact controller no longer reattachable'}
 $raw=@(& wsl.exe -d Ubuntu-24.04 -u pou --exec /usr/bin/python3 -I -B ('/mnt/c/ProgramData/OracovaNativeRemote/claude-connector-'+$Generation+'/inspect_pc_claude_topics.py') --core)
 if($LASTEXITCODE -ne 0){throw 'Quiescent history inspection failed'};$histories=($raw -join "`n")|ConvertFrom-Json
 if(@($histories).Count -ne 7 -or @($histories|Where-Object {$_.uid -ne 1000 -or @($_.liveProducers).Count}).Count){throw 'Seven exact quiescent owner histories required'}
 $tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile("$nativeRoot\stage-dut-topic.ps1",[ref]$tokens,[ref]$errors)
 $f=$ast.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type' -and $n.Extent.Text -like '*class PcbaRegistry*'},$true)
 if(-not $f -or $errors.Count){throw 'Protected SQLite maintenance definition missing'};& ([ScriptBlock]::Create($f.Extent.Text))
 $exclusive=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null
 try{
  $db=[PcbaRegistry]::new();$null=$db.Read("VACUUM INTO '$release\previous-router.db'")
  $key='bubble/01a0facd-1bc0-7d23-95d6-c32fde0c62db';$r=$db.Read("SELECT value FROM meta WHERE key='$key'");if($r.Count -ne 1){throw 'Controller receipt missing'}
  $v=$r[0][0]|ConvertFrom-Json
  if($v.busy){$v|Add-Member turn $after.turn -Force;$hex=([BitConverter]::ToString([Text.Encoding]::UTF8.GetBytes(($v|ConvertTo-Json -Depth 100 -Compress)))).Replace('-','');$null=$db.Read("UPDATE meta SET value=CAST(X'$hex' AS TEXT) WHERE key='$key'")}
 }finally{if($db){$db.Dispose()};$exclusive.Dispose()}
 $p=Get-Content "$root\config.json" -Raw|ConvertFrom-Json;$checkpoints=[ordered]@{}
 foreach($h in $histories){
  $c="$package\handoff-$($h.session).json";if(Test-Path $c){throw 'Checkpoint already exists; reconcile'}
  Save $c @{schema='ccrelay.personal_claude_handoff.v1';session_id=$h.session;workspace=$h.workspace;source_writer='quiesced';uncertain_actions=@();profile='/Users/pouya/.claude';history=@{path=$h.path;bytes=$h.bytes;sha256=$h.sha256}};Protect $c $false $true
  $entry=@{Chat=$h.chat;Topic=$h.topic;Workspace=$h.workspace;Sha256=(Get-FileHash $c).Hash.ToLowerInvariant()}
  if($p.LinuxClaude.Checkpoints.($h.session).Model){$entry.Model=$p.LinuxClaude.Checkpoints.($h.session).Model};$checkpoints[$h.session]=$entry
 }
 Copy-Item "$root\bin" "$release\previous-bin" -Recurse
 $p.LinuxClaude.PackageRoot=$package;$p.LinuxClaude.Checkpoints=$checkpoints # Existing participant and owner policy preserved.
 Save "$root\config.json" $p
 Copy-Item "$release\candidate\publish\*" "$root\bin" -Force -Recurse
 Get-ChildItem "$root\bin" -Recurse -Force|ForEach-Object {Protect $_.FullName $_.PSIsContainer}
 Save "$release\stage.json" @{code=$prepared.code;policy=(Get-FileHash "$root\config.json").Hash;histories=$histories;participant=199200674;owner=110123423;ownerControlsGranted=$false;bindingsChanged=$false;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='staged-not-live';checkpoints=7;participant=199200674;ownerControlsGranted=$false;bindingsChanged=$false}|ConvertTo-Json -Compress;return
}
$staged=Get-Content "$release\stage.json" -Raw|ConvertFrom-Json
if($Phase -eq 'probe'){
 Stopped
 $s=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $probe='"'+$root+'\bin\KhadangRouter.exe" --probe-service --config "'+$root+'\config.json"'
 $r=Invoke-CimMethod -InputObject $s -MethodName Change -Arguments @{PathName=$probe;StartMode='Manual'}
 if($r.ReturnValue -ne 0 -or (Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'").PathName -cne $probe){throw 'Exact probe service path readback failed'}
 Start-Service KhadangRouter;@{phase='probe-running';modelInference=$false;telegramPolling=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'accept'){
 Stopped
 $p=Get-Content "$root\state\probe.json" -Raw|ConvertFrom-Json;$old=Get-Content "$release\previous-probe.json" -Raw|ConvertFrom-Json
 if($p.policySha256 -ne $staged.policy -or $p.routerSha256 -ne $staged.code -or -not $p.verified -or -not $p.credentialAndCodeDenied -or
  -not $p.aclProbeWithoutProviderSandbox -or -not $p.nativeWindowsSandboxVerified -or -not $p.nativeLinuxCodexVerified -or -not $p.nativeLinuxCommandOwnerVerified -or
  $p.nativeOwnerSid -ne $owner.Value -or $p.modelInference -or $p.telegramPolling -or [DateTimeOffset]$p.testedAt -le [DateTimeOffset]$staged.at -or
  $old.policySha256 -ne $oldPolicy -or $old.routerSha256 -ne $oldCode -or -not $old.nativeLinuxClaudeLaunchVerified -or -not $old.nativeLinuxClaudeToolOwnerVerified -or -not $old.nativeLinuxClaudeContinuityVerified){throw 'Fresh exact OS proof and original native acceptance required'}
 if(Test-Path "$release\generic-proof.json"){throw 'Acceptance already consumed; inspect'}
 Copy-Item "$root\state\probe.json" "$release\generic-proof.json"
 $p.nativeLinuxClaudeLaunchVerified=$true;$p.nativeLinuxClaudeToolOwnerVerified=$true;$p.nativeLinuxClaudeContinuityVerified=$true
 if($old.nativeLinuxClaudeAcceptance){$p|Add-Member nativeLinuxClaudeAcceptance $old.nativeLinuxClaudeAcceptance -Force}
 $p|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Unchanged native executable/launcher/connector; Native Telegram final tables only; native dispatch and connector unchanged';priorRouterSha256=$oldCode;currentRouterSha256=$staged.code;freshCheckpoints=7;modelsRerun=$false;liveExactSessionInitializationRequired=$true;at=[DateTimeOffset]::UtcNow.ToString('o')} -Force
 Save "$root\state\probe.json" $p;Save "$release\accepted.json" @{policy=$staged.policy;code=$staged.code;freshOsProof=$true;priorNativeChecksExplicitlyReused=$true;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='accepted-not-live';freshOsProof=$true;priorNativeChecksExplicitlyReused=$true}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'typing'){
 Stopped;$a=Get-Content "$release\accepted.json" -Raw|ConvertFrom-Json
 if((Get-FileHash "$root\config.json").Hash -ne $a.policy -or (Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $a.code){throw 'Accepted typing policy/code changed'}
 $s=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $command='"'+$root+'\bin\KhadangRouter.exe" --typing-probe-service --config "'+$root+'\config.json"'
 $r=Invoke-CimMethod -InputObject $s -MethodName Change -Arguments @{PathName=$command;StartMode='Manual'}
 if($r.ReturnValue -ne 0 -or (Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'").PathName -cne $command){throw 'Exact typing-probe service path readback failed'}
 Start-Service KhadangRouter;@{phase='typing-probe-running';modelInference=$false;telegramPolling=$false;chatMessagesSent=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'table'){
 Stopped;$a=Get-Content "$release\accepted.json" -Raw|ConvertFrom-Json
 if((Get-FileHash "$root\config.json").Hash -ne $a.policy -or (Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $a.code){throw 'Accepted table policy/code changed'}
 $s=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $command='"'+$root+'\bin\KhadangRouter.exe" --table-probe-service --config "'+$root+'\config.json"'
 $r=Invoke-CimMethod -InputObject $s -MethodName Change -Arguments @{PathName=$command;StartMode='Manual'}
 if($r.ReturnValue -ne 0 -or (Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'").PathName -cne $command){throw 'Exact table-probe service path readback failed'}
 Start-Service KhadangRouter;@{phase='table-probe-running';modelInference=$false;telegramPolling=$false;chatMessagesSent=1;automaticReplay=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'activate'){
 Stopped;$a=Get-Content "$release\accepted.json" -Raw|ConvertFrom-Json
 if((Get-FileHash "$root\config.json").Hash -ne $a.policy -or (Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $a.code){throw 'Accepted policy/code changed'}
 $typing=Get-Content "$root\state\typing-proof.json" -Raw|ConvertFrom-Json
 if(-not $typing.confirmed -or $typing.routerSha256 -ne $a.code -or $typing.policySha256 -ne $a.policy -or $typing.telegramPolling -or $typing.nativeProcessesStarted -or $typing.modelInference -or $typing.chatMessagesSent -or @($typing.targets).Count -ne 2 -or [DateTimeOffset]$typing.testedAt -le [DateTimeOffset]$staged.at){throw 'Fresh exact two-topic typing API proof required'}
 Copy-Item "$root\state\typing-proof.json" "$release\typing-proof.json"
 $table=Get-Content "$root\state\table-proof.json" -Raw|ConvertFrom-Json
 if(-not $table.confirmed -or -not $table.nativeTableReturned -or $table.chat -ne -1003550185469 -or $table.topic -ne 816 -or $table.message -le 0 -or $table.routerSha256 -ne $a.code -or $table.policySha256 -ne $a.policy -or $table.telegramPolling -or $table.nativeProcessesStarted -or $table.modelInference -or $table.chatMessagesSent -ne 1 -or [DateTimeOffset]$table.testedAt -le [DateTimeOffset]$staged.at){throw 'Fresh exact native Telegram table API proof required'}
 Copy-Item "$root\state\table-proof.json" "$release\table-proof.json"
 $before=Get-Content "$release\controller-after.json" -Raw|ConvertFrom-Json;$current=Controller
 if($current.turn -ne $before.turn -or @($current.activeFlags).Count){throw 'Exact active controller changed; no restart'}
 $s=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$saved=Get-Content "$release\previous-service.json" -Raw|ConvertFrom-Json
 $mode=if($saved.StartMode -eq 'Auto'){'Automatic'}else{'Manual'}
 $r=Invoke-CimMethod -InputObject $s -MethodName Change -Arguments @{PathName=$normal;StartMode=$mode}
 if($r.ReturnValue -ne 0 -or (Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'").PathName -cne $normal){throw 'Exact live service path readback failed'}
 Start-Service KhadangRouter;@{phase='activation-started';participant=199200674;ownerControlsGranted=$false}|ConvertTo-Json -Compress;return
}
$s=Inspect;$p=Get-Content "$root\config.json" -Raw|ConvertFrom-Json
$accepted=Get-Content "$release\accepted.json" -Raw|ConvertFrom-Json
if($s.service -ne 'Running' -or @($s.bindings).Count -ne 12 -or $s.status.unknown -or @($s.status.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count -or
 @($s.status.nativeSessions).Count -ne 12 -or [DateTimeOffset]$s.status.at -le [DateTimeOffset]$accepted.at -or $s.status.nativeLinuxPid -ne 2141 -or
 $p.OwnerId -ne 110123423 -or @($p.ParticipantIds).Count -ne 1 -or $p.ParticipantIds[0] -ne 199200674){throw 'Live exact routing/participant acceptance not yet proven; inspect, never blind restart'}
$before=Get-Content "$release\prior-bindings.json" -Raw -Encoding UTF8|ConvertFrom-Json
if((($before|Sort-Object Chat,Topic|ConvertTo-Json -Depth 20 -Compress) -cne ($s.bindings|Sort-Object Chat,Topic|ConvertTo-Json -Depth 20 -Compress))){throw 'A native topic binding changed'}
Enable-ScheduledTask Oracova-KhadangStartup|Out-Null
Save "$release\live-verified.json" @{phase='live-verified';routes=12;connectedClaudeStreams=7;participant=199200674;owner=110123423;ownerControlsGranted=$false;bindingsChanged=$false;unknown=$s.status.unknown;presentationUnknown=$s.status.presentationUnknown;nativeLinuxPid=$s.status.nativeLinuxPid;nativeWindowsPid=$s.status.nativePid;startupRestored=$true;receiptTyping=$s.status.receiptTyping;typingApiVerified=$true;claudeStreamTerminalView=$true;nativeRichTables=$true;tableApiVerified=$true;at=[DateTimeOffset]::UtcNow.ToString('o')}
Get-Content "$release\live-verified.json" -Raw
