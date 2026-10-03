param(
 [Parameter(Mandatory=$true)][ValidatePattern('^C:\\ProgramData\\OracovaNativeRemote\\sharing-probe-[0-9a-f]{32}\.zip$')][string]$Archive,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedSha256,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RunId
)
# One-shot transport test, not a production endpoint or remote enrollment.
# Administrator only installs/seals deterministic code; native execution uses
# the exact ordinary interactive owner, an empty credential-free child home,
# two authenticated local clients and two explicit bearer-denial checks.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=[Security.Principal.WindowsPrincipal]::new($identity)
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
 throw 'Reviewed PC administrator installer required'
}
$root='C:\ProgramData\OracovaNativeRemote';$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
if(-not (Get-Acl $root).AreAccessRulesProtected -or (Get-Item -LiteralPath $root).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Existing protected literal native code root required'}
if((Get-Service KhadangRouter).Status.ToString() -ne 'Running' -or
 (Get-FileHash 'C:\ProgramData\KhadangRouter\config.json').Hash -ne '653FD4D37637BEA5ED8C88BF063A1669D5A0DCA5E3B6BDD795189D151A2FD2EC'){
 throw 'Live unchanged router must remain running'
}
if((Get-Item -LiteralPath $Archive).Attributes -band [IO.FileAttributes]::ReparsePoint -or
 (Get-FileHash -LiteralPath $Archive).Hash -ne $ExpectedSha256){throw 'Reviewed literal diagnostic archive required'}
$release=Join-Path $root ('sharing-probe-'+$RunId);$taskName='Oracova-NativeSharingProbe-'+$RunId
$state=Join-Path 'C:\Users\pou\.native-remote' ('sharing-probe-'+$RunId)
if((Test-Path -LiteralPath $release) -or (Test-Path -LiteralPath $state) -or (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)){
 throw 'Prior probe exists; inspect it, never replay or overwrite'
}
[IO.Directory]::CreateDirectory($release)|Out-Null
Expand-Archive -LiteralPath $Archive -DestinationPath $release
$exe=Join-Path $release 'publish-sharing\NativeSharingProbe.exe'
$runtime=Get-Content (Join-Path $release 'publish-sharing\NativeSharingProbe.runtimeconfig.json') -Raw | ConvertFrom-Json
if(-not (Test-Path -LiteralPath $exe) -or -not (Test-Path -LiteralPath (Join-Path $release 'publish-sharing\coreclr.dll')) -or
 -not ($runtime.runtimeOptions.includedFrameworks | Where-Object name -eq 'Microsoft.NETCore.App')){throw 'Reviewed self-contained diagnostic required'}
# Read-only parent grants are preserved; each extracted entry loses the SCP
# owner's implicit WriteDAC before execution. No production ACL is changed.
Get-ChildItem -LiteralPath $release -Recurse -Force | ForEach-Object {
 $acl=Get-Acl $_.FullName;$acl.SetOwner($admin);Set-Acl $_.FullName $acl
}
$acl=Get-Acl $release;$acl.SetOwner($admin);$acl.SetAccessRuleProtection($true,$false)
$inherit=[Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'
foreach($sid in @($admin,$system)){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl',$inherit,'None','Allow'))}
$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($owner,'ReadAndExecute',$inherit,'None','Allow'))
Set-Acl $release $acl
& $exe --self-test
if($LASTEXITCODE -ne 0){throw 'Sharing-probe method guards failed'}
$action=New-ScheduledTaskAction -Execute $exe -Argument ('--run '+$RunId) -WorkingDirectory (Join-Path $release 'publish-sharing')
$limited=New-ScheduledTaskPrincipal -UserId $owner.Value -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
# No triggers, repetition, restart policy, credential arguments or SYSTEM agent.
Register-ScheduledTask -TaskName $taskName -Action $action -Principal $limited -Settings $settings | Out-Null
[IO.File]::WriteAllText((Join-Path $release 'reviewed-run.json'),(@{run=$RunId;archiveSha256=$ExpectedSha256;task=$taskName;
 oneShot=$true;modelsStarted=$false;productionChanged=$false;phoneRoundTripVerified=$false} | ConvertTo-Json -Compress))
Start-ScheduledTask -TaskName $taskName
[Console]::WriteLine((@{task=$taskName;state=(Get-ScheduledTask -TaskName $taskName).State.ToString();result=(Join-Path $state 'result.json')} | ConvertTo-Json -Compress))
