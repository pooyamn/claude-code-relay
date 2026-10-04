param([Parameter(Mandatory=$true)][ValidateSet('prepare','fence','stage','accept')][string]$Phase,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$Generation,
 [ValidateSet('labs','additional','core')][string]$Batch='labs')
# Fixed personal batches; reuse retained handoffs, never perform project work.
# No router binary, credentials, subscription profile or shared daemon changes.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$root='C:\ProgramData\KhadangRouter';$nativeRoot='C:\ProgramData\OracovaNativeRemote'
$package=Join-Path $nativeRoot ('claude-connector-'+$Generation)
$release=Join-Path $root ('release-'+$Generation)
$beforePolicy=switch($Batch){'core'{'E99D0BE6F9EDFA8B31D25AC2A672AA29BA3140CFAEF2D6A6B19C660D0FF2BA63'}'additional'{'FD0C4A5D7C44F9F7BC8FC542F083A533062C7153C9C9E043AC8021C1F7C4C76F'}default{'507DB6D32B51692EEB304C12566977E7A29EB6AC53ED0B2927546F472916C95D'}}
$priorCount=switch($Batch){'core'{10}'additional'{7}default{5}}
$claudeCount=switch($Batch){'core'{7}'additional'{5}default{3}}
$code=if($Batch -eq 'core'){'C22B67C902C7303DFFFB28684CC5CD9183410065FEF909D4C965BE13C3DA31CF'}else{'94111E96E68F5D935FAA3DF94085E81F06AC3867E28A75DF290A744048D55841'}
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator migration lane required'}
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544');$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
function Protect([string]$Path,[bool]$Directory,[bool]$Readable=$false){
 if((Get-Item $Path).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Literal artifact required'}
 if($Directory){$acl=[Security.AccessControl.DirectorySecurity]::new();$inherit=[Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'}
 else{$acl=[Security.AccessControl.FileSecurity]::new();$inherit=[Security.AccessControl.InheritanceFlags]::None}
 $acl.SetOwner($admin);$acl.SetAccessRuleProtection($true,$false)
 foreach($sid in @($admin,$system)){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl',$inherit,'None','Allow'))}
 if($Readable){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($owner,'ReadAndExecute',$inherit,'None','Allow'))};Set-Acl $Path $acl
}
function Save([string]$Path,$Value){[IO.File]::WriteAllText($Path,($Value|ConvertTo-Json -Depth 100),[Text.UTF8Encoding]::new($false))}
function Inspect {
 $raw=(& 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$nativeRoot\inspect-state.ps1") -join "`n"
 if($LASTEXITCODE -ne 0){throw 'Read-only router inspection failed'};return ($raw|ConvertFrom-Json)
}
function Idle($State,[int]$Count){
 if(@($State.bindings).Count -ne $Count -or $State.status.unknown -ne 0){throw 'Unexpected registry or uncertain effects'}
 foreach($row in @($State.metadata|Where-Object key -like 'bubble/*')){
  if($row.value.held -or $row.value.sendUnknown -or @($row.value.pendingResponses).Count -or
   $row.value.busy -and -not ($Batch -eq 'core' -and $row.key -eq 'bubble/01a0facd-1bc0-7d23-95d6-c32fde0c62db')){throw 'Native work active or unreconciled; no interruption'}
 }
}
function Controller {
 $path='/mnt/c/ProgramData/OracovaNativeRemote/claude-connector-0bc81f90bf4e4494a07d2d36b979271e/pc_router_switch_observer.py'
 if((Get-FileHash 'C:\ProgramData\OracovaNativeRemote\claude-connector-0bc81f90bf4e4494a07d2d36b979271e\pc_router_switch_observer.py').Hash -ne '1DFAC3D8AF2C710AB673BBBDF16CDF74EACC5B5487D172E02F78189A9366C33C'){throw 'Reviewed read-only controller observer changed'}
 $raw=@(& wsl.exe -d Ubuntu-24.04 -u pou --exec /usr/bin/python3 -I -B $path)
 if($LASTEXITCODE -ne 0){throw 'Exact native controller observation failed'}
 $value=($raw -join "`n")|ConvertFrom-Json
 if(@($value.activeFlags).Count){throw 'Pending native request; no active reattachment'}
 return $value
}
if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code){throw 'Accepted router code changed'}
$policy=Get-Content "$root\config.json" -Raw -Encoding UTF8|ConvertFrom-Json
$targets=@(
 [ordered]@{Chat=-1004395661179;Topic=2697;Name='Schematic Pipeline - PC';Workspace='/Users/pouya/.openclaw/workspace/schematic-pipeline-lab';ThreadId='6159472a-7878-42e4-b497-ffbb64a7e2d6';Backend='claude';Runtime='linux'},
 [ordered]@{Chat=-1004395661179;Topic=3315;Name='Mimic Fast PCB - PC';Workspace='/Users/pouya/.openclaw/workspace/mimic-fast-pcb';ThreadId='10ab0d8a-f31c-49ca-ab99-1a6152ae4ee2';Backend='claude';Runtime='linux'})
if($Batch -eq 'additional'){
 $targets=@(
  [ordered]@{Chat=-1003550185469;Topic=6333;Name='Hardware Lite - PC';Workspace='/Users/pouya/.openclaw/workspace/hardware-lite';ThreadId='5fc53034-e240-43b5-a2c4-75ee1947aefa';Backend='claude';Runtime='linux'},
  [ordered]@{Chat=-1003550185469;Topic=8653;Name='MPU6000 i9 - PC';Workspace='/Users/pouya/.openclaw/workspace/ai-hil/demos/fpga/mpu6000-i9';ThreadId='a32bd2ef-172a-4a51-95ba-1b9bce4f44eb';Backend='claude';Runtime='linux'})
}
if($Batch -eq 'core'){
 $targets=@(
  [ordered]@{Chat=-1003550185469;Topic=1876;Name='ai-hil outreach - PC';Workspace='/Users/pouya/.openclaw/workspace/ai-hil';ThreadId='2c0bce31-f586-4d5e-9422-4be550763ed8';Backend='claude';Runtime='linux'},
  [ordered]@{Chat=-1003550185469;Topic=5786;Name='Supervisor firmware review - PC';Workspace='/Users/pouya/.openclaw/workspace/ai-hil/.worktrees/supervisor-fw';ThreadId='dcf9169b-c044-4c39-9ba5-e27d2978722c';Backend='claude';Runtime='linux'})
}
if($Phase -eq 'prepare'){
 if((Get-Service KhadangRouter).Status.ToString() -ne 'Running' -or (Get-FileHash "$root\config.json").Hash -ne $beforePolicy -or (Test-Path $package)){throw 'Unchanged live production and fresh generation required'}
 $observed=Inspect;Idle $observed $priorCount
 New-Item -ItemType Directory $package|Out-Null;Protect $package $true $true
 New-Item -ItemType Directory "$package\relay_core"|Out-Null;Protect "$package\relay_core" $true $true
 foreach($file in $policy.LinuxClaude.FileSha256.PSObject.Properties){
  $source=Join-Path $policy.LinuxClaude.PackageRoot $file.Name
  if((Get-FileHash $source).Hash -ne $file.Value){throw 'Accepted native connector changed'}
  $destination=Join-Path $package $file.Name;Copy-Item -LiteralPath $source -Destination $destination;Protect $destination $false $true
 }
 $reports=@()
 foreach($target in $targets){foreach($mode in @('fresh','continuity')){
  $linux='/Users/pouya/.migration/topic-native-'+$target.ThreadId+'/'+$mode+'/result.json'
  $raw=@(& wsl.exe -d Ubuntu-24.04 -u pou --exec /bin/cat $linux)
  if($LASTEXITCODE -ne 0){throw 'Native acceptance result missing'};$report=($raw -join "`n")|ConvertFrom-Json
  if(-not $report.complete -or $report.uncertain -or -not $report.nativeStopped -or $report.nativeExitCode -ne 0 -or
   -not $report.nativeIdleAfterResult -or $report.session -ne $target.ThreadId -or $report.workspace -ne $target.Workspace -or
   $report.nativeUid -ne 1000 -or $report.modelPromptsAttempted -ne 1 -or $report.chat -ne $target.Chat -or $report.topic -ne $target.Topic -or
   ($mode -eq 'fresh' -and -not $report.toolOwnerVerified) -or ($mode -eq 'continuity' -and -not $report.continuityVerified)){throw 'Exact actual native handoff/tool/continuity evidence required'}
  $reports+=@($report)
 }}
 Save "$package\new-topic-acceptance.json" $reports;Protect "$package\new-topic-acceptance.json" $false
 [ordered]@{phase='prepared-not-live';generation=$Generation;nativeChecks=4;codeChanged=$false;routingChanged=$false}|ConvertTo-Json -Compress;exit
}
if($Phase -eq 'fence'){
 if((Get-FileHash "$root\config.json").Hash -ne $beforePolicy -or (Get-Service KhadangRouter).Status.ToString() -ne 'Running' -or
  (Test-Path $release) -or -not (Test-Path "$package\new-topic-acceptance.json")){throw 'Prepared candidate and unchanged production required'}
 $state=Inspect;Idle $state $priorCount
 if($Batch -eq 'core'){
  $fence=Get-Content "$package\source-fence.json" -Raw -Encoding UTF8|ConvertFrom-Json
  if($fence.phase -cne 'source-core-topics-fenced' -or ($fence.topics -join ',') -ne '1876,5786' -or
   $fence.remainingBindings -ne 3 -or $fence.sourceSessionsStopped -ne 4 -or $fence.sharedDaemonRestarted -or $fence.gatewayRestarted){throw 'Exact retained Mac source fence required'}
  $controller=Controller
 }
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 Copy-Item "$root\config.json" "$release\previous-config.json";Copy-Item "$root\state\probe.json" "$release\previous-probe.json"
 Save "$release\prior-bindings.json" $state.bindings
 if($Batch -eq 'core'){Save "$release\controller-before.json" $controller}
 [IO.File]::WriteAllText("$release\startup-before.xml",(Export-ScheduledTask Oracova-KhadangStartup),[Text.UTF8Encoding]::new($false))
 Disable-ScheduledTask Oracova-KhadangStartup|Out-Null;Stop-ScheduledTask Oracova-KhadangStartup
 try{Stop-Service KhadangRouter}catch{(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(20))}
 (Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(20))
 if($Batch -eq 'core'){
  $after=Controller
  if($after.turn -ne $controller.turn -or $after.goalStatus -ne $controller.goalStatus -or $after.turnStatus -ne $controller.turnStatus){throw 'Exact native controller boundary changed; preserve held state'}
  Save "$release\controller-after.json" $after
 }
 [ordered]@{phase='fenced-not-staged';recoveryDirectory=$release;service='Stopped'}|ConvertTo-Json -Compress;exit
}
if((Get-Service KhadangRouter).Status.ToString() -ne 'Stopped' -or (Get-ScheduledTask Oracova-KhadangStartup).State.ToString() -ne 'Disabled' -or
 -not (Test-Path "$release\previous-config.json")){throw 'Fenced stopped service and retained preimages required'}
if($Phase -eq 'stage'){
 if((Get-FileHash "$root\config.json").Hash -ne $beforePolicy -or (Test-Path "$release\stage.json")){throw 'Unchanged original policy and unconsumed staging required'}
 $state=Inspect;Idle $state $priorCount
 $inspection=@('/mnt/c/ProgramData/OracovaNativeRemote/inspect-lab-topics-'+$Generation+'.py')
 if($Batch -eq 'additional'){$inspection+=@('--additional')}
 if($Batch -eq 'core'){$inspection+=@('--core')}
 $raw=@(& wsl.exe -d Ubuntu-24.04 -u pou --exec /usr/bin/python3 -I -B @inspection)
 if($LASTEXITCODE -ne 0){throw 'Final native history inspection failed'};$histories=($raw -join "`n")|ConvertFrom-Json
 if(@($histories).Count -ne $claudeCount -or @($histories|Where-Object {@($_.liveProducers).Count -ne 0}).Count){throw 'Exact selected stopped native histories required'}
 $checkpoints=[ordered]@{}
 foreach($history in $histories){
  $id=$history.session;$checkpoint=Join-Path $package ('handoff-'+$id+'.json')
  if(Test-Path $checkpoint){throw 'Checkpoint already exists; no staging replay'}
  Save $checkpoint @{schema='ccrelay.personal_claude_handoff.v1';session_id=$id;workspace=$history.workspace;source_writer='quiesced';uncertain_actions=@();profile='/Users/pouya/.claude';history=@{path=$history.path;bytes=$history.bytes;sha256=$history.sha256}}
  Protect $checkpoint $false $true
  $checkpoints[$id]=@{Chat=$history.chat;Topic=$history.topic;Workspace=$history.workspace;Sha256=(Get-FileHash $checkpoint).Hash.ToLowerInvariant()}
 }
 $policy.LinuxClaude.PackageRoot=$package;$policy.LinuxClaude.Checkpoints=$checkpoints
 # Reuse the accepted fixed SQLite migration definition without executing its old body.
 $tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile("$nativeRoot\stage-dut-topic.ps1",[ref]$tokens,[ref]$errors)
 if($errors.Count){throw 'Accepted SQLite migration source failed parsing'}
 $definition=$ast.Find({param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type'},$true)
 if(-not $definition -or $definition.Extent.Text -notlike '*class PcbaRegistry*'){throw 'Fixed accepted SQLite definition missing'}
 & ([ScriptBlock]::Create($definition.Extent.Text))
 $exclusive=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null;$transaction=$false;$policyWritten=$false
 try{
  $db=[PcbaRegistry]::new();$unknown=$db.Read("SELECT (SELECT COUNT(*) FROM operations WHERE status IN ('attempting','unknown'))+(SELECT COUNT(*) FROM updates WHERE status IN ('received','dispatching','unknown'))")
  if([int]$unknown[0][0]){throw 'Unreconciled input or action; no migration'}
  $prior=$db.Read('SELECT payload FROM bindings ORDER BY chat,topic');if($prior.Length -ne $priorCount){throw 'Exact prior routes required'}
  $old=@($prior|ForEach-Object {$_[0]|ConvertFrom-Json})
  $expected=@('01a10114-cbad-7a80-ae57-b9af8f8478c7','01a104a6-9fce-74a3-bdb0-e6dc04237ce7','01a104cc-9a63-7901-8897-abf8aff3dfb3','01a104cc-d892-7c52-ba1e-e505edfb13d6','7dc840b0-402f-451e-bc79-dadfb706d363')
  if($Batch -in @('additional','core')){$expected+=@('6159472a-7878-42e4-b497-ffbb64a7e2d6','10ab0d8a-f31c-49ca-ab99-1a6152ae4ee2')}
  if($Batch -eq 'core'){$expected+=@('5fc53034-e240-43b5-a2c4-75ee1947aefa','a32bd2ef-172a-4a51-95ba-1b9bce4f44eb','01a0facd-1bc0-7d23-95d6-c32fde0c62db')}
  if((@($old.ThreadId|Sort-Object)-join ',') -ne (@($expected|Sort-Object)-join ',')){throw 'Existing native identities changed'}
  $null=$db.Read("VACUUM INTO '"+"$release\previous-router.db"+"'")
  if($Batch -eq 'core'){
   $after=Controller;$before=Get-Content "$release\controller-after.json" -Raw|ConvertFrom-Json
   if($after.turn -ne $before.turn -or $after.goalStatus -ne $before.goalStatus -or $after.turnStatus -ne $before.turnStatus){throw 'Exact controller changed during staging'}
   $key='bubble/01a0facd-1bc0-7d23-95d6-c32fde0c62db';$rows=$db.Read("SELECT value FROM meta WHERE key='$key'")
   if($rows.Count -ne 1){throw 'Exact controller receipt missing'};$receipt=$rows[0][0]|ConvertFrom-Json
   if($receipt.held -or $receipt.sendUnknown -or $receipt.chat -ne -1003550185469 -or $receipt.topic -ne 816){throw 'Controller receipt cannot be safely reattached'}
   if($receipt.busy){
    $receipt|Add-Member turn $after.turn -Force
    $hex=([BitConverter]::ToString([Text.Encoding]::UTF8.GetBytes(($receipt|ConvertTo-Json -Depth 100 -Compress)))).Replace('-','')
    $null=$db.Read("UPDATE meta SET value=CAST(X'$hex' AS TEXT) WHERE key='$key'")
   }
  }
  $digest=$db.UnrelatedDigest()
  $null=$db.Read('BEGIN IMMEDIATE');$transaction=$true
  foreach($target in $targets){$json=$target|ConvertTo-Json -Compress;$hex=([BitConverter]::ToString([Text.Encoding]::UTF8.GetBytes($json))).Replace('-','')
   $null=$db.Read("INSERT INTO bindings(chat,topic,payload) VALUES("+$target.Chat+","+$target.Topic+",CAST(X'"+$hex+"' AS TEXT))")}
  if($db.UnrelatedDigest() -ne $digest){throw 'Unrelated ledger changed'}
  Save "$root\config.json" $policy;$policyWritten=$true
  $null=$db.Read('COMMIT');$transaction=$false
  Save "$release\stage.json" @{phase='staged-not-live';generation=$Generation;bindings=$targets;policySha256=(Get-FileHash "$root\config.json").Hash;routerSha256=$code;unrelatedLedgerSha256=$digest;histories=$histories;at=[DateTimeOffset]::UtcNow.ToString('o')}
 }catch{
  if($transaction){$null=$db.Read('ROLLBACK');if($policyWritten){Copy-Item "$release\previous-config.json" "$root\config.json"}}
  throw
 }finally{if($db){$db.Dispose()};$exclusive.Dispose()}
 Get-Content "$release\stage.json" -Raw;exit
}
$staged=Get-Content "$release\stage.json" -Raw -Encoding UTF8|ConvertFrom-Json
$proof=Get-Content "$root\state\probe.json" -Raw -Encoding UTF8|ConvertFrom-Json
$priorProof=Get-Content "$release\previous-probe.json" -Raw -Encoding UTF8|ConvertFrom-Json
if(-not $proof.verified -or $proof.policySha256 -ne $staged.policySha256 -or $proof.routerSha256 -ne $code -or
 -not $proof.credentialAndCodeDenied -or -not $proof.nativeLinuxCodexVerified -or -not $proof.nativeLinuxCommandOwnerVerified -or
 -not $proof.nativeWindowsSandboxVerified -or $proof.modelInference -or $proof.telegramPolling -or
 [DateTimeOffset]$proof.testedAt -le [DateTimeOffset]$staged.at -or -not $priorProof.nativeLinuxClaudeLaunchVerified -or
 -not $priorProof.nativeLinuxClaudeToolOwnerVerified -or -not $priorProof.nativeLinuxClaudeContinuityVerified){throw 'Fresh exact OS proof and accepted unchanged Claude core required'}
if(Test-Path "$release\generic-proof-before-native.json"){throw 'Acceptance already attempted; reconcile instead of replay'}
Copy-Item "$root\state\probe.json" "$release\generic-proof-before-native.json"
$proof.nativeLinuxClaudeLaunchVerified=$true;$proof.nativeLinuxClaudeToolOwnerVerified=$true;$proof.nativeLinuxClaudeContinuityVerified=$true
$proof|Add-Member nativeLinuxClaudeAcceptance $priorProof.nativeLinuxClaudeAcceptance -Force
if($Batch -eq 'core'){
 if(-not $priorProof.nativeLinuxClaudeModelSwitchAcceptance.exactSameSessionResumed -or
  $priorProof.nativeLinuxClaudeModelSwitchAcceptance.bindingChanged){throw 'Current connector native continuity acceptance required'}
 $proof|Add-Member nativeLinuxClaudeModelSwitchAcceptance $priorProof.nativeLinuxClaudeModelSwitchAcceptance -Force
}
$proof|Add-Member nativeLinuxClaudeNewTopicAcceptance (Get-Content "$package\new-topic-acceptance.json" -Raw -Encoding UTF8|ConvertFrom-Json) -Force
$proof|Add-Member nativeLinuxClaudeAcceptanceReuse @{unchangedRouterSha256=$code;unchangedConnectorFiles=$policy.LinuxClaude.FileSha256;
 bootstrapUsedLimitedWindowsOwner=$true;bootstrapHooksAndMcpDisabled=$true;liveProductionInitializationRequired=$true;scope='Personal migration, not company-role isolation'} -Force
Save "$root\state\probe.json" $proof
[ordered]@{phase='accepted-not-live';policy=$staged.policySha256;code=$code;newTopics=@($targets.Topic)}|ConvertTo-Json -Compress
