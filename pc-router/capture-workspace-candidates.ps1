param(
 [Parameter(Mandatory=$true)][ValidateSet('prepare','capture','verify')][string]$Phase,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RunId,
 [Parameter(Mandatory=$true)][ValidatePattern('^tree-audit-[A-Za-z0-9]{8}$')][string]$AuditName
)
# Preserve whole-walk candidate deltas with the existing exact-leaf receiver.
# No project import, links activation, router/native restart or source freeze.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$parent='C:\ProgramData\OracovaMigration';$folder=Join-Path $parent $RunId
$original=Join-Path $parent 'stream-helper-54bc2b09b7084ccd9f4c42dc8311fc0f'
$source='\\wsl.localhost\Ubuntu-24.04\Users\pouya\.migration\'+$AuditName
$hashes=@{'capture-mac-stream.ps1'='14295fa525ca9250d1b0a1b3121cc01038082ec25c760158a580684349b43ce9';
 'test-mac-stream.ps1'='847c7d72a52c6cba2e15e3468c0f6d959e37755bca54ecf052b614c979f710ba';
 'stream_owner_tools.py'='be7985bc80bb16d3f4005b3a4956cc4544e1c5df62ee8ca7954873cdf1ed8895'}
$principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Exact administrator capture lane required'}
foreach($name in $hashes.Keys){if((Get-FileHash (Join-Path $original $name)).Hash.ToLowerInvariant() -ne $hashes[$name]){throw 'Accepted immutable capture helper changed'}}
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $original 'capture-mac-stream.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Accepted capture helper parse error'}
foreach($f in $ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){. ([ScriptBlock]::Create($f.Extent.Text))}
Assert-MigrationStreamParent $parent
function Save([string]$Path,$Value){$f=New-MigrationStreamFile $Path;try{$b=[Text.UTF8Encoding]::new($false).GetBytes(($Value|ConvertTo-Json -Depth 50 -Compress));$f.Write($b,0,$b.Length);$f.Flush($true)}finally{$f.Dispose()}}
function CopyPrivate([string]$From,[string]$To,[string]$Expected){
 if(Test-Path $To){throw 'Private destination exists; no overwrite'}
 if((Get-Item -LiteralPath $From -Force).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Literal private source file required'}
 Copy-Item -LiteralPath $From -Destination $To;Set-Acl -LiteralPath $To -AclObject (New-MigrationStreamAcl $false)
 if((Get-FileHash $To).Hash.ToLowerInvariant() -ne $Expected.ToLowerInvariant()){throw 'Protected private file hash mismatch'}
}
function RouterObservation {
 $root='C:\ProgramData\KhadangRouter';$s=Get-Content "$root\state\status.json" -Raw|ConvertFrom-Json
 $service=(Get-Service KhadangRouter).Status.ToString()
 if($service -notin @('Running','Stopped')){throw 'Stable observed service state required; no capture-time service effects'}
 if($service -eq 'Running' -and ($s.bindings.Count -ne 12 -or $s.unknown)){throw 'Healthy routing required when running; capture never repairs/restarts it'}
 $code=(Get-FileHash "$root\bin\KhadangRouter.dll").Hash;$policy=(Get-FileHash "$root\config.json").Hash
 if($code -ne 'FFAEC6699B17BD59C47BC40DC83D4364F6A0B9EE18101B40DAF0A45152F8D94C' -or $policy -ne '33F8BE3BF0E538B03FCB20AC612310CEA3877E0387C3663D67635BBF55C1E522'){throw 'Reviewed current PC code/policy changed'}
 # Preservation does not require a running agent/router. A stopped router's
 # last status is historical evidence, never a live routing acceptance claim.
 return @{serviceState=$service;liveRoutingVerified=($service -eq 'Running');at=$s.at;routes=$s.bindings.Count;connectedClaude=@($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and $_.claudeConnected}).Count;
  nativeLinuxPid=$s.nativeLinuxPid;nativeWindowsPid=$s.nativePid;unknown=$s.unknown;presentationUnknown=$s.presentationUnknown;code=$code;policy=$policy}
}
function Assert-CaptureRouterUnchanged($Before,$After){
 if($Before.serviceState -notin @('Running','Stopped') -or $After.serviceState -ne $Before.serviceState -or
  $After.code -ne $Before.code -or $After.policy -ne $Before.policy){throw 'Service/code/policy changed during preservation; no automatic repair'}
 if($After.serviceState -eq 'Running' -and ($After.nativeLinuxPid -ne $Before.nativeLinuxPid -or
  $After.nativeWindowsPid -ne $Before.nativeWindowsPid -or $After.connectedClaude -ne 7)){
  throw 'Native routing changed during capture; report it, never repair automatically'
 }
}
if($Phase -eq 'prepare'){
 if(Test-Path $folder){throw 'Fresh observation/capture generation required'}
 $before=RouterObservation
 [IO.Directory]::CreateDirectory($folder,(New-MigrationStreamAcl $true))|Out-Null
 foreach($name in @('capture-receipt.json','candidate-content-receipt.json')){
  $from=Join-Path $source $name;CopyPrivate $from (Join-Path $folder $name) (Get-FileHash $from).Hash
 }
 $metadata=Get-Content "$folder\capture-receipt.json" -Raw|ConvertFrom-Json
 $candidate=Get-Content "$folder\candidate-content-receipt.json" -Raw|ConvertFrom-Json
 if($metadata.schema -ne 'ccrelay.workspace_metadata_capture.v1' -or $candidate.schema -ne 'ccrelay.workspace_candidate_content_capture.v1' -or
  $metadata.sourceProblems -or $candidate.counts.errors -or $candidate.incompatibleNames -or @($candidate.selections).Count -lt 1 -or @($candidate.selections).Count -gt 25){throw 'Complete bounded candidate observations required'}
 $files=@(@('mac-metadata.private.json',$metadata.source.sha256),@('comparison.private.json',$metadata.comparison.sha256),
  @('candidate-source.private.json',$candidate.source.sha256),@('candidate-pc.private.json',$candidate.pc.sha256),@('candidate-content-differences.private.json',$candidate.comparison.sha256))
 foreach($pair in $files){CopyPrivate (Join-Path $source $pair[0]) (Join-Path $folder $pair[0]) $pair[1]}
 $batches=@();$number=0
 foreach($selection in $candidate.selections){
  $number++;if($selection.name -notmatch '^candidate-selection-[1-9][0-9]*\.private\.json$' -or $selection.entries -lt 1 -or $selection.entries -gt 4000 -or $selection.bytes -gt 4MB){throw 'Literal bounded selection required'}
  CopyPrivate (Join-Path $source $selection.name) (Join-Path $folder $selection.name) $selection.sha256
  $helperId=[Guid]::NewGuid().ToString('N');$archiveId=[Guid]::NewGuid().ToString('N');$helper=Join-Path $parent ('stream-helper-'+$helperId)
  [IO.Directory]::CreateDirectory($helper,(New-MigrationStreamAcl $true))|Out-Null
  foreach($name in $hashes.Keys){CopyPrivate (Join-Path $original $name) (Join-Path $helper $name) $hashes[$name]}
  CopyPrivate (Join-Path $folder $selection.name) (Join-Path $helper 'dirty-selection.json') $selection.sha256
  $batches+=@{number=$number;helper=$helper;run=$archiveId;selectionSha256=$selection.sha256;entries=$selection.entries;fileBytes=$selection.fileBytes}
 }
 & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $batches[0].helper 'test-mac-stream.ps1')
 if($LASTEXITCODE -ne 0){throw 'Actual sealed Windows receiver fixtures failed'}
 Save "$folder\plan.json" @{schema='ccrelay.workspace_candidate_preservation.v1';batches=$batches;before=$before;metadata=$metadata;candidate=$candidate;windowsFixturesPassed=$true;code=$hashes;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='prepared';batches=$batches.Count;entries=$candidate.counts.differentOrMissing;routerChanged=$false}|ConvertTo-Json -Compress;return
}
$plan=Get-Content "$folder\plan.json" -Raw|ConvertFrom-Json
Assert-MigrationStreamParent $folder
if($Phase -eq 'capture'){
 $null=RouterObservation
 foreach($batch in $plan.batches){
  foreach($name in $hashes.Keys){if((Get-FileHash (Join-Path $batch.helper $name)).Hash.ToLowerInvariant() -ne $hashes[$name]){throw 'Sealed capture code changed'}}
  if(Test-Path "$folder\attempt-$($batch.number).json"){throw 'Attempt already exists; inspect exact process/receipts, never rerun'}
  Save "$folder\attempt-$($batch.number).json" @{run=$batch.run;at=[DateTimeOffset]::UtcNow.ToString('o')}
  & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $batch.helper 'capture-mac-stream.ps1') -Profile vm-dirty-work-manifest -RunId $batch.run -OwnerToolsProducerSha256 $hashes['stream_owner_tools.py'] -DirtySelectionSha256 $batch.selectionSha256
  if($LASTEXITCODE -ne 0){throw 'Exact batch not accepted; keep partial state and do not retry'}
  Save "$folder\completed-$($batch.number).json" @{run=$batch.run;at=[DateTimeOffset]::UtcNow.ToString('o')}
 }
 @{phase='captures-terminal';batches=@($plan.batches).Count}|ConvertTo-Json -Compress;return
}
$results=@()
foreach($batch in $plan.batches){
 if(-not (Test-Path "$folder\completed-$($batch.number).json")){throw 'Batch terminal receipt absent; inspect process before deciding its state'}
 $root=Join-Path $parent $batch.run;Assert-MigrationStreamParent $root
 $r=Get-Content "$root\result.json" -Raw|ConvertFrom-Json;$archive="$root\vm-dirty-work-manifest.tar.gz"
 $acl=Get-Acl $archive
 if(-not $r.seedAccepted -or -not $r.fileManifestTargetVerified -or $r.producerExit -ne 0 -or $r.transportExit -ne 0 -or $r.archiveReaderExit -ne 0 -or
  $r.sourceWarningBytes -ne 0 -or $r.fileManifestEntries -ne $batch.entries -or $r.fileManifestBytes -ne $batch.fileBytes -or
  $r.consistentFinalSnapshot -or $r.extracted -or (Get-Item $archive).Length -ne $r.bytes -or (Get-FileHash $archive).Hash.ToLowerInvariant() -ne $r.sha256 -or
  -not $acl.AreAccessRulesProtected -or $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne 'S-1-5-32-544' -or
  @($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])|Where-Object {$_.IdentityReference.Value -notin @('S-1-5-18','S-1-5-32-544')}).Count){throw 'Independent exact archive/hash/ACL acceptance failed'}
 $results+=@{run=$batch.run;entries=$r.fileManifestEntries;fileBytes=$r.fileManifestBytes;bytes=$r.bytes;sha256=$r.sha256;finishedAt=$r.finishedAt}
}
$after=RouterObservation
Assert-CaptureRouterUnchanged $plan.before $after
$summary=@{schema='ccrelay.workspace_candidate_preservation_verified.v1';captures=$results;routerBefore=$plan.before;routerAfter=$after;verifiedAt=[DateTimeOffset]::UtcNow.ToString('o');
 sourceWritersFrozen=$false;allWorkspaceContentsVerified=$false;activeProjectsChanged=$false;sourceDeleted=$false;encryptedOffMachineRestoreVerified=$false}
Save "$folder\verified.json" $summary
$summary|ConvertTo-Json -Depth 10 -Compress
