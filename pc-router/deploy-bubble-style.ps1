param([Parameter(Mandatory=$true)][ValidateSet('prepare','fence','stage','accept')][string]$Phase,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$Generation,
 [ValidatePattern('^[0-9A-Fa-f]{64}$')][string]$ArchiveSha256,
 [ValidatePattern('^[0-9A-Fa-f]{64}$')][string]$CandidateSha256)
# Reviewed formatting-only deployment of the existing nine personal routes.
# No topic/identity/credential changes, model prompts, daemon restart or fallback.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$root='C:\ProgramData\KhadangRouter';$nativeRoot='C:\ProgramData\OracovaNativeRemote'
$release=Join-Path $root ('release-'+$Generation)
$package=Join-Path $nativeRoot ('claude-connector-'+$Generation)
$oldCode='94111E96E68F5D935FAA3DF94085E81F06AC3867E28A75DF290A744048D55841'
$oldPolicy='B61DC1C276815DCF964094721337DAA794CC3C6FDA0E19C01A68E27AF2DBD663'
$normal='"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator deployment lane required'}
# Reuse only the reviewed ACL/inspection functions, never the migration body.
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile("$nativeRoot\migrate-lab-topics-65fc17bfcb9d47a190ab128b096bba5d.ps1",[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Accepted helper failed parsing'}
foreach($name in @('Protect','Save','Inspect','Idle')){
 $definition=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
 if(-not $definition){throw 'Accepted helper definition missing'}
 . ([ScriptBlock]::Create($definition.Extent.Text))
}
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544');$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
function Original {
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $oldCode -or (Get-FileHash "$root\config.json").Hash -ne $oldPolicy){throw 'Accepted production changed; no replacement'}
 $service=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 if($service.StartName -ne 'LocalSystem' -or $service.PathName -ne $normal){throw 'Unexpected SCM identity/path'}
}
if($Phase -eq 'prepare'){
 Original
 if(-not $ArchiveSha256 -or -not $CandidateSha256 -or (Test-Path $release) -or (Test-Path $package) -or (Get-Service KhadangRouter).Status.ToString() -ne 'Running'){throw 'Fresh release and reviewed artifact hashes required'}
 $state=Inspect;Idle $state 9
 $archive='C:\Users\pou\workspaces\bubble-style-'+$Generation+'\publish-live.zip'
 if((Get-FileHash $archive).Hash -ne $ArchiveSha256){throw 'Source artifact digest mismatch'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 Copy-Item $archive "$release\publish-live.zip";Protect "$release\publish-live.zip" $false
 if((Get-FileHash "$release\publish-live.zip").Hash -ne $ArchiveSha256){throw 'Protected artifact digest mismatch'}
 Expand-Archive "$release\publish-live.zip" "$release\candidate"
 $candidate="$release\candidate\publish-live"
 if((Get-FileHash "$candidate\KhadangRouter.dll").Hash -ne $CandidateSha256 -or -not (Test-Path "$candidate\coreclr.dll")){throw 'Expected self-contained Windows candidate required'}
 Get-ChildItem "$release\candidate" -Recurse -Force|ForEach-Object {Protect $_.FullName $_.PSIsContainer}
 & "$candidate\KhadangRouter.exe" --self-test
 if($LASTEXITCODE -ne 0){throw 'Windows candidate tests failed; production untouched'}
 $policy=Get-Content "$root\config.json" -Raw -Encoding UTF8|ConvertFrom-Json
 New-Item -ItemType Directory $package|Out-Null;Protect $package $true $true
 New-Item -ItemType Directory "$package\relay_core"|Out-Null;Protect "$package\relay_core" $true $true
 foreach($file in $policy.LinuxClaude.FileSha256.PSObject.Properties){
  $source=Join-Path $policy.LinuxClaude.PackageRoot $file.Name
  if((Get-FileHash $source).Hash -ne $file.Value){throw 'Accepted native connector changed'}
  $destination=Join-Path $package $file.Name;Copy-Item $source $destination;Protect $destination $false $true
  if((Get-FileHash $destination).Hash -ne $file.Value){throw 'Protected connector copy mismatch'}
 }
 Save "$release\prepared.json" @{generation=$Generation;code=$CandidateSha256;archive=$ArchiveSha256;windowsSelfTests=$true;at=[DateTimeOffset]::UtcNow.ToString('o')}
 [ordered]@{phase='prepared-not-live';windowsSelfTests=$true;productionUntouched=$true}|ConvertTo-Json -Compress;exit
}
$prepared=Get-Content "$release\prepared.json" -Raw -Encoding UTF8|ConvertFrom-Json
if($Phase -eq 'fence'){
 Original
 if((Get-Service KhadangRouter).Status.ToString() -ne 'Running' -or (Test-Path "$release\previous-config.json")){throw 'Unchanged live production and unconsumed fence required'}
 $state=Inspect;Idle $state 9
 if(@($state.status.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Native stream disconnected; do not interrupt'}
 Save "$release\prior-bindings.json" $state.bindings
 Copy-Item "$root\config.json" "$release\previous-config.json";Copy-Item "$root\state\probe.json" "$release\previous-probe.json"
 [IO.File]::WriteAllText("$release\startup-before.xml",(Export-ScheduledTask Oracova-KhadangStartup),[Text.UTF8Encoding]::new($false))
 $task=Get-ScheduledTask Oracova-KhadangStartup
 if($task.Actions.Count -ne 1 -or $task.Actions[0].Arguments -ne '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\ProgramData\OracovaNativeRemote\router-startup.ps1"' -or $task.Principal.UserId -notin @('SYSTEM','NT AUTHORITY\SYSTEM','S-1-5-18')){throw 'Unexpected startup supervisor'}
 Disable-ScheduledTask Oracova-KhadangStartup|Out-Null;Stop-ScheduledTask Oracova-KhadangStartup
 try{Stop-Service KhadangRouter}catch{if((Get-Service KhadangRouter).Status.ToString() -ne 'Stopped'){throw}}
 (Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(20))
 [ordered]@{phase='fenced';service='Stopped';allNineBindingsPreserved=$true}|ConvertTo-Json -Compress;exit
}
if((Get-Service KhadangRouter).Status.ToString() -ne 'Stopped' -or (Get-ScheduledTask Oracova-KhadangStartup).State.ToString() -ne 'Disabled'){throw 'Stopped fenced service required'}
if($Phase -eq 'stage'){
 Original
 if(Test-Path "$release\stage.json"){throw 'Staging already consumed; no replay'}
 $state=Inspect;Idle $state 9
 $inspector='/mnt/c/ProgramData/OracovaNativeRemote/inspect-lab-topics-65fc17bfcb9d47a190ab128b096bba5d.py'
 $raw=@(& wsl.exe -d Ubuntu-24.04 -u pou --exec /usr/bin/python3 -I -B $inspector --additional)
 if($LASTEXITCODE -ne 0){throw 'Stopped native history inspection failed'};$histories=($raw -join "`n")|ConvertFrom-Json
 if(@($histories).Count -ne 5 -or @($histories|Where-Object {@($_.liveProducers).Count}).Count){throw 'Five exact quiesced native histories required'}
 $policy=Get-Content "$root\config.json" -Raw -Encoding UTF8|ConvertFrom-Json;$checkpoints=[ordered]@{}
 foreach($history in $histories){
  $checkpoint=Join-Path $package ('handoff-'+$history.session+'.json')
  if(Test-Path $checkpoint){
   # Resume only an inert partial stage: original code/policy, stopped service,
   # no stage receipt and the exact same still-quiesced native history.
   $saved=Get-Content $checkpoint -Raw -Encoding UTF8|ConvertFrom-Json
   if(@($saved.PSObject.Properties).Count -ne 7 -or @($saved.history.PSObject.Properties).Count -ne 3 -or
    $saved.schema -cne 'ccrelay.personal_claude_handoff.v1' -or $saved.session_id -cne $history.session -or
    $saved.workspace -cne $history.workspace -or $saved.source_writer -cne 'quiesced' -or @($saved.uncertain_actions).Count -or
    $saved.profile -cne '/Users/pouya/.claude' -or $saved.history.path -cne $history.path -or
    $saved.history.bytes -ne $history.bytes -or $saved.history.sha256 -cne $history.sha256){throw 'Partial checkpoint changed; no replacement or native replay'}
  }else{
   Save $checkpoint @{schema='ccrelay.personal_claude_handoff.v1';session_id=$history.session;workspace=$history.workspace;source_writer='quiesced';uncertain_actions=@();profile='/Users/pouya/.claude';history=@{path=$history.path;bytes=$history.bytes;sha256=$history.sha256}}
  }
  Protect $checkpoint $false $true
  $checkpoints[$history.session]=@{Chat=$history.chat;Topic=$history.topic;Workspace=$history.workspace;Sha256=(Get-FileHash $checkpoint).Hash.ToLowerInvariant()}
 }
 $tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile("$nativeRoot\stage-dut-topic.ps1",[ref]$tokens,[ref]$errors)
 if($errors.Count){throw 'Accepted SQLite source failed parsing'}
 $definition=$ast.Find({param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type' -and $n.Extent.Text -like '*class PcbaRegistry*'},$true)
 if(-not $definition){throw 'Accepted SQLite definition missing'};& ([ScriptBlock]::Create($definition.Extent.Text))
 $exclusive=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null
 try{
  $db=[PcbaRegistry]::new()
  $uncertain=$db.Read("SELECT (SELECT COUNT(*) FROM operations WHERE status IN ('attempting','unknown'))+(SELECT COUNT(*) FROM updates WHERE status IN ('received','dispatching','unknown'))")
  if([int]$uncertain[0][0]){throw 'Input or effects remain unreconciled; no deployment'}
  $bindings=@($db.Read('SELECT payload FROM bindings')|ForEach-Object {$_[0]|ConvertFrom-Json})
  $prior=Get-Content "$release\prior-bindings.json" -Raw -Encoding UTF8|ConvertFrom-Json
  if(@($bindings).Count -ne 9 -or (ConvertTo-Json -Depth 100 -Compress @($bindings|Sort-Object Chat,Topic)) -ne
   (ConvertTo-Json -Depth 100 -Compress @($prior|Sort-Object Chat,Topic))){throw 'Topic bindings changed; preserve them and review'}
  $null=$db.Read("VACUUM INTO '"+"$release\previous-router.db"+"'")
 }finally{if($db){$db.Dispose()};$exclusive.Dispose()}
 Copy-Item "$root\bin" "$release\previous-bin" -Recurse
 $policy.LinuxClaude.PackageRoot=$package;$policy.LinuxClaude.Checkpoints=$checkpoints
 Save "$root\config.json" $policy
 Copy-Item "$release\candidate\publish-live\*" "$root\bin" -Force -Recurse
 Get-ChildItem "$root\bin" -Recurse -Force|ForEach-Object {Protect $_.FullName $_.PSIsContainer}
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $prepared.code){throw 'Installed binary digest differs'}
 Save "$release\stage.json" @{generation=$Generation;code=$prepared.code;policy=(Get-FileHash "$root\config.json").Hash;histories=$histories;at=[DateTimeOffset]::UtcNow.ToString('o')}
 [ordered]@{phase='staged-not-live';code=$prepared.code;policy=(Get-FileHash "$root\config.json").Hash;checkpoints=5;registryChanged=$false}|ConvertTo-Json -Compress;exit
}
$staged=Get-Content "$release\stage.json" -Raw -Encoding UTF8|ConvertFrom-Json
$policy=Get-Content "$root\config.json" -Raw -Encoding UTF8|ConvertFrom-Json
$proof=Get-Content "$root\state\probe.json" -Raw -Encoding UTF8|ConvertFrom-Json
$prior=Get-Content "$release\previous-probe.json" -Raw -Encoding UTF8|ConvertFrom-Json
if(-not $proof.verified -or $proof.routerSha256 -ne $staged.code -or $proof.policySha256 -ne $staged.policy -or
 -not $proof.credentialAndCodeDenied -or -not $proof.aclProbeWithoutProviderSandbox -or -not $proof.nativeWindowsSandboxVerified -or
 -not $proof.nativeLinuxCodexVerified -or -not $proof.nativeLinuxCommandOwnerVerified -or $proof.modelInference -or $proof.telegramPolling -or
 [DateTimeOffset]$proof.testedAt -le [DateTimeOffset]$staged.at -or $prior.routerSha256 -ne $oldCode -or $prior.policySha256 -ne $oldPolicy -or
 -not $prior.nativeLinuxClaudeLaunchVerified -or -not $prior.nativeLinuxClaudeToolOwnerVerified -or -not $prior.nativeLinuxClaudeContinuityVerified){throw 'Fresh exact OS proof and accepted unchanged Claude runtime evidence required'}
if(Test-Path "$release\generic-proof-before-native.json"){throw 'Acceptance already consumed; reconcile instead of repeating'}
Copy-Item "$root\state\probe.json" "$release\generic-proof-before-native.json"
$proof.nativeLinuxClaudeLaunchVerified=$true;$proof.nativeLinuxClaudeToolOwnerVerified=$true;$proof.nativeLinuxClaudeContinuityVerified=$true
foreach($name in @('nativeLinuxClaudeAcceptance','nativeLinuxClaudeNewTopicAcceptance')){if($prior.PSObject.Properties[$name]){$proof|Add-Member $name $prior.$name -Force}}
$proof|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Formatting-only router update; native launcher/control/runtime source unchanged';priorRouterSha256=$oldCode;currentRouterSha256=$staged.code;connectorFiles=$policy.LinuxClaude.FileSha256;freshCheckpoints=5;modelsRerun=$false;liveProductionInitializationRequired=$true} -Force
Save "$root\state\probe.json" $proof
[ordered]@{phase='accepted-not-live';freshOsProof=$true;priorNativeChecksReused=$true;registryChanged=$false}|ConvertTo-Json -Compress
