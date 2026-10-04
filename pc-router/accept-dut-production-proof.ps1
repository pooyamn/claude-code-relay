param([Parameter(Mandatory=$true)][ValidatePattern('^C:\\ProgramData\\KhadangRouter\\release-[0-9a-f]{32}$')][string]$RecoveryDirectory)
# Compose a fresh OS probe with two completed, candidate-bound native checks.
# No model input, Telegram call, token access or acceptance by fixtures.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter'
$package='C:\ProgramData\OracovaNativeRemote\claude-connector-aeb2520d0ecc787dc2e18790169d9476'
$session='7dc840b0-402f-451e-bc79-dadfb706d363'
$owner='S-1-5-21-71459778-1164188569-2276148161-1001'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or
 (Get-Service KhadangRouter).Status.ToString() -ne 'Stopped' -or (Get-ScheduledTask -TaskName 'Oracova-KhadangStartup').State.ToString() -ne 'Disabled'){throw 'Stopped router and fenced supervisor required'}
function Protected([string]$Path){
 $item=Get-Item -LiteralPath $Path
 if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Reparse evidence is forbidden'}
 $acl=Get-Acl -LiteralPath $Path
 if($acl.Owner -notin @('BUILTIN\Administrators','NT AUTHORITY\SYSTEM','S-1-5-32-544','S-1-5-18')){throw 'Evidence must be administrator/System-owned'}
 $mutation=[Security.AccessControl.FileSystemRights]'Write,Delete,ChangePermissions,TakeOwnership'
 foreach($rule in $acl.Access){$sid=$rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
  if($rule.AccessControlType -eq 'Allow' -and ($rule.FileSystemRights -band $mutation) -and $sid -notin @('S-1-5-18','S-1-5-32-544')){throw 'Ordinary-owner mutable evidence is forbidden'}}
}
foreach($p in @($root,$package,$RecoveryDirectory,"$root\config.json","$root\state","$root\state\probe.json","$root\bin\KhadangRouter.dll")){Protected $p}
$staged=Get-Content (Join-Path $RecoveryDirectory 'dut-migration.json') -Raw -Encoding UTF8|ConvertFrom-Json
$policy=Get-Content "$root\config.json" -Raw -Encoding UTF8|ConvertFrom-Json
$proof=Get-Content "$root\state\probe.json" -Raw -Encoding UTF8|ConvertFrom-Json
$code=(Get-FileHash "$root\bin\KhadangRouter.dll").Hash
if($staged.phase -ne 'staged-not-live' -or -not $staged.existingRoutesPreserved -or $staged.modelsStarted -or
 $proof.policySha256 -ne $staged.policySha256 -or $proof.policySha256 -ne (Get-FileHash "$root\config.json").Hash -or
 $proof.routerSha256 -ne $code -or $code -ne '84AB5DEA4B368980A0754FB64D23F2ABBE0F63DCADA6EAFDB1F752E1A37E5690' -or
 -not $proof.verified -or -not $proof.credentialAndCodeDenied -or -not $proof.aclProbeWithoutProviderSandbox -or
 -not $proof.nativeWindowsSandboxVerified -or -not $proof.nativeLinuxCodexVerified -or -not $proof.nativeLinuxCommandOwnerVerified -or
 $proof.nativeOwnerSid -ne $owner -or $proof.modelInference -or $proof.telegramPolling -or
 [DateTimeOffset]$proof.testedAt -le [DateTimeOffset]$staged.at){throw 'Fresh matching actual generic OS probe required'}
$candidatePath=Join-Path $package 'production-candidate.json';Protected $candidatePath
if((Get-FileHash $candidatePath).Hash -ne '0A697FF22F479A1125C0ADEF9DA699D197F57FF71B20DAA7D202A1BCCD70FEA7'){throw 'Final reviewed candidate changed'}
$candidate=Get-Content $candidatePath -Raw -Encoding UTF8|ConvertFrom-Json
if(($candidate.LinuxClaude|ConvertTo-Json -Depth 20 -Compress) -ne ($policy.LinuxClaude|ConvertTo-Json -Depth 20 -Compress) -or
 $policy.LinuxClaude.PackageRoot -ne $package){throw 'Production Claude differs from accepted candidate'}
$sources=@(
 @{run='1340c3563eb7f0867d3799727670d29b';result='81D5FCF60BC7A064DAEA2AA47F3C5837C6166670663F035F7B680CDBEF56790A';policy='0235DB8F98B6DEC2832B35222617E36843B66A9BAFC6C5AD75723F1169EC4C44';mode='--handoff'},
 @{run='f0584b2695ee26a7911032a40add5d6b';result='4A3AF708CBA666093129CEA4DBCE66219EF72D1684FAD10BE21C63E0B8FD55BF';policy='08C725E99EE6655EF42FB438B2CA09FDDE483E5C8DE520EB26D9B48171F94342';mode='--continuity'})
$reports=@();$evidence=@()
foreach($source in $sources){
 $directory=Join-Path $root ('dut-claude-acceptance-'+$source.run)
 $reportPath=Join-Path $directory 'result.json';$testPolicyPath=Join-Path $directory 'candidate.json'
 foreach($p in @($directory,$reportPath,$testPolicyPath)){Protected $p}
 if((Get-FileHash $reportPath).Hash -ne $source.result -or (Get-FileHash $testPolicyPath).Hash -ne $source.policy){throw 'Actual accepted native evidence changed'}
 $r=Get-Content $reportPath -Raw -Encoding UTF8|ConvertFrom-Json
 $testPolicy=Get-Content $testPolicyPath -Raw -Encoding UTF8|ConvertFrom-Json
 if(-not $r.complete -or -not $r.nativeLinuxClaudeLaunchVerified -or -not $r.nativeIdleAfterResult -or $r.routingChanged -or
  $r.unknownEffects -ne 0 -or $r.modelPromptsAttempted -ne 1 -or $r.mode -ne $source.mode -or $r.routerSha256 -ne $code -or $r.policySha256 -ne $source.policy -or
  $r.binding.Chat -ne -1004395661179 -or $r.binding.Topic -ne 53 -or $r.binding.ThreadId -ne $session -or
  $r.binding.Backend -ne 'claude' -or $r.binding.Runtime -ne 'linux' -or $r.binding.Workspace -ne '/Users/pouya/.openclaw/workspace/ai-hil/hardware/duts' -or
  $r.observation.WindowsOwner.Sid -ne $owner -or $r.observation.WindowsOwner.Elevated -or $r.observation.WindowsOwner.Session -le 0 -or
  $r.observation.NativePid -le 0 -or $r.observation.SessionId -ne $session -or $r.observation.CheckpointSha256 -ne $r.checkpointSha256 -or
  (Get-ScheduledTask -TaskName ('Oracova-DutClaudeProof-'+$source.run)).State.ToString() -ne 'Disabled' -or
  ($testPolicy.LinuxClaude.FileSha256|ConvertTo-Json -Compress) -ne ($policy.LinuxClaude.FileSha256|ConvertTo-Json -Compress) -or
  $testPolicy.LinuxClaude.WslSha256 -ne $policy.LinuxClaude.WslSha256){throw 'Exact actual native session/tool-owner evidence required'}
 $reports+=,$r;$evidence+=@{run=$source.run;resultSha256=$source.result;policySha256=$source.policy;nativeGeneration=$r.observation.NativeGeneration}
}
if(-not $reports[0].nativeLinuxClaudeToolOwnerVerified -or -not $reports[1].nativeLinuxClaudeContinuityVerified -or
 $reports[0].observation.NativeGeneration -eq $reports[1].observation.NativeGeneration){throw 'Actual tool owner and independent same-session resume required'}
foreach($property in $policy.LinuxClaude.FileSha256.PSObject.Properties){$p=Join-Path $package $property.Name;Protected $p
 if((Get-FileHash $p).Hash -ne $property.Value){throw 'Accepted runtime bytes changed'}}
$checkpoint=Join-Path $package ('handoff-'+$session+'.json');Protected $checkpoint
if((Get-FileHash $checkpoint).Hash -ne 'bb551a71ede33ab31665a74d82f9f263041f510c03c16426f7128cdb96d666e9' -or
 $policy.LinuxClaude.Checkpoints.$session.Sha256 -ne 'bb551a71ede33ab31665a74d82f9f263041f510c03c16426f7128cdb96d666e9'){throw 'Exact reviewed post-continuation checkpoint required'}
$preimage=Join-Path $RecoveryDirectory 'generic-probe-before-claude-acceptance.json'
if(Test-Path $preimage){throw 'Acceptance already attempted; inspect instead of replay'}
Copy-Item "$root\state\probe.json" $preimage
$proof.nativeLinuxClaudeLaunchVerified=$true
$proof.nativeLinuxClaudeToolOwnerVerified=$true
$proof.nativeLinuxClaudeContinuityVerified=$true
$proof|Add-Member nativeLinuxClaudeAcceptance ([ordered]@{session=$session;chat=-1004395661179;topic=53;sources=$evidence;
 checkpointSha256=$policy.LinuxClaude.Checkpoints.$session.Sha256;acceptedAt=[DateTimeOffset]::UtcNow.ToString('o')})
[IO.File]::WriteAllText("$root\state\probe.json",($proof|ConvertTo-Json -Depth 100),[Text.UTF8Encoding]::new($false))
[ordered]@{phase='accepted-not-live';policy=$proof.policySha256;code=$proof.routerSha256;claude=$proof.nativeLinuxClaudeAcceptance}|ConvertTo-Json -Depth 8 -Compress
