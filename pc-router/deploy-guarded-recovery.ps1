param(
 [Parameter(Mandatory=$true)][ValidateSet('prepare','stage','probe','accept','activate','verify')][string]$Phase,
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{32}$')][string]$Generation,
 [ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$ArchiveSha256,
 [ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$CandidateSha256,
 [ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$ConnectorSha256
)
# Owner approved guarded recovery only. No session replacement, replay,
# native-host restart, participant promotion or source credential retirement.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote'
$nativeRoot=$native # Required by the pinned Inspect helper's lexical contract.
$release="$root\release-$Generation";$package="$native\claude-connector-$Generation"
$incoming="C:\Users\pou\workspaces\guarded-recovery-$Generation"
$oldCode='FFAEC6699B17BD59C47BC40DC83D4364F6A0B9EE18101B40DAF0A45152F8D94C'
$oldPolicy='33F8BE3BF0E538B03FCB20AC612310CEA3877E0387C3663D67635BBF55C1E522'
$normal='"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Exact PC administrator maintenance required'}
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544');$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
foreach($entry in @(@("$native\migrate-lab-topics-65fc17bfcb9d47a190ab128b096bba5d.ps1",'86F3D550CBA51D280CE2D6BCDCBD7A3C3B1B1CBB7435FE9BC54590C0F87E6513'),@("$native\inspect-state.ps1",'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2'))){if((Get-FileHash $entry[0]).Hash -ne $entry[1]){throw 'Protected maintenance helper changed'}}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile("$native\migrate-lab-topics-65fc17bfcb9d47a190ab128b096bba5d.ps1",[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Maintenance helper parse error'}
foreach($name in @('Protect','Save','Inspect')){
 $f=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
 if(-not $f){throw 'Maintenance helper missing'};. ([ScriptBlock]::Create($f.Extent.Text))
}
function Stopped { if((Get-Service KhadangRouter).Status.ToString() -ne 'Stopped' -or (Get-ScheduledTask Oracova-KhadangStartup).State.ToString() -ne 'Disabled'){throw 'Stopped fenced router required'} }
function Original {
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $oldCode -or (Get-FileHash "$root\config.json").Hash -ne $oldPolicy){throw 'Production changed; preserve it'}
 $s=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 if($s.StartName -ne 'LocalSystem' -or $s.PathName -cne $normal -or $s.State -ne 'Stopped'){throw 'Expected already-stopped protected service required'}
}
function Scope($p,$s){
 if($p.OwnerId -ne 110123423 -or @($p.ParticipantIds).Count -ne 1 -or $p.ParticipantIds[0] -ne 199200674 -or @($s.bindings).Count -ne 12 -or $s.status.unknown){throw 'Exact owner, normal participant, twelve bindings and no unknown effects required'}
}
if($Phase -eq 'prepare'){
 Original;$s=Inspect;$p=Get-Content "$root\config.json" -Raw|ConvertFrom-Json;Scope $p $s
 if((Test-Path $release) -or (Test-Path $package) -or -not $ArchiveSha256 -or -not $CandidateSha256 -or -not $ConnectorSha256){throw 'Fresh reviewed artifacts required'}
 if((Get-FileHash "$incoming\candidate.zip").Hash -ne $ArchiveSha256 -or (Get-FileHash "$incoming\pc_claude_stdio.py").Hash -ne $ConnectorSha256){throw 'Incoming digest mismatch'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 Copy-Item "$incoming\candidate.zip" "$release\candidate.zip";Protect "$release\candidate.zip" $false
 Add-Type -AssemblyName System.IO.Compression.FileSystem
 $zip=[IO.Compression.ZipFile]::OpenRead("$release\candidate.zip")
 try{$names=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase);foreach($e in $zip.Entries){if($e.FullName -notmatch '^publish/[A-Za-z0-9._-]+$' -or $e.Length -gt 300000000 -or -not $names.Add($e.FullName)){throw 'Unexpected release entry'}}}finally{$zip.Dispose()}
 Expand-Archive "$release\candidate.zip" "$release\candidate";Get-ChildItem "$release\candidate" -Recurse -Force|ForEach-Object{Protect $_.FullName $_.PSIsContainer}
 if((Get-FileHash "$release\candidate\publish\KhadangRouter.dll").Hash -ne $CandidateSha256 -or -not (Test-Path "$release\candidate\publish\coreclr.dll")){throw 'Exact self-contained Windows candidate required'}
 & "$release\candidate\publish\KhadangRouter.exe" --self-test
 if($LASTEXITCODE -ne 0){throw 'Windows candidate tests failed; production untouched'}
 New-Item -ItemType Directory $package|Out-Null;Protect $package $true $true
 New-Item -ItemType Directory "$package\relay_core"|Out-Null;Protect "$package\relay_core" $true $true
 foreach($f in $p.LinuxClaude.FileSha256.PSObject.Properties){
  $from=Join-Path $p.LinuxClaude.PackageRoot $f.Name;if((Get-FileHash $from).Hash -ne $f.Value){throw 'Accepted connector changed'}
  $to=Join-Path $package $f.Name;Copy-Item $from $to;Protect $to $false $true
 }
 Copy-Item "$incoming\pc_claude_stdio.py" "$package\pc_claude_stdio.py" -Force;Protect "$package\pc_claude_stdio.py" $false $true
 if((Get-FileHash "$package\pc_claude_stdio.py").Hash -ne $ConnectorSha256){throw 'Protected connector mismatch'}
 foreach($c in $p.LinuxClaude.Checkpoints.PSObject.Properties){
  $name='handoff-'+$c.Name+'.json';$from=Join-Path $p.LinuxClaude.PackageRoot $name
  if((Get-FileHash $from).Hash -ne $c.Value.Sha256){throw 'Original checkpoint changed'}
  Copy-Item $from (Join-Path $package $name);Protect (Join-Path $package $name) $false $true
 }
 Save "$release\prepared.json" @{code=$CandidateSha256;archive=$ArchiveSha256;connector=$ConnectorSha256;windowsTests=$true;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='prepared';productionChanged=$false;windowsTests=$true}|ConvertTo-Json -Compress;return
}
$prepared=Get-Content "$release\prepared.json" -Raw|ConvertFrom-Json
if($Phase -eq 'stage'){
 Original;$s=Inspect;$p=Get-Content "$root\config.json" -Raw|ConvertFrom-Json;Scope $p $s
 if(Test-Path "$release\stage.json"){throw 'Stage already attempted; reconcile'}
 $task=Get-ScheduledTask Oracova-KhadangStartup
 if($task.Actions.Count -ne 1 -or $task.Actions[0].Arguments -cne '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\ProgramData\OracovaNativeRemote\router-startup.ps1"' -or $task.Principal.UserId -notin @('SYSTEM','NT AUTHORITY\SYSTEM','S-1-5-18')){throw 'Unexpected startup supervisor'}
 [IO.File]::WriteAllText("$release\startup-before.xml",(Export-ScheduledTask Oracova-KhadangStartup),[Text.UTF8Encoding]::new($false))
 Disable-ScheduledTask Oracova-KhadangStartup|Out-Null;Stop-ScheduledTask Oracova-KhadangStartup;Stopped
 Copy-Item "$root\config.json" "$release\previous-config.json";Copy-Item "$root\state\probe.json" "$release\previous-probe.json"
 Save "$release\prior-bindings.json" $s.bindings
 $exclusive=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None')
 try{
  Copy-Item "$root\state\router.db" "$release\previous-router.db";Protect "$release\previous-router.db" $false
  foreach($suffix in @('-wal','-shm')){if(Test-Path "$root\state\router.db$suffix"){Copy-Item "$root\state\router.db$suffix" "$release\previous-router.db$suffix";Protect "$release\previous-router.db$suffix" $false}}
  Copy-Item "$root\bin" "$release\previous-bin" -Recurse
  $p.LinuxClaude.PackageRoot=$package;$p.LinuxClaude.FileSha256.'pc_claude_stdio.py'=$prepared.connector.ToLowerInvariant()
  $p.LinuxClaude|Add-Member GuardedRecovery $true -Force
  Save "$root\config.json" $p
  Copy-Item "$release\candidate\publish\*" "$root\bin" -Force -Recurse;Get-ChildItem "$root\bin" -Recurse -Force|ForEach-Object{Protect $_.FullName $_.PSIsContainer}
 }finally{$exclusive.Dispose()}
 Save "$release\stage.json" @{code=$prepared.code;policy=(Get-FileHash "$root\config.json").Hash;guardedRecovery=$true;bindingsChanged=$false;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='staged';bindingsChanged=$false;nativeHostsRestarted=$false}|ConvertTo-Json -Compress;return
}
$staged=Get-Content "$release\stage.json" -Raw|ConvertFrom-Json
if($Phase -eq 'probe'){
 Stopped;$s=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $command='"'+$root+'\bin\KhadangRouter.exe" --probe-service --config "'+$root+'\config.json"'
 $r=Invoke-CimMethod -InputObject $s -MethodName Change -Arguments @{PathName=$command;StartMode='Manual'}
 if($r.ReturnValue -ne 0){throw 'Probe service path failed'}
 Start-Service KhadangRouter;@{phase='probe-running';modelInference=$false;telegramPolling=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'accept'){
 Stopped;$p=Get-Content "$root\state\probe.json" -Raw|ConvertFrom-Json;$old=Get-Content "$release\previous-probe.json" -Raw|ConvertFrom-Json
 if($p.policySha256 -ne $staged.policy -or $p.routerSha256 -ne $staged.code -or -not $p.verified -or -not $p.credentialAndCodeDenied -or -not $p.aclProbeWithoutProviderSandbox -or
  -not $p.nativeWindowsSandboxVerified -or -not $p.nativeLinuxCodexVerified -or -not $p.nativeLinuxCommandOwnerVerified -or $p.nativeOwnerSid -ne $owner.Value -or
  $p.modelInference -or $p.telegramPolling -or [DateTimeOffset]$p.testedAt -le [DateTimeOffset]$staged.at -or $old.policySha256 -ne $oldPolicy -or $old.routerSha256 -ne $oldCode -or
  -not $old.nativeLinuxClaudeLaunchVerified -or -not $old.nativeLinuxClaudeToolOwnerVerified -or -not $old.nativeLinuxClaudeContinuityVerified){throw 'Fresh OS proof and prior native acceptance required'}
 Copy-Item "$root\state\probe.json" "$release\generic-proof.json"
 # These prior checks cover the unchanged native executable, launch/input path
 # and saved conversations, NOT new recovery. Actual recovery is verified live.
 $p.nativeLinuxClaudeLaunchVerified=$true;$p.nativeLinuxClaudeToolOwnerVerified=$true;$p.nativeLinuxClaudeContinuityVerified=$true
 $p|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Owner-approved guarded snapshot renewal; native binary, launch/input path and saved IDs unchanged; recovery must pass fresh live attestation';priorRouterSha256=$oldCode;connectorSha256=$prepared.connector;modelsRerun=$false;at=[DateTimeOffset]::UtcNow.ToString('o')} -Force
 Save "$root\state\probe.json" $p;Save "$release\accepted.json" @{code=$staged.code;policy=$staged.policy;freshOsProof=$true;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='accepted-not-live';freshOsProof=$true;modelInference=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'activate'){
 Stopped;$accepted=Get-Content "$release\accepted.json" -Raw|ConvertFrom-Json
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $accepted.code -or (Get-FileHash "$root\config.json").Hash -ne $accepted.policy){throw 'Accepted code/policy changed'}
 $s=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $s -MethodName Change -Arguments @{PathName=$normal;StartMode='Manual'}
 if($r.ReturnValue -ne 0){throw 'Live service path failed'}
 Start-Service KhadangRouter;@{phase='activation-started';sessionIdsChanged=$false}|ConvertTo-Json -Compress;return
}
$s=Inspect;$p=Get-Content "$root\config.json" -Raw|ConvertFrom-Json;Scope $p $s
$before=Get-Content "$release\prior-bindings.json" -Raw|ConvertFrom-Json
if($s.service -ne 'Running' -or @($s.status.nativeSessions).Count -ne 12 -or @($s.status.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count -or
 (($before|Sort-Object Chat,Topic|ConvertTo-Json -Depth 20 -Compress) -cne ($s.bindings|Sort-Object Chat,Topic|ConvertTo-Json -Depth 20 -Compress))){throw 'Live exact sessions not yet verified; inspect without replay'}
$recoveries=@($s.metadata|Where-Object key -like 'claude/recovery/*')
if($recoveries.Count -ne 7 -or @($recoveries|Where-Object {$_.value.state -ne 'connected'}).Count){throw 'Seven actual guarded recovery receipts required'}
$claudeBubbles=@($s.metadata|Where-Object {$_.key -like 'bubble/*' -and $_.value.backend -eq 'claude'})
if($claudeBubbles.Count -ne 7 -or @($claudeBubbles|Where-Object {$_.value.held -or $_.value.busy -or $_.value.claudeState -ne 'idle'}).Count){throw 'Seven recovered idle Claude topics required; preserve other held topics'}
Enable-ScheduledTask Oracova-KhadangStartup|Out-Null
Save "$release\live-verified.json" @{routes=12;connectedClaudeStreams=7;guardedRecovery=$true;unknown=$s.status.unknown;presentationUnknown=$s.status.presentationUnknown;bindingsChanged=$false;startupRestored=$true;nativeHostsRestarted=$false;phoneRoundTripVerified=$false;at=[DateTimeOffset]::UtcNow.ToString('o')}
Get-Content "$release\live-verified.json" -Raw
