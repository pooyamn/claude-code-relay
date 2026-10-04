param(
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RunId,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedSha256,
 [ValidateSet('handoff','continuity')][string]$Mode='handoff'
)
# Stage a fixed DUT native check alongside the live router. No polling/cutover.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
 throw 'Reviewed PC administrator installer required'
}
$root='C:\ProgramData\OracovaNativeRemote';$router='C:\ProgramData\KhadangRouter'
$archive=Join-Path $root ('dut-claude-probe-'+$RunId+'.zip')
$release=Join-Path $root ('claude-connector-'+$RunId)
$state=Join-Path $router ('dut-claude-acceptance-'+$RunId)
$task='Oracova-DutClaudeProof-'+$RunId
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
foreach($path in @($root,$router)){
 $a=Get-Acl $path
 if(-not $a.AreAccessRulesProtected -or $a.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $admin.Value -or
  ((Get-Item $path).Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Protected literal deployment roots required'}
}
if((Get-FileHash "$router\config.json").Hash -ne '7E77ACA790FC5786C9737C93E67855EE5967C7D36FE364D1F3A41F83C874364A' -or
 (Get-FileHash "$router\bin\KhadangRouter.dll").Hash -ne '84AB5DEA4B368980A0754FB64D23F2ABBE0F63DCADA6EAFDB1F752E1A37E5690' -or
 (Get-Service KhadangRouter).Status.ToString() -ne 'Running'){throw 'Unchanged live production required'}
if((Test-Path $release) -or (Test-Path $state) -or (Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue)){
 throw 'Existing attempt; inspect instead of replaying'
}
function Protect([string]$Path,[bool]$Directory,[bool]$Readable){
 if($Directory){$a=[Security.AccessControl.DirectorySecurity]::new();$inherit=[Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'}
 else{$a=[Security.AccessControl.FileSecurity]::new();$inherit=[Security.AccessControl.InheritanceFlags]::None}
 $a.SetOwner($admin);$a.SetAccessRuleProtection($true,$false)
 foreach($sid in @($admin,$system)){$a.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl',$inherit,'None','Allow'))}
 if($Readable){$a.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($owner,'ReadAndExecute',$inherit,'None','Allow'))}
 Set-Acl $Path $a
}
if((Get-Item $archive).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Literal archive required'}
Protect $archive $false $false
if((Get-FileHash $archive).Hash -ne $ExpectedSha256){throw 'Reviewed archive bytes differ'}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip=[IO.Compression.ZipFile]::OpenRead($archive)
try{
 $names=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
 foreach($entry in $zip.Entries){
  if($entry.FullName -notmatch '^(publish/[A-Za-z0-9._-]+|pc_(native|claude)_stdio\.py|relay_core/(__init__|contracts|identity|native_rpc|native_ws)\.py|handoff-7dc840b0-402f-451e-bc79-dadfb706d363\.json)$' -or
   $entry.Length -gt 300000000 -or -not $names.Add($entry.FullName)){throw 'Unexpected, duplicate or oversized archive entry'}
 }
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true $true
 Expand-Archive -LiteralPath $archive -DestinationPath $release
 foreach($item in @(Get-ChildItem $release -Recurse -Force)){
  if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Archive redirect refused'}
  Protect $item.FullName $item.PSIsContainer $true
 }
 foreach($entry in $zip.Entries){
  $stream=$entry.Open();$hash=[Security.Cryptography.SHA256]::Create()
  try{$digest=([BitConverter]::ToString($hash.ComputeHash($stream))).Replace('-','')}
  finally{$stream.Dispose();$hash.Dispose()}
  if((Get-FileHash (Join-Path $release $entry.FullName)).Hash -ne $digest){throw 'Sealed extracted bytes differ'}
 }
 if(@(Get-ChildItem $release -Recurse -File).Count -ne $names.Count){throw 'Unexpected extracted bytes'}
}finally{$zip.Dispose()}
$bin=Join-Path $release 'publish';$exe=Join-Path $bin 'DutClaudeProbe.exe'
if(-not (Test-Path $exe) -or (Get-FileHash "$bin\KhadangRouter.dll").Hash -ne
 '84AB5DEA4B368980A0754FB64D23F2ABBE0F63DCADA6EAFDB1F752E1A37E5690'){throw 'Actual current router assembly required'}
& $exe --self-test
if($LASTEXITCODE -ne 0){throw 'Acceptance evidence fixtures failed; no native launch'}
New-Item -ItemType Directory $state|Out-Null;Protect $state $true $false
$policy=Get-Content "$router\config.json" -Raw -Encoding UTF8|ConvertFrom-Json
$wslSha=$policy.LinuxCodex.WslSha256
if((Get-FileHash 'C:\Windows\System32\wsl.exe').Hash -ne $wslSha){throw 'Previously reviewed WSL image changed'}
$digests=[ordered]@{}
foreach($name in @('pc_claude_stdio.py','pc_native_stdio.py','relay_core/__init__.py','relay_core/contracts.py',
 'relay_core/identity.py','relay_core/native_rpc.py','relay_core/native_ws.py')){
 $digests[$name]=(Get-FileHash (Join-Path $release $name)).Hash.ToLowerInvariant()
}
$session='7dc840b0-402f-451e-bc79-dadfb706d363';$checkpoint=Join-Path $release ('handoff-'+$session+'.json')
$checkpoints=[ordered]@{};$checkpoints[$session]=[ordered]@{Chat=-1004395661179;Topic=53;
 Workspace='/Users/pouya/.openclaw/workspace/ai-hil/hardware/duts';Sha256=(Get-FileHash $checkpoint).Hash.ToLowerInvariant()}
$policy|Add-Member LinuxClaude ([ordered]@{PackageRoot=$release;WslSha256=$wslSha;
 FileSha256=$digests;Checkpoints=$checkpoints}) -Force
[IO.File]::WriteAllText((Join-Path $state 'candidate.json'),($policy|ConvertTo-Json -Depth 100),[Text.UTF8Encoding]::new($false))
$action=New-ScheduledTaskAction -Execute $exe -Argument ('--'+$Mode+' '+$RunId+' '+$RunId) -WorkingDirectory $bin
$principal=New-ScheduledTaskPrincipal -UserId $system.Value -LogonType ServiceAccount -RunLevel Highest
$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::FromMinutes(4)) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $task -Action $action -Principal $principal -Settings $settings|Out-Null
$scheduler=New-Object -ComObject Schedule.Service;$scheduler.Connect();$registered=$scheduler.GetFolder('\').GetTask($task)
$registered.SetSecurityDescriptor('O:BAG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)',0x10)
$security=[Security.AccessControl.RawSecurityDescriptor]::new($registered.GetSecurityDescriptor(7))
if($security.Owner.Value -ne $admin.Value -or -not ($security.ControlFlags -band [Security.AccessControl.ControlFlags]::DiscretionaryAclProtected)){throw 'Protected task required'}
foreach($ace in $security.DiscretionaryAcl){if($ace.SecurityIdentifier.Value -notin @($admin.Value,$system.Value)){throw 'Untrusted task grant'}}
$observed=Get-ScheduledTask -TaskName $task
if($observed.Principal.UserId -notin @('SYSTEM','NT AUTHORITY\SYSTEM','S-1-5-18') -or
 [string]$observed.Principal.LogonType -ne 'ServiceAccount' -or $observed.Triggers.Count -ne 0 -or
 $observed.Settings.RestartCount -ne 0 -or (Get-ScheduledTaskInfo $observed).LastTaskResult -ne 267011){throw 'Fresh one-shot SYSTEM checker required'}
Start-ScheduledTask -TaskName $task
[ordered]@{task=$task;state=[string](Get-ScheduledTask -TaskName $task).State;result=(Join-Path $state 'result.json');
 productionChanged=$false;modelPrompts=1;nativeUsesLimitedOwner=$true}|ConvertTo-Json -Compress
