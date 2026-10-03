param(
 [Parameter(Mandatory=$true)][ValidatePattern('^C:\\ProgramData\\OracovaNativeRemote\\broker-probe-[0-9a-f]{32}\.zip$')][string]$Archive,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedSha256,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RunId
)
# One-shot acceptance, not a broker service/credential/policy deployment. SYSTEM
# runs only the deterministic fixture; native is launched through the reviewed
# WTS console-owner launcher, never as SYSTEM. Existing native remotes stay alive.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or
 -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
 throw 'Exact PC administrator diagnostic installer required'
}
$root='C:\ProgramData\OracovaNativeRemote';$release=Join-Path $root ('broker-probe-'+$RunId)
$workspace=Join-Path 'C:\Users\pou\.native-remote' ('broker-probe-'+$RunId)
$task='Oracova-NativeBrokerProbe-'+$RunId
$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544');$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18')
if((Get-Service KhadangRouter).Status.ToString() -ne 'Running' -or
 (Get-FileHash 'C:\ProgramData\KhadangRouter\config.json').Hash -ne '653FD4D37637BEA5ED8C88BF063A1669D5A0DCA5E3B6BDD795189D151A2FD2EC' -or
 -not (Get-Acl $root).AreAccessRulesProtected -or (Get-Item -LiteralPath $root).Attributes -band [IO.FileAttributes]::ReparsePoint){
 throw 'Protected diagnostic root and unchanged running router required'
}
if((Test-Path -LiteralPath $release) -or (Test-Path -LiteralPath $workspace) -or
 (Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue)){throw 'Prior fixture exists; inspect, never replay/overwrite'}
if((Get-Item -LiteralPath $Archive).Attributes -band [IO.FileAttributes]::ReparsePoint -or
 (Get-FileHash -LiteralPath $Archive).Hash -ne $ExpectedSha256){throw 'Exact literal diagnostic archive digest required'}
[IO.Directory]::CreateDirectory($release)|Out-Null
Expand-Archive -LiteralPath $Archive -DestinationPath $release
$bin=Join-Path $release 'publish-broker';$exe=Join-Path $bin 'NativeBrokerProbe.exe'
$runtime=Get-Content (Join-Path $bin 'NativeBrokerProbe.runtimeconfig.json') -Raw|ConvertFrom-Json
if(-not (Test-Path $exe) -or -not (Test-Path (Join-Path $bin 'coreclr.dll')) -or
 -not ($runtime.runtimeOptions.includedFrameworks|Where-Object name -eq 'Microsoft.NETCore.App')){throw 'Self-contained fixture required'}
Get-ChildItem -LiteralPath $release -Recurse -Force|ForEach-Object{
 if($_.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Diagnostic reparse refused'}
 $acl=Get-Acl $_.FullName;$acl.SetOwner($admin);Set-Acl $_.FullName $acl
}
$inherit=[Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'
function Protect-Directory([string]$Path,[bool]$OwnerWrites){
 $acl=[Security.AccessControl.DirectorySecurity]::new();$acl.SetAccessRuleProtection($true,$false)
 $acl.SetOwner($(if($OwnerWrites){$owner}else{$admin}))
 foreach($sid in @($admin,$system)){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl',$inherit,'None','Allow'))}
 if($OwnerWrites){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($owner,'FullControl',$inherit,'None','Allow'))}
 else{$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($owner,'ReadAndExecute',$inherit,'None','Allow'))}
 Set-Acl -LiteralPath $Path $acl
}
Protect-Directory $release $false
$state=Join-Path $release 'state';[IO.Directory]::CreateDirectory($state)|Out-Null
# Runtime custody is SYSTEM/admin only, not the read-only fixture code ACL.
$acl=[Security.AccessControl.DirectorySecurity]::new();$acl.SetOwner($admin);$acl.SetAccessRuleProtection($true,$false)
foreach($sid in @($admin,$system)){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl',$inherit,'None','Allow'))}
Set-Acl -LiteralPath $state $acl
[IO.Directory]::CreateDirectory($workspace)|Out-Null;Protect-Directory $workspace $true
[IO.Directory]::CreateDirectory((Join-Path $workspace 'empty-native-home'))|Out-Null
& $exe --self-test
if($LASTEXITCODE -ne 0){throw 'Broker diagnostic method guards failed'}
& (Join-Path $bin 'KhadangRouter.exe') --self-test
if($LASTEXITCODE -ne 0){throw 'Actual Windows custody/router checks failed'}
$action=New-ScheduledTaskAction -Execute $exe -Argument ('--run '+$RunId) -WorkingDirectory $bin
$principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $task -Action $action -Principal $principal -Settings $settings|Out-Null
$scheduler=New-Object -ComObject Schedule.Service;$scheduler.Connect();$registered=$scheduler.GetFolder('\').GetTask($task)
$registered.SetSecurityDescriptor('O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)',0x10)
$security=[Security.AccessControl.RawSecurityDescriptor]::new($registered.GetSecurityDescriptor(7))
if($security.Owner.Value -ne $admin.Value -or -not ($security.ControlFlags -band [Security.AccessControl.ControlFlags]::DiscretionaryAclProtected)){
 throw 'Protected task owner/DACL required'
}
foreach($ace in $security.DiscretionaryAcl){if($ace.SecurityIdentifier.Value -notin @($admin.Value,$system.Value)){throw 'Untrusted diagnostic task grant'}}
[IO.File]::WriteAllText((Join-Path $release 'reviewed-run.json'),(@{run=$RunId;archiveSha256=$ExpectedSha256;task=$task;
 oneShot=$true;modelsStarted=$false;productionChanged=$false;nativeUsesOrdinaryOwner=$true} | ConvertTo-Json -Compress))
Start-ScheduledTask -TaskName $task
[Console]::WriteLine((@{task=$task;state=(Get-ScheduledTask -TaskName $task).State.ToString();result=(Join-Path $state 'result.json')}|ConvertTo-Json -Compress))
