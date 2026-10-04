param([Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RunId)
# Read-only Windows API exports to a NEW administrator/SYSTEM-only artifact.
# No installation, model, network request, credentials API, reboot, replay or
# restore. Mutable observations are not a coherent full-system backup.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
function New-SettingsAcl([bool]$Directory){
 $acl=$(if($Directory){[Security.AccessControl.DirectorySecurity]::new()}else{[Security.AccessControl.FileSecurity]::new()})
 $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'));$acl.SetAccessRuleProtection($true,$false)
 foreach($sid in @('S-1-5-18','S-1-5-32-544')){
  $identity=[Security.Principal.SecurityIdentifier]::new($sid)
  if($Directory){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($identity,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))}
  else{$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($identity,'FullControl','Allow'))}
 }
 return $acl
}
function Assert-SettingsParent([string]$Path){
 for($part=[IO.DirectoryInfo]::new($Path);$null -ne $part;$part=$part.Parent){if(-not $part.Exists -or ($part.Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Literal existing settings destination required'}}
 $acl=Get-Acl -LiteralPath $Path;$rules=@($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
 if(-not $acl.AreAccessRulesProtected -or $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne 'S-1-5-32-544' -or $rules.Count -ne 2 -or
  @($rules|Where-Object {$_.IdentityReference.Value -notin @('S-1-5-18','S-1-5-32-544') -or $_.AccessControlType -ne 'Allow'}).Count){throw 'Administrator/SYSTEM-only destination required'}
}
function Write-SettingsArtifact([string]$Directory,$Report){
 Assert-SettingsParent ([IO.Path]::GetDirectoryName($Directory))
 if(Test-Path -LiteralPath $Directory){throw 'Settings run already exists; never overwrite or replay'}
 [IO.Directory]::CreateDirectory($Directory,(New-SettingsAcl $true))|Out-Null
 $path=Join-Path $Directory 'settings.private.json'
 $bytes=[Text.UTF8Encoding]::new($false).GetBytes(($Report|ConvertTo-Json -Depth 16 -Compress))
 if($bytes.Length -gt 32MB){throw 'Settings artifact exceeds bound; retain generated directory'}
 $file=[IO.FileStream]::new($path,[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::None,65536,[IO.FileOptions]::None,(New-SettingsAcl $false))
 try{$file.Write($bytes,0,$bytes.Length);$file.Flush($true)}finally{$file.Dispose()}
 Assert-SettingsParent $Directory
 $hash=[BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($bytes)).Replace('-','').ToLowerInvariant()
 if((Get-FileHash -LiteralPath $path).Hash.ToLowerInvariant() -ne $hash){throw 'Independent settings readback hash mismatch'}
 return @{path=$path;bytes=$bytes.Length;sha256=$hash}
}
function Read-SettingsSection([string]$Name,[ScriptBlock]$Read){
 try{return [ordered]@{name=$Name;state='observed';data=(& $Read);errorType=$null}}
 catch{return [ordered]@{name=$Name;state='unavailable';data=$null;errorType=$_.Exception.GetType().Name}}
}
function Convert-SettingsValue([string]$Name,[string]$Kind,$Value){
 if($Name -eq 'DefaultPassword'){throw 'Never export a Winlogon password value'}
 if($Value -is [byte[]]){$Value=@{base64=[Convert]::ToBase64String($Value)}}
 return [ordered]@{name=$Name;kind=$Kind;value=$Value}
}
function Read-SettingsRegistry([ValidateSet('LocalMachine','CurrentUser')][string]$Hive,[string]$Path,[string[]]$OnlyValues){
 $root=$(if($Hive -eq 'LocalMachine'){[Microsoft.Win32.Registry]::LocalMachine}else{[Microsoft.Win32.Registry]::CurrentUser})
 $rows=[Collections.Generic.List[object]]::new();$pending=[Collections.Generic.Stack[string]]::new();$pending.Push($Path)
 while($pending.Count){
  if($rows.Count -ge 10000){throw 'Registry entry bound reached; section unavailable, not silently complete'}
  $current=$pending.Pop();$key=$root.OpenSubKey($current,$false)
  if(-not $key){if($current -eq $Path){return @{hive=$Hive;root=$Path;present=$false;entries=@()}};throw 'Registry key disappeared during export'}
  try{
   $values=@($key.GetValueNames()|Where-Object {-not $OnlyValues -or $_ -in $OnlyValues}|ForEach-Object {
    $kind=$key.GetValueKind($_).ToString();$value=$key.GetValue($_,$null,[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    Convert-SettingsValue $_ $kind $value
   })
   $rows.Add([ordered]@{path=$current;values=$values})
   if(-not $OnlyValues){foreach($child in $key.GetSubKeyNames()){$pending.Push($current+'\'+$child)}}
  }finally{$key.Dispose()}
 }
 return @{hive=$Hive;root=$Path;present=$true;entries=@($rows.ToArray())}
}
function Read-SettingsNative([string]$Exe,[string]$Arguments){
 $start=[Diagnostics.ProcessStartInfo]::new($Exe,$Arguments);$start.UseShellExecute=$false;$start.CreateNoWindow=$true
 $start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true;$child=[Diagnostics.Process]::Start($start)
 try{
  $out=$child.StandardOutput.ReadToEndAsync();$err=$child.StandardError.ReadToEndAsync()
  if(-not $child.WaitForExit(30000)){$child.Kill();$child.WaitForExit();throw 'Owned read-only command exceeded deadline'}
  $text=$out.GetAwaiter().GetResult();$errorText=$err.GetAwaiter().GetResult()
  if($child.ExitCode -ne 0 -or $errorText.Length -or $text.Length -gt 8MB){throw 'Bounded read-only command failed'}
  return $text
 }finally{$child.Dispose()}
}
function Convert-SettingsTime($Value){
 # Logon/event and completed one-shot tasks may have no next scheduled run.
 # Keep that absence explicit; never invent a timestamp or drop the task XML.
 if($null -eq $Value){return $null}
 if($Value -isnot [DateTime] -and $Value -isnot [DateTimeOffset]){throw 'Unsupported task timestamp type'}
 return $Value.ToString('o',[Globalization.CultureInfo]::InvariantCulture)
}
function Get-SettingsSummary($Report,$Artifact){
 return [ordered]@{schema=$Report.schema;at=$Report.finishedAt;run=$Report.run;artifact=$Artifact.path;bytes=$Artifact.bytes;sha256=$Artifact.sha256;
  sections=@($Report.sections|ForEach-Object {@{name=$_.name;state=$_.state;errorType=$_.errorType}});
  allSelectedSectionsObserved=(@($Report.sections|Where-Object state -ne 'observed').Count -eq 0);
  liveConfigurationChanged=$false;credentialsApiUsed=$false;modelsStarted=$false;writersFrozen=$false;fullSystemBackup=$false;encrypted=$false;restoreActivated=$false}
}
$identity=[Security.Principal.WindowsIdentity]::GetCurrent();$principal=[Security.Principal.WindowsPrincipal]::new($identity)
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Exact PC administrator settings export required'}
$parent='C:\ProgramData\OracovaMigration';Assert-SettingsParent $parent
$target=Join-Path $parent $RunId;if(Test-Path -LiteralPath $target){throw 'Settings run already exists; inspect instead of replaying'}
$started=[DateTime]::UtcNow.ToString('o');$sections=[Collections.Generic.List[object]]::new()
$serviceNames=@('KhadangRouter','MagicRemoteBridge','OracovaVPN','OracovaVPNState','OracovaMTProto','OracovaMTProto8443','OracovaCloudflare','OracovaCloudflareFallback','sshd','WSLService')
$sections.Add((Read-SettingsSection 'services' {
 $found=@(Get-CimInstance Win32_Service|Where-Object {$_.Name -in $serviceNames})
 if(@($serviceNames|Where-Object {$_ -notin $found.Name}).Count){throw 'Required operational service absent'}
 @($found|ForEach-Object {$svc=Get-Service -Name $_.Name;[ordered]@{name=$_.Name;displayName=$_.DisplayName;pathName=$_.PathName;startName=$_.StartName;startMode=$_.StartMode;
  state=$_.State;dependencies=@($svc.ServicesDependedOn.Name);registry=(Read-SettingsRegistry LocalMachine ('SYSTEM\CurrentControlSet\Services\'+$_.Name))}})
}))
$sections.Add((Read-SettingsSection 'tasks' {
 $found=@(Get-ScheduledTask|Where-Object {$_.TaskName -like 'Oracova-*' -or $_.TaskName -like 'MagicRemoteBridge*'})
 if($found.Count -gt 200){throw 'Task export bound reached'}
 foreach($required in @('Oracova-KhadangStartup','Oracova-CodexWslRemote','Oracova-CodexRemote','Oracova-ClaudeRemote')){if($required -notin $found.TaskName){throw 'Required recovery task absent'}}
 @($found|ForEach-Object { $info=Get-ScheduledTaskInfo -InputObject $_;[ordered]@{name=$_.TaskName;path=$_.TaskPath;xml=(Export-ScheduledTask -InputObject $_);
  state=$_.State.ToString();lastResult=$info.LastTaskResult;lastRun=(Convert-SettingsTime $info.LastRunTime);nextRun=(Convert-SettingsTime $info.NextRunTime)}})
}))
$sections.Add((Read-SettingsSection 'firewall-policy' {Read-SettingsRegistry LocalMachine 'SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy'}))
$sections.Add((Read-SettingsSection 'windows-update-policy' {Read-SettingsRegistry LocalMachine 'SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate'}))
$sections.Add((Read-SettingsSection 'winlogon-nonsecret' {Read-SettingsRegistry LocalMachine 'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' @('AutoAdminLogon','DefaultUserName','DefaultDomainName','AutoLogonCount','ForceAutoLogon','Userinit','Shell')}))
$sections.Add((Read-SettingsSection 'owner-wsl-registration' {Read-SettingsRegistry CurrentUser 'Software\Microsoft\Windows\CurrentVersion\Lxss'}))
$sections.Add((Read-SettingsSection 'power-settings' {Read-SettingsNative 'C:\Windows\System32\powercfg.exe' '/query'}))
$sections.Add((Read-SettingsSection 'power-capabilities' {Read-SettingsNative 'C:\Windows\System32\powercfg.exe' '/a'}))
$sections.Add((Read-SettingsSection 'network-adapters' {@(Get-NetAdapter|Select-Object Name,InterfaceDescription,InterfaceGuid,MacAddress,Status,HardwareInterface,DriverVersion)}))
$sections.Add((Read-SettingsSection 'adapter-advanced-settings' {@(Get-NetAdapterAdvancedProperty -AllProperties|Select-Object Name,RegistryKeyword,RegistryValue,DisplayName,DisplayValue)}))
$sections.Add((Read-SettingsSection 'ip-settings' {@(Get-NetIPConfiguration -All|Select-Object InterfaceAlias,InterfaceIndex,IPv4Address,IPv6Address,IPv4DefaultGateway,IPv6DefaultGateway,DNSServer)}))
$sections.Add((Read-SettingsSection 'optional-features' {@(Get-WindowsOptionalFeature -Online|Select-Object FeatureName,State)}))
$report=[ordered]@{schema='ccrelay.pc_recovery_settings.v1';run=$RunId;host=$env:COMPUTERNAME;startedAt=$started;finishedAt=[DateTime]::UtcNow.ToString('o');
 mode='selected mutable read-only Windows API exports';liveConfigurationChanged=$false;credentialsApiUsed=$false;modelsStarted=$false;writersFrozen=$false;fullSystemBackup=$false;
 encrypted=$false;restoreActivated=$false;sections=@($sections.ToArray());
 unresolved=@('Task/service passwords and LSA/DPAPI portable recovery or re-login','Files, worktrees, SQLite/native/action-ledger consistency','Registry links, complete byte/name representation and ACL/driver closure',
  'WSL disk consistency and Linux configuration','BIOS/UEFI/BitLocker/AC-restore behavior','Encryption, off-machine custody and clean-machine restore')}
$artifact=Write-SettingsArtifact $target $report
[Console]::WriteLine(((Get-SettingsSummary $report $artifact)|ConvertTo-Json -Depth 6 -Compress))
