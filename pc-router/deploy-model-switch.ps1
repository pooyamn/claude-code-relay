param([Parameter(Mandatory=$true)][ValidateSet('prepare','stage','accept')][string]$Phase,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$Generation,
 [ValidatePattern('^[0-9A-Fa-f]{64}$')][string]$ArchiveSha256,
 [ValidatePattern('^[0-9A-Fa-f]{64}$')][string]$CandidateSha256,
 [ValidatePattern('^[0-9A-Fa-f]{64}$')][string]$BridgeSha256,
 [ValidatePattern('^[0-9A-Fa-f]{64}$')][string]$ObserverSha256)
# Fixed personal UI/tool-switch deployment. Keeps the shared controller alive,
# preserves every binding, backs up all preimages, never replays native input.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote'
$nativeRoot=$native # Name used by the reviewed inspection function.
$release="$root\release-$Generation";$package="$native\claude-connector-$Generation"
$source="C:\Users\pou\workspaces\model-switch-$Generation"
$oldCode='3FD09C88CA54F0716310C3649FBC7A48907362B0487AF80DE1E4599B3AE755C1'
$oldPolicy='1204A440086705CC0B94988371CEBEFDAF392E18354A12C407458358B9E0D8DA'
$normal='"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator lane required'}
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544');$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile("$native\migrate-lab-topics-65fc17bfcb9d47a190ab128b096bba5d.ps1",[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Accepted helper parse failed'}
foreach($name in @('Protect','Save','Inspect')){
 $definition=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
 if(-not $definition){throw 'Accepted helper function missing'};. ([ScriptBlock]::Create($definition.Extent.Text))
}
function Original {
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $oldCode -or (Get-FileHash "$root\config.json").Hash -ne $oldPolicy){throw 'Accepted production changed; do not replace'}
 $s=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 if($s.StartName -ne 'LocalSystem' -or $s.PathName -ne $normal){throw 'Unexpected SCM identity/path'}
}
function Controller {
 $path='/mnt/c/ProgramData/OracovaNativeRemote/claude-connector-'+$Generation+'/pc_router_switch_observer.py'
 $raw=@(& wsl.exe -d Ubuntu-24.04 -u pou --exec /usr/bin/python3 -I -B $path)
 if($LASTEXITCODE -ne 0){throw 'Read-only native observation failed'};return (($raw -join "`n")|ConvertFrom-Json)
}
function Quiet($state){
 if(@($state.bindings).Count -ne 10 -or $state.status.unknown){throw 'Unexpected routes or unknown effects'}
 foreach($row in @($state.metadata|Where-Object key -like 'bubble/*')){
  if($row.value.held -or $row.value.sendUnknown -or @($row.value.pendingResponses).Count -or
   $row.value.busy -and $row.key -ne 'bubble/01a0facd-1bc0-7d23-95d6-c32fde0c62db'){throw 'Another task/unknown receipt is active; preserve it'}
 }
}
if($Phase -eq 'prepare'){
 Original;Quiet (Inspect)
 if((Test-Path $release) -or (Test-Path $package) -or -not $ArchiveSha256 -or -not $CandidateSha256 -or -not $BridgeSha256 -or -not $ObserverSha256){throw 'Fresh generation and reviewed hashes required'}
 foreach($pair in @(@('candidate.zip',$ArchiveSha256),@('pc_claude_stdio.py',$BridgeSha256),@('pc_router_switch_observer.py',$ObserverSha256))){if((Get-FileHash (Join-Path $source $pair[0])).Hash -ne $pair[1]){throw 'Reviewed source digest mismatch'}}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 Copy-Item "$source\candidate.zip" "$release\candidate.zip";Protect "$release\candidate.zip" $false
 if((Get-FileHash "$release\candidate.zip").Hash -ne $ArchiveSha256){throw 'Sealed archive differs from reviewed artifact'}
 Add-Type -AssemblyName System.IO.Compression.FileSystem
 $zip=[IO.Compression.ZipFile]::OpenRead("$release\candidate.zip")
 try{
  $names=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
  foreach($entry in $zip.Entries){if($entry.FullName -notmatch '^(publish|probe)/([A-Za-z0-9._-]+)?$' -or $entry.Length -gt 300000000 -or -not $names.Add($entry.FullName)){throw 'Unexpected archive entry'}}
 }finally{$zip.Dispose()}
 Expand-Archive "$release\candidate.zip" "$release\candidate"
 Get-ChildItem "$release\candidate" -Recurse -Force|ForEach-Object {Protect $_.FullName $_.PSIsContainer}
 if((Get-FileHash "$release\candidate\publish\KhadangRouter.dll").Hash -ne $CandidateSha256 -or (Get-FileHash "$release\candidate\probe\KhadangRouter.dll").Hash -ne $CandidateSha256){throw 'Candidate/probe assemblies differ'}
 & "$release\candidate\publish\KhadangRouter.exe" --self-test
 if($LASTEXITCODE -ne 0){throw 'Windows candidate tests failed; production unchanged'}
 $policy=Get-Content "$root\config.json" -Raw|ConvertFrom-Json
 New-Item -ItemType Directory $package|Out-Null;Protect $package $true $true
 New-Item -ItemType Directory "$package\relay_core"|Out-Null;Protect "$package\relay_core" $true $true
 foreach($file in $policy.LinuxClaude.FileSha256.PSObject.Properties){
  $from=Join-Path $policy.LinuxClaude.PackageRoot $file.Name
  if((Get-FileHash $from).Hash -ne $file.Value){throw 'Accepted connector changed'}
  if($file.Name -eq 'pc_claude_stdio.py'){$from="$source\pc_claude_stdio.py"}
  $to=Join-Path $package $file.Name;Copy-Item $from $to;Protect $to $false $true
 }
 Copy-Item "$source\pc_router_switch_observer.py" "$package\pc_router_switch_observer.py";Protect "$package\pc_router_switch_observer.py" $false $true
 if((Get-FileHash "$package\pc_claude_stdio.py").Hash -ne $BridgeSha256 -or (Get-FileHash "$package\pc_router_switch_observer.py").Hash -ne $ObserverSha256){throw 'Sealed helper digest mismatch'}
 Save "$release\prepared.json" @{code=$CandidateSha256;bridge=$BridgeSha256;observer=$ObserverSha256;windowsTests=$true;at=[DateTimeOffset]::UtcNow.ToString('o')}
 New-Item -ItemType Directory "$release\handoff-proof"|Out-Null;Protect "$release\handoff-proof" $true
 Save "$release\handoff-proof\bindings.json" (Inspect).bindings
 $policy.OwnerFullAccess=$false;$policy.LinuxClaude.PackageRoot=$package;$policy.LinuxClaude.FileSha256.'pc_claude_stdio.py'=$BridgeSha256.ToLowerInvariant()
 Save "$release\handoff-proof\candidate.json" $policy
 [ordered]@{phase='prepared-not-live';windowsTests=$true;productionUnchanged=$true}|ConvertTo-Json -Compress;exit
}
$prepared=Get-Content "$release\prepared.json" -Raw|ConvertFrom-Json
if($Phase -eq 'stage'){
 Original;Quiet (Inspect)
 if(Test-Path "$release\previous-config.json"){throw 'Stage already attempted; inspect, do not repeat'}
 $proof=Get-Content "$release\handoff-proof\result.json" -Raw|ConvertFrom-Json
 if(-not $proof.complete -or $proof.routingChanged -or $proof.routerSha256 -ne $prepared.code -or $proof.modelPromptsAttempted -ne 2 -or
  -not $proof.nativeLinuxClaudeToolOwnerVerified -or -not $proof.nativeLinuxClaudeContinuityVerified){throw 'Actual candidate-bound handoff/owner/continuity acceptance required'}
 $before=Controller
 if(@($before.activeFlags).Count){throw 'Native request pending; no active reattachment'}
 Save "$release\controller-before.json" $before
 Copy-Item "$root\config.json" "$release\previous-config.json";Copy-Item "$root\state\probe.json" "$release\previous-probe.json"
 [IO.File]::WriteAllText("$release\startup-before.xml",(Export-ScheduledTask Oracova-KhadangStartup),[Text.UTF8Encoding]::new($false))
 Save "$release\prior-bindings.json" (Inspect).bindings
 Disable-ScheduledTask Oracova-KhadangStartup|Out-Null;Stop-ScheduledTask Oracova-KhadangStartup
 try{Stop-Service KhadangRouter}catch{(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(20))}
 (Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(20))
 $after=Controller
 if($after.turn -ne $before.turn -or @($after.activeFlags).Count){throw 'Exact native turn changed; no held state cleared'}
 Save "$release\controller-after.json" $after
 $tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile("$native\stage-dut-topic.ps1",[ref]$tokens,[ref]$errors)
 $definition=$ast.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type' -and $n.Extent.Text -like '*class PcbaRegistry*'},$true)
 if(-not $definition -or $errors.Count){throw 'Accepted SQLite source missing'};& ([ScriptBlock]::Create($definition.Extent.Text))
 $exclusive=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null
 try{
  $db=[PcbaRegistry]::new()
  $unknown=$db.Read("SELECT (SELECT COUNT(*) FROM operations WHERE status IN ('attempting','unknown'))+(SELECT COUNT(*) FROM updates WHERE status IN ('received','dispatching','unknown'))")
  if([int]$unknown[0][0]){throw 'Input/effect not reconciled; no deployment'}
  $null=$db.Read("VACUUM INTO '$release\previous-router.db'")
  $key='bubble/01a0facd-1bc0-7d23-95d6-c32fde0c62db';$rows=$db.Read("SELECT value FROM meta WHERE key='$key'")
  if($rows.Count -ne 1){throw 'Exact controller receipt missing'}
  $receipt=$rows[0][0]|ConvertFrom-Json
  if($receipt.held -or $receipt.sendUnknown -or $receipt.chat -ne -1003550185469 -or $receipt.topic -ne 816){throw 'Controller receipt not safely reattachable'}
  if($receipt.busy){
   $receipt|Add-Member turn $after.turn -Force
   $hex=([BitConverter]::ToString([Text.Encoding]::UTF8.GetBytes(($receipt|ConvertTo-Json -Depth 100 -Compress)))).Replace('-','')
   $null=$db.Read("UPDATE meta SET value=CAST(X'$hex' AS TEXT) WHERE key='$key'")
  }
 }finally{if($db){$db.Dispose()};$exclusive.Dispose()}
 $inspector='/mnt/c/ProgramData/OracovaNativeRemote/inspect-lab-topics-65fc17bfcb9d47a190ab128b096bba5d.py'
 $raw=@(& wsl.exe -d Ubuntu-24.04 -u pou --exec /usr/bin/python3 -I -B $inspector --additional)
 if($LASTEXITCODE -ne 0){throw 'Quiesced history observation failed'};$histories=($raw -join "`n")|ConvertFrom-Json
 if(@($histories).Count -ne 5 -or @($histories|Where-Object {@($_.liveProducers).Count}).Count){throw 'Five exact quiesced histories required'}
 $policy=Get-Content "$root\config.json" -Raw|ConvertFrom-Json;$checkpoints=[ordered]@{}
 foreach($h in $histories){
  $p="$package\handoff-$($h.session).json"
  if(Test-Path $p){throw 'Production checkpoint already exists; no blind reuse'}
  Save $p @{schema='ccrelay.personal_claude_handoff.v1';session_id=$h.session;workspace=$h.workspace;source_writer='quiesced';uncertain_actions=@();profile='/Users/pouya/.claude';history=@{path=$h.path;bytes=$h.bytes;sha256=$h.sha256}};Protect $p $false $true
  $checkpoints[$h.session]=@{Chat=$h.chat;Topic=$h.topic;Workspace=$h.workspace;Sha256=(Get-FileHash $p).Hash.ToLowerInvariant()}
 }
 Copy-Item "$root\bin" "$release\previous-bin" -Recurse
 $policy.LinuxClaude.PackageRoot=$package;$policy.LinuxClaude.Checkpoints=$checkpoints;$policy.LinuxClaude.FileSha256.'pc_claude_stdio.py'=$prepared.bridge.ToLowerInvariant()
 Save "$root\config.json" $policy
 Copy-Item "$release\candidate\publish\*" "$root\bin" -Force -Recurse
 Get-ChildItem "$root\bin" -Recurse -Force|ForEach-Object {Protect $_.FullName $_.PSIsContainer}
 Save "$release\stage.json" @{code=$prepared.code;policy=(Get-FileHash "$root\config.json").Hash;at=[DateTimeOffset]::UtcNow.ToString('o')}
 [ordered]@{phase='staged-not-live';bindings=10;checkpoints=5;sharedDaemonRestarted=$false}|ConvertTo-Json -Compress;exit
}
if((Get-Service KhadangRouter).Status.ToString() -ne 'Stopped' -or (Get-ScheduledTask Oracova-KhadangStartup).State.ToString() -ne 'Disabled'){throw 'Stopped fenced router required'}
$stage=Get-Content "$release\stage.json" -Raw|ConvertFrom-Json
$proof=Get-Content "$root\state\probe.json" -Raw|ConvertFrom-Json
$handoff=Get-Content "$release\handoff-proof\result.json" -Raw|ConvertFrom-Json
if(-not $proof.verified -or -not $proof.credentialAndCodeDenied -or -not $proof.aclProbeWithoutProviderSandbox -or -not $proof.nativeWindowsSandboxVerified -or
 -not $proof.nativeLinuxCodexVerified -or -not $proof.nativeLinuxCommandOwnerVerified -or $proof.modelInference -or $proof.telegramPolling -or
 $proof.routerSha256 -ne $stage.code -or $proof.policySha256 -ne $stage.policy -or [DateTimeOffset]$proof.testedAt -le [DateTimeOffset]$stage.at -or
 -not $handoff.complete -or $handoff.routerSha256 -ne $stage.code -or $handoff.routingChanged){throw 'Fresh exact OS and native acceptance required'}
Copy-Item "$root\state\probe.json" "$release\generic-proof.json"
$proof.nativeLinuxClaudeLaunchVerified=$true;$proof.nativeLinuxClaudeToolOwnerVerified=$true;$proof.nativeLinuxClaudeContinuityVerified=$true
$proof|Add-Member nativeLinuxClaudeModelSwitchAcceptance @{resultSha256=(Get-FileHash "$release\handoff-proof\result.json").Hash;source="$release\handoff-proof\result.json";exactSameSessionResumed=$true;bindingChanged=$false;acceptedAt=[DateTimeOffset]::UtcNow.ToString('o')} -Force
Save "$root\state\probe.json" $proof
[ordered]@{phase='accepted-not-live';freshOsProof=$true;actualNativeHandoff=$true}|ConvertTo-Json -Compress
