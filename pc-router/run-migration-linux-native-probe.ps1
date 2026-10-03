param(
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RunId,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedSha256
)
# Administrator seals diagnostic code only. Native/tools execute as the exact
# Interactive/Limited Windows owner -> explicit WSL pou, in fresh empty state.
# No production deployment, Telegram polling, owner auth/history or model turn.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or
 -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
 throw 'Exact administrator diagnostic installer required'
}
$root='C:\ProgramData\OracovaNativeRemote'
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
$archive=Join-Path $root ('migration-linux-transport-'+$RunId+'.zip')
$release=Join-Path $root ('migration-linux-transport-'+$RunId)
$state=Join-Path 'C:\Users\pou\.native-remote' ('migration-linux-transport-'+$RunId)
$task='Oracova-MigrationLinuxTransport-'+$RunId
$rootAcl=Get-Acl -LiteralPath $root
if(-not $rootAcl.AreAccessRulesProtected -or $rootAcl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $admin.Value -or
 (Get-Item -LiteralPath $root).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Protected literal administrator code root required'}
if((Get-Service KhadangRouter).Status.ToString() -ne 'Running' -or
 (Get-FileHash 'C:\ProgramData\KhadangRouter\config.json').Hash -ne '653FD4D37637BEA5ED8C88BF063A1669D5A0DCA5E3B6BDD795189D151A2FD2EC'){
 throw 'Unchanged running production router required'
}
if((Test-Path -LiteralPath $release) -or (Test-Path -LiteralPath $state) -or
 (Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue)){throw 'Prior attempt exists; inspect, never replay/overwrite'}
function Protect-Code([string]$Path,[bool]$Directory){
 if($Directory){$acl=[Security.AccessControl.DirectorySecurity]::new();$inherit=[Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'}
 else{$acl=[Security.AccessControl.FileSecurity]::new();$inherit=[Security.AccessControl.InheritanceFlags]::None}
 $acl.SetOwner($admin);$acl.SetAccessRuleProtection($true,$false)
 foreach($sid in @($admin,$system)){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl',$inherit,'None','Allow'))}
 $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($owner,'ReadAndExecute',$inherit,'None','Allow'))
 Set-Acl -LiteralPath $Path $acl
}
if((Get-Item -LiteralPath $archive).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Literal diagnostic archive required'}
Protect-Code $archive $false
if((Get-FileHash -LiteralPath $archive).Hash -ne $ExpectedSha256){throw 'Reviewed archive digest differs'}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip=[IO.Compression.ZipFile]::OpenRead($archive)
try{
 $names=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
 foreach($entry in $zip.Entries){
  if($entry.FullName.EndsWith('/')){
   if($entry.FullName -notin @('relay_core/','publish/')){throw 'Unexpected archive directory'}
   continue
  }
  if($entry.FullName -notmatch '^(pc_native_stdio\.py|check-pc-native-transport\.py|relay_core/(__init__|contracts|identity|native_rpc|native_ws)\.py|publish/[A-Za-z0-9._-]+)$' -or
   -not $names.Add($entry.FullName) -or $entry.Length -gt 300000000){throw 'Unexpected/duplicate/oversized diagnostic entry'}
 }
 [IO.Directory]::CreateDirectory($release)|Out-Null;Protect-Code $release $true
 Expand-Archive -LiteralPath $archive -DestinationPath $release
 foreach($item in @(Get-ChildItem -LiteralPath $release -Recurse -Force)){
  if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Diagnostic reparse refused'}
  Protect-Code $item.FullName $item.PSIsContainer
 }
 foreach($entry in $zip.Entries){
  if($entry.FullName.EndsWith('/')){continue}
  $stream=$entry.Open();$sha=[Security.Cryptography.SHA256]::Create()
  try{$hash=([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','')}
  finally{$stream.Dispose();$sha.Dispose()}
  $path=Join-Path $release $entry.FullName
  if((Get-FileHash -LiteralPath $path).Hash -ne $hash){throw 'Sealed extracted bytes differ'}
 }
 if(@(Get-ChildItem -LiteralPath $release -Recurse -File).Count -ne $names.Count){throw 'Unexpected extracted file'}
}finally{$zip.Dispose()}
$bin=Join-Path $release 'publish';$exe=Join-Path $bin 'MigrationLinuxNativeProbe.exe'
if((Get-FileHash (Join-Path $bin 'KhadangRouter.dll')).Hash -ne '26FA0D60980E3CC834178BFaf5719CAFE9FDF9825A6AD677D3FCBFED06407959'){
 throw 'Frozen router DLL changed; no diagnostic activation'
}
$runtime=Get-Content (Join-Path $bin 'MigrationLinuxNativeProbe.runtimeconfig.json') -Raw|ConvertFrom-Json
if(-not (Test-Path (Join-Path $bin 'coreclr.dll')) -or
 -not ($runtime.runtimeOptions.includedFrameworks|Where-Object name -eq 'Microsoft.NETCore.App')){throw 'Self-contained Windows diagnostic required'}
& $exe --self-test
if($LASTEXITCODE -ne 0){throw 'Diagnostic method guards failed'}
$action=New-ScheduledTaskAction -Execute $exe -Argument ('--run '+$RunId) -WorkingDirectory $bin
$principal=New-ScheduledTaskPrincipal -UserId $owner.Value -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $task -Action $action -Principal $principal -Settings $settings|Out-Null
$scheduler=New-Object -ComObject Schedule.Service;$scheduler.Connect();$registered=$scheduler.GetFolder('\').GetTask($task)
$registered.SetSecurityDescriptor('O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)',0x10)
$security=[Security.AccessControl.RawSecurityDescriptor]::new($registered.GetSecurityDescriptor(7))
if($security.Owner.Value -ne $admin.Value -or -not ($security.ControlFlags -band [Security.AccessControl.ControlFlags]::DiscretionaryAclProtected)){
 throw 'Protected task owner/DACL required'
}
foreach($ace in $security.DiscretionaryAcl){if($ace.SecurityIdentifier.Value -notin @($admin.Value,$system.Value)){throw 'Untrusted task grant'}}
[IO.File]::WriteAllText((Join-Path $release 'reviewed-run.json'),(@{run=$RunId;archiveSha256=$ExpectedSha256;task=$task;
 oneShot=$true;modelsStarted=$false;productionChanged=$false;nativeUsesOrdinaryOwner=$true}|ConvertTo-Json -Compress))
Start-ScheduledTask -TaskName $task
[Console]::WriteLine((@{task=$task;state=[string](Get-ScheduledTask -TaskName $task).State;result=(Join-Path $state 'result.json')}|ConvertTo-Json -Compress))
