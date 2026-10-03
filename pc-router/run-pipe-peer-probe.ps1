param(
 [Parameter(Mandatory=$true)][ValidatePattern('^C:\\ProgramData\\OracovaNativeRemote\\pipe-probe-[0-9a-f]{32}\.zip$')][string]$Archive,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedSha256,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RunId
)
# Credential-free kernel test; not a live broker installer or a security approval.
# The SYSTEM task runs ONLY the fixed diagnostic fixture, never a native model.
# A second exact Interactive/Limited owner task attempts the denied connection.
# Both are one-shot, no triggers/repetition/restart, with retained evidence.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or
 -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
 throw 'Exact PC administrator diagnostic installer required'
}
$root='C:\ProgramData\OracovaNativeRemote';$release=Join-Path $root ('pipe-probe-'+$RunId)
$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544');$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$task='Oracova-PipePeerProbe-'+$RunId;$ownerTask='Oracova-PipeOwnerDenial-'+$RunId
$ownerResult=Join-Path 'C:\Users\pou\.native-remote' ('pipe-owner-denial-'+$RunId+'\result.json')
if((Get-Service KhadangRouter).Status.ToString() -ne 'Running' -or
 (Get-FileHash 'C:\ProgramData\KhadangRouter\config.json').Hash -ne '653FD4D37637BEA5ED8C88BF063A1669D5A0DCA5E3B6BDD795189D151A2FD2EC' -or
 -not (Get-Acl $root).AreAccessRulesProtected -or (Get-Item -LiteralPath $root).Attributes -band [IO.FileAttributes]::ReparsePoint){
 throw 'Existing protected diagnostic root and unchanged running router required'
}
if((Test-Path -LiteralPath $release) -or (Test-Path -LiteralPath $ownerResult) -or
 (Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue) -or
 (Get-ScheduledTask -TaskName $ownerTask -ErrorAction SilentlyContinue)){throw 'Prior fixture exists; inspect, never replay/overwrite'}
if((Get-Item -LiteralPath $Archive).Attributes -band [IO.FileAttributes]::ReparsePoint -or
 (Get-FileHash -LiteralPath $Archive).Hash -ne $ExpectedSha256){throw 'Exact literal diagnostic archive digest required'}
[IO.Directory]::CreateDirectory($release)|Out-Null
Expand-Archive -LiteralPath $Archive -DestinationPath $release
$bin=Join-Path $release 'publish-pipe';$exe=Join-Path $bin 'PipePeerProbe.exe'
$runtime=Get-Content (Join-Path $bin 'PipePeerProbe.runtimeconfig.json') -Raw | ConvertFrom-Json
if(-not (Test-Path -LiteralPath $exe) -or -not (Test-Path -LiteralPath (Join-Path $bin 'coreclr.dll')) -or
 -not ($runtime.runtimeOptions.includedFrameworks | Where-Object name -eq 'Microsoft.NETCore.App')){throw 'Self-contained diagnostic required'}
Get-ChildItem -LiteralPath $release -Recurse -Force | ForEach-Object {
 if($_.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Diagnostic reparse point refused'}
 $acl=Get-Acl $_.FullName;$acl.SetOwner($admin);Set-Acl $_.FullName $acl
}
$acl=Get-Acl $release;$acl.SetOwner($admin);$acl.SetAccessRuleProtection($true,$false)
$inherit=[Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'
foreach($sid in @($admin,$system)){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl',$inherit,'None','Allow'))}
$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($owner,'ReadAndExecute',$inherit,'None','Allow'))
Set-Acl $release $acl
& $exe --self-test
if($LASTEXITCODE -ne 0){throw 'Protected-pipe argument checks failed'}
& (Join-Path $bin 'KhadangRouter.exe') --self-test
if($LASTEXITCODE -ne 0){throw 'Actual Windows candidate router checks failed'}
$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$systemPrincipal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$limited=New-ScheduledTaskPrincipal -UserId $owner.Value -LogonType Interactive -RunLevel Limited
$action=New-ScheduledTaskAction -Execute $exe -Argument ('--run '+$RunId) -WorkingDirectory $bin
$ownerAction=New-ScheduledTaskAction -Execute $exe -Argument ('--owner-denial '+$RunId) -WorkingDirectory $bin
Register-ScheduledTask -TaskName $task -Action $action -Principal $systemPrincipal -Settings $settings | Out-Null
Register-ScheduledTask -TaskName $ownerTask -Action $ownerAction -Principal $limited -Settings $settings | Out-Null
$scheduler=New-Object -ComObject Schedule.Service;$scheduler.Connect();$folder=$scheduler.GetFolder('\')
foreach($name in @($task,$ownerTask)){
 # Never leave a creator/ordinary-principal task-mutation grant. No running
 # task is changed: protect these new one-shot fixtures before either starts.
 $registered=$folder.GetTask($name)
 $registered.SetSecurityDescriptor('O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)',0x10)
 $security=[Security.AccessControl.RawSecurityDescriptor]::new($registered.GetSecurityDescriptor(7))
 if($security.Owner.Value -ne $admin.Value -or -not ($security.ControlFlags -band [Security.AccessControl.ControlFlags]::DiscretionaryAclProtected)){
  throw 'Protected diagnostic task owner/DACL required'
 }
 foreach($ace in $security.DiscretionaryAcl){
  if($ace.SecurityIdentifier.Value -notin @($admin.Value,$system.Value)){throw 'Untrusted diagnostic task access grant'}
 }
}
[IO.File]::WriteAllText((Join-Path $release 'reviewed-run.json'),(@{run=$RunId;archiveSha256=$ExpectedSha256;
 systemTask=$task;ownerTask=$ownerTask;modelsStarted=$false;productionChanged=$false;oneShot=$true} | ConvertTo-Json -Compress))
Start-ScheduledTask -TaskName $task
$ready=Join-Path $release 'state\owner-denial-ready.json';$result=Join-Path $release 'state\result.json'
$until=[DateTimeOffset]::UtcNow.AddSeconds(15)
while(-not (Test-Path -LiteralPath $ready)){
 if((Test-Path -LiteralPath $result) -or [DateTimeOffset]::UtcNow -gt $until){throw 'Kernel fixture did not reach owner-denial window; inspect retained result'}
 Start-Sleep -Milliseconds 100
}
Start-ScheduledTask -TaskName $ownerTask
$until=[DateTimeOffset]::UtcNow.AddSeconds(15)
while(-not (Test-Path -LiteralPath $ownerResult)){
 if([DateTimeOffset]::UtcNow -gt $until){throw 'Limited-owner denial result missing; inspect, never replay'}
 Start-Sleep -Milliseconds 100
}
$observation=Get-Content -LiteralPath $ownerResult -Raw | ConvertFrom-Json
if(-not $observation.complete -or -not $observation.accessDenied -or -not $observation.componentDenied -or
 $observation.sid -ne $owner.Value -or $observation.elevated -or $observation.session -ne 1){throw 'Exact ordinary-owner explicit denial required'}
$until=[DateTimeOffset]::UtcNow.AddSeconds(5)
while((Get-ScheduledTask -TaskName $ownerTask).State.ToString() -eq 'Running'){
 if([DateTimeOffset]::UtcNow -gt $until){throw 'Owner task has not ended'};Start-Sleep -Milliseconds 100
}
if((Get-ScheduledTaskInfo -TaskName $ownerTask).LastTaskResult -ne 0){throw 'Owner task failed'}
# Protected coordinator acknowledgement, not a file written by the owner.
# Owner-writable diagnostic observations do not authorize any production effect.
[IO.File]::WriteAllText((Join-Path $release 'owner-denial-observed.json'),(@{complete=$true;ownerTask=$ownerTask;
 ownerResultSha256=(Get-FileHash -LiteralPath $ownerResult).Hash;observedAt=[DateTimeOffset]::UtcNow} | ConvertTo-Json -Compress))
$until=[DateTimeOffset]::UtcNow.AddSeconds(10)
while(-not (Test-Path -LiteralPath $result)){
 if([DateTimeOffset]::UtcNow -gt $until){throw 'Kernel fixture result missing; inspect, never replay'};Start-Sleep -Milliseconds 100
}
$proof=Get-Content -LiteralPath $result -Raw | ConvertFrom-Json
if(-not $proof.complete){throw 'Kernel fixture failed; inspect retained result'}
[Console]::WriteLine((@{systemTask=$task;ownerTask=$ownerTask;result=$result;complete=$true;
 mutuallyAuthenticatedConnections=$proof.mutuallyAuthenticatedConnections;ownerExplicitlyDenied=$true;productionChanged=$false} | ConvertTo-Json -Compress))
