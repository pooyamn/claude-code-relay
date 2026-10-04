param(
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RunId,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedSha256,
 [ValidateSet('probe','create-web','create-base','create-marginal')][string]$Mode='probe',
 [ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedPolicySha256='653FD4D37637BEA5ED8C88BF063A1669D5A0DCA5E3B6BDD795189D151A2FD2EC'
)
# Stage only reviewed diagnostic bytes. Preserve live router/bindings/remotes.
# SYSTEM owns the deterministic launcher; all native execution is limited pou.
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
$archive=Join-Path $root ('managed-probe-'+$RunId+'.zip')
$release=Join-Path $root ('codex-connector-'+$RunId)
$task='Oracova-ManagedCodexProof-'+$RunId
$acl=Get-Acl -LiteralPath $root
if(-not $acl.AreAccessRulesProtected -or $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $admin.Value -or
 (Get-Item -LiteralPath $root).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Protected literal code root required'}
if((Get-Service KhadangRouter).Status.ToString() -ne 'Running' -or
 (Get-FileHash 'C:\ProgramData\KhadangRouter\config.json').Hash -ne $ExpectedPolicySha256){
 throw 'Unchanged running production router required'
}
if((Test-Path -LiteralPath $release) -or (Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue)){
 throw 'Prior attempt exists; inspect, never replay'
}
function Protect([string]$Path,[bool]$Directory){
 if($Directory){$a=[Security.AccessControl.DirectorySecurity]::new();$inherit=[Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'}
 else{$a=[Security.AccessControl.FileSecurity]::new();$inherit=[Security.AccessControl.InheritanceFlags]::None}
 $a.SetOwner($admin);$a.SetAccessRuleProtection($true,$false)
 foreach($sid in @($admin,$system)){$a.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl',$inherit,'None','Allow'))}
 $a.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($owner,'ReadAndExecute',$inherit,'None','Allow'))
 Set-Acl -LiteralPath $Path $a
}
if((Get-Item -LiteralPath $archive).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Literal reviewed archive required'}
Protect $archive $false
if((Get-FileHash -LiteralPath $archive).Hash -ne $ExpectedSha256){throw 'Archive digest differs'}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip=[IO.Compression.ZipFile]::OpenRead($archive)
try{
 $names=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
 foreach($entry in $zip.Entries){
  if($entry.FullName.EndsWith('/')){
   if($entry.FullName -notin @('relay_core/','publish/')){throw 'Unexpected archive directory'}
   continue
  }
  if($entry.FullName -notmatch '^(pc_native_stdio\.py|relay_core/(__init__|contracts|identity|native_rpc|native_ws)\.py|publish/[A-Za-z0-9._-]+)$' -or
   -not $names.Add($entry.FullName) -or $entry.Length -gt 300000000){throw 'Unexpected/duplicate/oversized archive member'}
 }
 [IO.Directory]::CreateDirectory($release)|Out-Null;Protect $release $true
 Expand-Archive -LiteralPath $archive -DestinationPath $release
 foreach($item in @(Get-ChildItem -LiteralPath $release -Recurse -Force)){
  if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Diagnostic reparse refused'}
  Protect $item.FullName $item.PSIsContainer
 }
 foreach($entry in $zip.Entries){
  if($entry.FullName.EndsWith('/')){continue}
  $stream=$entry.Open();$sha=[Security.Cryptography.SHA256]::Create()
  try{$hash=([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','')}
  finally{$stream.Dispose();$sha.Dispose()}
  if((Get-FileHash -LiteralPath (Join-Path $release $entry.FullName)).Hash -ne $hash){throw 'Sealed bytes differ'}
 }
 if(@(Get-ChildItem -LiteralPath $release -Recurse -File).Count -ne $names.Count){throw 'Unexpected extracted file'}
}finally{$zip.Dispose()}
$files=@{}
foreach($name in @('pc_native_stdio.py','relay_core/__init__.py','relay_core/contracts.py','relay_core/identity.py','relay_core/native_rpc.py','relay_core/native_ws.py')){
 $files[$name]=(Get-FileHash -LiteralPath (Join-Path $release $name)).Hash
}
$policy=Get-Content 'C:\ProgramData\KhadangRouter\config.json' -Raw|ConvertFrom-Json
$policy.StateDirectory=Join-Path $release 'proof'
$policy|Add-Member LinuxWorkspaceRoot '/Users/pouya/.openclaw/workspace' -Force
$policy|Add-Member LinuxCodex (@{PackageRoot=$release;WslSha256=(Get-FileHash 'C:\Windows\System32\wsl.exe').Hash;FileSha256=$files}) -Force
$config=Join-Path $release 'reviewed-policy.json'
[IO.File]::WriteAllText($config,($policy|ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false));Protect $config $false
$bin=Join-Path $release 'publish';$exe=Join-Path $bin 'ManagedCodexProbe.exe'
$runtime=Get-Content (Join-Path $bin 'ManagedCodexProbe.runtimeconfig.json') -Raw|ConvertFrom-Json
if(-not (Test-Path (Join-Path $bin 'coreclr.dll')) -or
 -not ($runtime.runtimeOptions.includedFrameworks|Where-Object name -eq 'Microsoft.NETCore.App')){throw 'Self-contained Windows runtime required'}
& $exe --self-test
if($LASTEXITCODE -ne 0){throw 'Fixed observation method guards failed'}
$flag=switch($Mode){'create-web'{'--create-web'}'create-base'{'--create-base'}'create-marginal'{'--create-marginal'}default{'--run'}}
$action=New-ScheduledTaskAction -Execute $exe -Argument ($flag+' '+$RunId) -WorkingDirectory $bin
$principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $task -Action $action -Principal $principal -Settings $settings|Out-Null
$scheduler=New-Object -ComObject Schedule.Service;$scheduler.Connect();$registered=$scheduler.GetFolder('\').GetTask($task)
$registered.SetSecurityDescriptor('O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)',0x10)
$security=[Security.AccessControl.RawSecurityDescriptor]::new($registered.GetSecurityDescriptor(7))
if($security.Owner.Value -ne $admin.Value -or -not ($security.ControlFlags -band [Security.AccessControl.ControlFlags]::DiscretionaryAclProtected)){
 throw 'Protected task owner/DACL required'
}
foreach($ace in $security.DiscretionaryAcl){if($ace.SecurityIdentifier.Value -notin @($admin.Value,$system.Value)){throw 'Untrusted task grant'}}
Start-ScheduledTask -TaskName $task
[Console]::WriteLine((@{task=$task;state=[string](Get-ScheduledTask -TaskName $task).State;
 result=(Join-Path $release 'proof\result.json');oneShot=$true;productionChanged=$false;mode=$Mode}|ConvertTo-Json -Compress))
