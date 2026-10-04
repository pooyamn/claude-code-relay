param([Parameter(Mandatory=$true)][ValidateSet('candidate','stage','accept')][string]$Phase,
 [ValidatePattern('^C:\\ProgramData\\KhadangRouter\\release-[0-9a-f]{32}$')][string]$RecoveryDirectory)
# Fixed Claude-only app hook. No topic/native-ID replacement or Codex change.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$nativeRoot='C:\ProgramData\OracovaNativeRemote'
$generation='08740876d17b4c70a50ecf5c8c789c44'
$session='7dc840b0-402f-451e-bc79-dadfb706d363'
$artifact=Join-Path $nativeRoot ('router-claude-ui-'+$generation)
$package=Join-Path $nativeRoot ('claude-connector-'+$generation)
$archive=Join-Path $nativeRoot ('router-claude-remote-'+$generation+'.zip')
$newCode='94111E96E68F5D935FAA3DF94085E81F06AC3867E28A75DF290A744048D55841'
$oldCode='84AB5DEA4B368980A0754FB64D23F2ABBE0F63DCADA6EAFDB1F752E1A37E5690'
$oldPolicy='0A697FF22F479A1125C0ADEF9DA699D197F57FF71B20DAA7D202A1BCCD70FEA7'
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544');$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed administrator deployment required'}
function Protect([string]$Path,[bool]$Directory,[bool]$Readable=$false){
 if((Get-Item $Path).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Reparse artifact forbidden'}
 if($Directory){$acl=[Security.AccessControl.DirectorySecurity]::new();$inherit=[Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'}
 else{$acl=[Security.AccessControl.FileSecurity]::new();$inherit=[Security.AccessControl.InheritanceFlags]::None}
 $acl.SetOwner($admin);$acl.SetAccessRuleProtection($true,$false)
 foreach($sid in @($admin,$system)){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl',$inherit,'None','Allow'))}
 if($Readable){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($owner,'ReadAndExecute',$inherit,'None','Allow'))};Set-Acl $Path $acl
}
function Save([string]$Path,$Value){[IO.File]::WriteAllText($Path,($Value|ConvertTo-Json -Depth 100),[Text.UTF8Encoding]::new($false))}
if($Phase -eq 'candidate'){
 if(Test-Path $artifact){throw 'Candidate exists; inspect rather than overwrite'}
 Protect $archive $false
 if((Get-FileHash $archive).Hash -ne 'C540A4AC9C9ECCC2D0437767AF806CDB10EAF8CB254463D31F0CA84F3F21D749'){throw 'Approved candidate archive differs'}
 New-Item -ItemType Directory $artifact|Out-Null;Protect $artifact $true
 Expand-Archive -LiteralPath $archive -DestinationPath $artifact
 foreach($file in Get-ChildItem $artifact -Recurse -Force){Protect $file.FullName $file.PSIsContainer}
 if((Get-FileHash "$artifact\publish-live\KhadangRouter.dll").Hash -ne $newCode){throw 'Actual candidate code differs'}
 & "$artifact\publish-live\KhadangRouter.exe" --self-test
 if($LASTEXITCODE -ne 0){throw 'Actual Windows candidate regressions failed; production untouched'}
 Save "$artifact\candidate-tested.json" @{code=$newCode;models=$false;productionChanged=$false;testedAt=[DateTimeOffset]::UtcNow.ToString('o')}
 'Windows candidate tests passed; production untouched';exit
}
if(-not $RecoveryDirectory -or -not (Test-Path $RecoveryDirectory) -or
 (Get-Service KhadangRouter).Status.ToString() -ne 'Stopped' -or (Get-ScheduledTask -TaskName Oracova-KhadangStartup).State.ToString() -ne 'Disabled'){
 throw 'Stopped production with exact retained preimages and fenced supervisor required'
}
if((Get-Content "$artifact\candidate-tested.json" -Raw -Encoding UTF8|ConvertFrom-Json).code -ne $newCode){throw 'Windows candidate acceptance missing'}
if($Phase -eq 'stage'){
 if((Get-FileHash "$root\config.json").Hash -ne $oldPolicy -or (Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $oldCode -or (Test-Path $package)){throw 'Expected original policy/code and unconsumed generation required'}
 $raw=(. "$nativeRoot\inspect-state.ps1") -join "`n";$state=$raw|ConvertFrom-Json
 if(@($state.bindings).Count -ne 5){throw 'Exactly five existing bindings required'}
 foreach($row in @($state.metadata|Where-Object key -like 'bubble/*')){
  if($row.value.busy -or $row.value.held -or $row.value.sendUnknown -or @($row.value.pendingResponses).Count){throw 'Native work active or unresolved'}
 }
 $count=[RouterReceipts]::Read("SELECT (SELECT COUNT(*) FROM operations WHERE status IN ('attempting','unknown'))+(SELECT COUNT(*) FROM updates WHERE status IN ('received','dispatching','unknown'))")
 if([int]$count[0][0]){throw 'Unreconciled work appeared during stop; no code/config change'}
 $before=[IO.File]::ReadAllText("$root\config.json");$policy=$before|ConvertFrom-Json
 if($policy.LinuxClaude.PackageRoot -ne "$nativeRoot\claude-connector-aeb2520d0ecc787dc2e18790169d9476" -or
  @($policy.LinuxClaude.Checkpoints.PSObject.Properties).Count -ne 1){throw 'Exact current DUT runtime required'}
 $inspection=@(& wsl.exe -d Ubuntu-24.04 -u pou --exec /usr/bin/python3 -I -B /mnt/c/ProgramData/OracovaNativeRemote/inspect-dut-pc-history.py)
 if($LASTEXITCODE -ne 0){throw 'Native history inspection failed'}
 $history=$inspection[0]|ConvertFrom-Json
 if($history.session -ne $session -or @($history.liveProducers).Count -ne 0 -or $history.ownerUid -ne 1000 -or $history.mode -ne '0o600' -or
  @($history.sessionIds).Count -ne 1 -or $history.sessionIds[0] -ne $session -or $history.bytes -le 0){throw 'Exact stopped native conversation required'}
 Add-Type @'
using System;using System.Runtime.InteropServices;
public static class DutUiSnapshot {
 [DllImport(@"C:\Windows\System32\winsqlite3.dll",CharSet=CharSet.Ansi)]static extern int sqlite3_open_v2(string p,out IntPtr d,int f,IntPtr v);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll",CharSet=CharSet.Ansi)]static extern int sqlite3_exec(IntPtr d,string s,IntPtr c,IntPtr a,out IntPtr e);
 [DllImport(@"C:\Windows\System32\winsqlite3.dll")]static extern int sqlite3_close_v2(IntPtr d);
 public static void Capture(string p){IntPtr d,e;if(sqlite3_open_v2(@"C:\ProgramData\KhadangRouter\state\router.db",out d,2,IntPtr.Zero)!=0)throw new Exception("Snapshot open failed");try{if(sqlite3_exec(d,"VACUUM INTO '"+p+"'",IntPtr.Zero,IntPtr.Zero,out e)!=0)throw new Exception("Consistent snapshot failed");}finally{sqlite3_close_v2(d);}}
}
'@
 $exclusive=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None')
 try{
  $backup=Join-Path $RecoveryDirectory 'previous-router.db';if(Test-Path $backup){throw 'Snapshot exists; no replay'}
  [DutUiSnapshot]::Capture($backup)
  New-Item -ItemType Directory $package|Out-Null;Protect $package $true $true
  New-Item -ItemType Directory "$package\relay_core"|Out-Null;Protect "$package\relay_core" $true $true
  foreach($property in $policy.LinuxClaude.FileSha256.PSObject.Properties){
   $source=Join-Path $policy.LinuxClaude.PackageRoot $property.Name
   if((Get-Item $source).Attributes -band [IO.FileAttributes]::ReparsePoint -or (Get-FileHash $source).Hash -ne $property.Value){throw 'Previously accepted native connector changed'}
   $target=Join-Path $package $property.Name;Copy-Item -LiteralPath $source -Destination $target;Protect $target $false $true
  }
  $checkpoint=Join-Path $package ('handoff-'+$session+'.json')
  Save $checkpoint @{schema='ccrelay.personal_claude_handoff.v1';session_id=$session;workspace='/Users/pouya/.openclaw/workspace/ai-hil/hardware/duts';source_writer='quiesced';uncertain_actions=@();profile='/Users/pouya/.claude';
   history=@{path=('/Users/pouya/.claude/projects/-Users-pouya--openclaw-workspace-ai-hil-hardware-duts/'+$session+'.jsonl');bytes=$history.bytes;sha256=$history.sha256}}
  Protect $checkpoint $false $true
  $policy.LinuxClaude.PackageRoot=$package;$policy.LinuxClaude.Checkpoints.$session.Sha256=(Get-FileHash $checkpoint).Hash.ToLowerInvariant()
  if([IO.File]::ReadAllText("$root\config.json") -ne $before){throw 'Policy changed during review'}
  Save "$root\config.json" $policy
  Save (Join-Path $RecoveryDirectory 'dut-app-stage.json') @{phase='staged-not-live';policySha256=(Get-FileHash "$root\config.json").Hash;history=$history;
   checkpointSha256=$policy.LinuxClaude.Checkpoints.$session.Sha256;nativeCodeFilesUnchanged=$true;bindingsChanged=$false;modelsStarted=$false;at=[DateTimeOffset]::UtcNow.ToString('o')}
 }finally{$exclusive.Dispose()}
 Get-Content (Join-Path $RecoveryDirectory 'dut-app-stage.json') -Raw -Encoding UTF8;exit
}
$staged=Get-Content (Join-Path $RecoveryDirectory 'dut-app-stage.json') -Raw -Encoding UTF8|ConvertFrom-Json
$proof=Get-Content "$root\state\probe.json" -Raw -Encoding UTF8|ConvertFrom-Json
$prior=Get-Content (Join-Path $RecoveryDirectory 'previous-probe.json') -Raw -Encoding UTF8|ConvertFrom-Json
if($proof.policySha256 -ne $staged.policySha256 -or $proof.policySha256 -ne (Get-FileHash "$root\config.json").Hash -or
 $proof.routerSha256 -ne $newCode -or (Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $newCode -or
 -not $proof.verified -or -not $proof.credentialAndCodeDenied -or -not $proof.aclProbeWithoutProviderSandbox -or -not $proof.nativeWindowsSandboxVerified -or
 -not $proof.nativeLinuxCodexVerified -or -not $proof.nativeLinuxCommandOwnerVerified -or $proof.nativeOwnerSid -ne $owner.Value -or
 $proof.modelInference -or $proof.telegramPolling -or [DateTimeOffset]$proof.testedAt -le [DateTimeOffset]$staged.at -or
 $prior.policySha256 -ne $oldPolicy -or $prior.routerSha256 -ne $oldCode -or -not $prior.nativeLinuxClaudeLaunchVerified -or
 -not $prior.nativeLinuxClaudeToolOwnerVerified -or -not $prior.nativeLinuxClaudeContinuityVerified -or $prior.nativeLinuxClaudeAcceptance.session -ne $session){throw 'Matching fresh OS proof and previous actual native acceptance required'}
$preimage=Join-Path $RecoveryDirectory 'generic-probe-before-native-compatibility.json';if(Test-Path $preimage){throw 'Acceptance already attempted; no replay'}
Copy-Item "$root\state\probe.json" $preimage
# Actual earlier native tool/continuity evidence remains applicable: the pinned
# native executable, seven Python files, stream parser, owner launcher, policy,
# ledger and program gates are unchanged. This is explicitly REUSED evidence,
# not a claim that those model checks were repeated on this assembly. The new
# app hook has separate fresh Windows regressions and must enroll natively live.
$proof.nativeLinuxClaudeLaunchVerified=$true;$proof.nativeLinuxClaudeToolOwnerVerified=$true;$proof.nativeLinuxClaudeContinuityVerified=$true
$proof|Add-Member nativeLinuxClaudeAcceptance $prior.nativeLinuxClaudeAcceptance
$proof|Add-Member nativeLinuxClaudeAcceptanceReuse @{previousRouterSha256=$oldCode;previousPolicySha256=$oldPolicy;newCheckpointSha256=$staged.checkpointSha256;
 unchangedNativeCoreSource=@{ClaudeNativeStream='f3366d75de68fae473065e21c7d870caa0d4f2dc2a14e2f9a040178f9ecd4a36';LinuxClaudeRuntime='f63781a8aa8f5b46b11ff9bdba33485a583a43f7bd131596ccdeaec9bd35e24b';WindowsOwnerProcess='bf7f69d4d31542784fcdf0bfc22ac8170748d707f6add9bacd3b2fab190f1b74';NativeChannel='809ac247ec2650f8a6864b47759e5de3222e56a72ef41a0e5ee7c3814488eb8f';Policy='c46e93b72873b6c68c8be6817c690dfdd31e75edd11dad40da61ac7ff197f034';Ledger='8e49c456b95e1217948c487b6b9cf133eba2b4e96f0c88a8327ddf2323b8ccf6';Program='aaf804bd3ba1b524297129317f739445a4ad9003ca5cb23092d4d264719e77a0'};
 newAppEnrollmentStillRequiresLiveNativeReceipt=$true;at=[DateTimeOffset]::UtcNow.ToString('o')}
Save "$root\state\probe.json" $proof
@{phase='accepted-not-live';policy=$proof.policySha256;code=$proof.routerSha256;nativeAcceptanceReusedWithUnchangedCore=$true;liveAppEnrollmentPending=$true}|ConvertTo-Json -Compress
