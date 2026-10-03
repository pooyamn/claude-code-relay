param([switch]$WriteReport,[ValidateRange(100,200000)][int]$MaximumEntries=100000)
# Metadata inventory ONLY, not a snapshot, backup policy, source freeze or restore
# grant. No secret contents, provider API, process/service/task mutations, network,
# source writes, encryption or decryption. Full paths/ACLs remain in a private report.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
Add-Type @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class RecoveryFileMetadata {
 [StructLayout(LayoutKind.Sequential)] public struct Info {
  public uint Attributes; public System.Runtime.InteropServices.ComTypes.FILETIME Created,Accessed,Written;
  public uint Volume,SizeHigh,SizeLow,Links,IndexHigh,IndexLow;
 }
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern SafeFileHandle CreateFileW(string name,uint access,uint share,IntPtr security,uint creation,uint flags,IntPtr template);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool GetFileInformationByHandle(SafeFileHandle file,out Info info);
 public static Info Read(string path) {
  // FILE_READ_ATTRIBUTES, all sharing, OPEN_EXISTING, BACKUP_SEMANTICS |
  // OPEN_REPARSE_POINT. Never request FILE_READ_DATA or open a link's target.
  using(var file=CreateFileW(path,0x80,7,IntPtr.Zero,3,0x02200000,IntPtr.Zero)) {
   if(file.IsInvalid)throw new Win32Exception(Marshal.GetLastWin32Error());
   Info result;if(!GetFileInformationByHandle(file,out result))throw new Win32Exception(Marshal.GetLastWin32Error());return result;
  }
 }
 public static string LiteralPath(string path) {
  // Preserve UTF-16 code units, including unpaired surrogates; JSON display text
  // is not an extraction pathname and replacement fallback must not lose names.
  var bytes=new byte[path.Length*2];Buffer.BlockCopy(path.ToCharArray(),0,bytes,0,bytes.Length);return Convert.ToBase64String(bytes);
 }
}
'@
function Get-RecoveryKind([string]$Path,[bool]$Directory,[bool]$Reparse){
 if($Reparse){return 'reparse-unresolved'}
 if($Directory){return 'directory'}
 if($Path -match '\.(?:db|sqlite)(?:-[A-Za-z0-9]+)?-(?:wal|shm)$'){return 'sqlite-sidecar'}
 if($Path -match '\.(?:db|sqlite)$'){return 'sqlite-candidate'}
 if([IO.Path]::GetFileName($Path) -eq 'one-shot.claim'){return 'persistent-action-deduplication'}
 if($Path -in @('C:\ProgramData\KhadangRouter\state\exclusive.lock','C:\Users\pou\.codex\.sqlite-maintenance.lock')){return 'runtime-ownership-not-restore-authority'}
 return 'file'
}
function Get-RecoveryComponent([string]$Id,[string]$Path,[bool]$Required,[int]$Limit){
 $rows=[Collections.Generic.List[object]]::new();$issues=[Collections.Generic.List[object]]::new()
 $present=Test-Path -LiteralPath $Path
 if(-not $present){return [ordered]@{id=$Id;root=$Path;required=$Required;present=$false;enumerationFinished=$false;entries=@();issues=@('Absent');bytes=[long]0}}
 $base=[IO.Path]::GetFullPath($Path).TrimEnd('\');$pending=[Collections.Generic.Stack[string]]::new();$pending.Push($base)
 [long]$bytes=0
 while($pending.Count){
  $current=$pending.Pop()
  if($rows.Count -ge $Limit){$issues.Add(@{kind='EntryBoundReached';remaining=$pending.Count+1});break}
  try{
   # Ancestor replacement is NOT fenced by this diagnostic. Handle metadata and
   # no-follow final entries help discover aliases, not certify coherent sources.
   $meta=[RecoveryFileMetadata]::Read($current)
   $directory=($meta.Attributes -band 16) -ne 0;$reparse=($meta.Attributes -band 1024) -ne 0
   $relative=$(if($current -eq $base){'.'}else{$current.Substring($base.Length+1)})
   $kind=Get-RecoveryKind $current $directory $reparse
   $size=([long]$meta.SizeHigh -shl 32) -bor [long]$meta.SizeLow
   $sddl=$null
   if(-not $reparse){try{$sddl=(Get-Acl -LiteralPath $current).Sddl}catch{$issues.Add(@{kind='AclUnavailable';pathUtf16=[RecoveryFileMetadata]::LiteralPath($relative)})}}
   $rows.Add([ordered]@{relativeDisplay=$relative;relativeUtf16=[RecoveryFileMetadata]::LiteralPath($relative);kind=$kind;attributes=$meta.Attributes;
    bytes=$size;fileIdentity=('{0:X8}:{1:X8}{2:X8}' -f $meta.Volume,$meta.IndexHigh,$meta.IndexLow);linkCount=$meta.Links;sddl=$sddl})
   if($reparse){$issues.Add(@{kind='ReparseRepresentationRequired';pathUtf16=[RecoveryFileMetadata]::LiteralPath($relative)});continue}
   if($directory){foreach($child in ([IO.DirectoryInfo]::new($current)).GetFileSystemInfos()){$pending.Push($child.FullName)}}else{$bytes+=$size}
  }catch{$issues.Add(@{kind='MetadataUnavailable';pathUtf16=[RecoveryFileMetadata]::LiteralPath($current);errorType=$_.Exception.GetType().Name})}
 }
 [ordered]@{id=$Id;root=$base;rootUtf16=[RecoveryFileMetadata]::LiteralPath($base);required=$Required;present=$true;
  enumerationFinished=($issues.Count -eq 0);entries=@($rows.ToArray());issues=@($issues.ToArray());bytes=$bytes}
}
function New-RecoveryPrivateDirectory([string]$Path){
 for($part=[IO.DirectoryInfo]::new([IO.Path]::GetDirectoryName($Path));$null -ne $part;$part=$part.Parent){
  if(-not $part.Exists -or ($part.Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Protected inventory destination ancestor absent/reparse'}
 }
 if(Test-Path -LiteralPath $Path){throw 'Inventory destination already exists; never overwrite'}
 $acl=[Security.AccessControl.DirectorySecurity]::new();$acl.SetAccessRuleProtection($true,$false)
 $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
 foreach($sid in @('S-1-5-18','S-1-5-32-544')){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','ContainerInherit,ObjectInherit','None','Allow'))}
 [IO.Directory]::CreateDirectory($Path,$acl) | Out-Null
}
function Get-RecoverySummary($Report){
 [ordered]@{schema=$Report.schema;at=$Report.finishedAt;host=$Report.host;mode=$Report.mode;inventoryOnly=$true;sourceWrites=$false;
  fullSystemBackup=$false;writersFrozen=$false;encrypted=$false;restoreMode='paused';reportDirectory=$Report.reportDirectory;
  components=@($Report.components | ForEach-Object {[ordered]@{id=$_.id;present=$_.present;required=$_.required;entries=@($_.entries).Count;bytes=$_.bytes;enumerationFinished=$_.enumerationFinished;issues=@($_.issues).Count}});
  sqliteCandidates=@($Report.components | ForEach-Object {$_.entries} | Where-Object kind -eq 'sqlite-candidate').Count;
  machineBoundRecoveryResolved=$false;dailyOffMachineBackupVerified=$false;requiredApiSources=$Report.requiredApiSources}
}
function Get-RecoverySources([string]$ProgramData){
 $sources=[Collections.Generic.List[object]]::new()
 $fixed=@(
 @('native-codex','C:\Users\pou\.codex',$true),@('native-claude','C:\Users\pou\.claude',$true),
 @('claude-global','C:\Users\pou\.claude.json',$true),@('native-remote-observations','C:\Users\pou\.native-remote',$true),
 @('workspaces-full-git-dirty-and-ignored','C:\Users\pou\workspaces',$true),
 @('github-cli','C:\Users\pou\AppData\Roaming\GitHub CLI',$true),@('github-user-config','C:\Users\pou\.gitconfig',$false),
 @('owner-ssh','C:\Users\pou\.ssh',$false),@('host-ssh','C:\ProgramData\ssh',$true),
 @('native-codex-installed-code','C:\Users\pou\AppData\Local\Programs\OpenAI\Codex',$true),
 @('native-claude-installed-code','C:\Users\pou\.local\bin\claude.exe',$true),
 @('owner-dpapi-masterkeys','C:\Users\pou\AppData\Roaming\Microsoft\Protect',$true),
 @('owner-credential-store-roaming','C:\Users\pou\AppData\Roaming\Microsoft\Credentials',$false),
 @('owner-credential-store-local','C:\Users\pou\AppData\Local\Microsoft\Credentials',$false),
 @('owner-vault-local','C:\Users\pou\AppData\Local\Microsoft\Vault',$false),
 @('owner-vault-roaming','C:\Users\pou\AppData\Roaming\Microsoft\Vault',$false),
 @('owner-crypto-keys','C:\Users\pou\AppData\Roaming\Microsoft\Crypto',$false),
 @('machine-crypto-keys','C:\ProgramData\Microsoft\Crypto',$false),
 @('machine-dpapi-masterkeys','C:\Windows\System32\Microsoft\Protect',$true),
 @('router-all-state-code-credentials-rollback','C:\ProgramData\KhadangRouter',$true),
 @('lg-service-all-state-code-config','C:\ProgramData\MagicRemoteBridge',$true))
 foreach($row in $fixed){$sources.Add([pscustomobject]@{id=$row[0];path=$row[1];required=[bool]$row[2]})}
 foreach($folder in Get-ChildItem -LiteralPath $ProgramData -Directory -Force | Where-Object Name -like 'Oracova*'){
  # Named fields avoid PowerShell's expression-list '+' precedence flattening
  # the dynamic tuple into one string and losing its path/required flag.
  $sources.Add([pscustomobject]@{id=('oracova-'+$folder.Name);path=$folder.FullName;required=$true})
 }
 return $sources.ToArray()
}
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=[Security.Principal.WindowsPrincipal]::new($identity)
if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed administrator metadata inventory required; never invoke through a model tool'}
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK'){throw 'Inventory target host mismatch'}
$started=[DateTime]::UtcNow.ToString('o');$components=[Collections.Generic.List[object]]::new();$used=0
foreach($source in (Get-RecoverySources 'C:\ProgramData')){
 if($used -ge $MaximumEntries){throw 'Whole-inventory entry bound reached; no report published'}
 $component=Get-RecoveryComponent $source.id $source.path $source.required ($MaximumEntries-$used)
 $used+=@($component.entries).Count;$components.Add($component)
}
$apiSources=@(
 'SCM service definitions, dependencies, failure/startup policy and protected credentials (not exported)',
 'Scheduled task XML, principals/triggers/settings/actions (not exported; may contain secrets)',
 'Firewall, power, Windows features and driver/USB/network configuration (not exported)',
 'LSA auto-login/DPAPI_SYSTEM and Credential Manager trusted portable recovery or explicit re-login (not accessed)',
 'Boot/UEFI/BitLocker and private VM/WSL registration/disk consistency (not certified)',
 'Company/role memories, registry and admission/export bindings once protected role hosting is selected')
$report=[ordered]@{schema='ccrelay.pc_recovery_candidate_inventory.v1';host=$env:COMPUTERNAME;mode='metadata-only';startedAt=$started;finishedAt=[DateTime]::UtcNow.ToString('o');
 authoritativeBackupPolicy=$false;sourceContentsRead=$false;sourceWrites=$false;writersFrozen=$false;fullSystemBackup=$false;encrypted=$false;restoreMode='paused';
 reportDirectory=$null;components=@($components.ToArray());requiredApiSources=$apiSources;
 sourceConsistency='Mutable-source diagnostic, not a writer fence, snapshot, current runtime/SQLite binding, freshness or restore authorization';
 nativeFilesystemLimitations=@('Reparse payloads unresolved','Alternate streams not inventoried','Hardlink identities/counts observed, complete alias closure unverified','Security audit SACL not captured');
 fileIdentityScope='Volume serial plus 64-bit file index; not guaranteed unique on ReFS or reusable as current restore authority';
 bytesAreLogicalPerPath=$true;
 liveConfigurationChanged=$false;modelsStarted=$false;liveProcessesRestarted=$false;networkAccess=$false}
if($WriteReport){
 $path='C:\ProgramData\KhadangRouter\state\recovery-inventory-'+[Guid]::NewGuid().ToString('N')
 New-RecoveryPrivateDirectory $path;$report.reportDirectory=$path
 $target=Join-Path $path 'candidate-inventory.json'
 $bytes=[Text.UTF8Encoding]::new($false).GetBytes(($report | ConvertTo-Json -Depth 12 -Compress))
 $file=[IO.File]::Open($target,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
 try{$file.Write($bytes,0,$bytes.Length);$file.Flush($true)}finally{$file.Dispose()}
}
[Console]::WriteLine(((Get-RecoverySummary $report) | ConvertTo-Json -Depth 7 -Compress))
