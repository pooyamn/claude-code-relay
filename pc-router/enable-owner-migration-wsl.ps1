param([Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RunId)
# Personal migration distro only, not a role/company security boundary.
# Preserve existing grants and save rollback before permitting normal owner entry.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=[Security.Principal.WindowsPrincipal]::new($identity)
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$base='C:\ProgramData\OracovaWSL\Ubuntu2404';$disk=Join-Path $base 'ext4.vhdx'
$entries=@(Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'|ForEach-Object {Get-ItemProperty $_.PSPath}|Where-Object {$_.DistributionName -eq 'Ubuntu-24.04'})
if($entries.Count -ne 1 -or ([string]$entries[0].BasePath).Trim([char]0) -ne $base){throw 'Exact owner-registered migration distro required'}
foreach($path in @($base,$disk)){if((Get-Item $path).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Literal non-reparse distro paths required'}}
$parent='C:\ProgramData\OracovaNativeRemote'
if((Get-Acl $parent).Owner -ne 'BUILTIN\Administrators' -or -not (Get-Acl $parent).AreAccessRulesProtected){throw 'Protected rollback root required'}
$before=@{base=$base;directorySddl=(Get-Acl $base).Sddl;diskSddl=(Get-Acl $disk).Sddl;at=[DateTime]::UtcNow.ToString('o');companyBoundary=$false}
$acl=[Security.AccessControl.FileSecurity]::new();$acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'));$acl.SetAccessRuleProtection($true,$false)
foreach($sid in @('S-1-5-18','S-1-5-32-544')){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','Allow'))}
$receipt=Join-Path $parent ('migration-wsl-acl-before-'+$RunId+'.json')
$f=[IO.FileStream]::new($receipt,[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::None,4096,[IO.FileOptions]::None,$acl)
try{$b=[Text.Encoding]::UTF8.GetBytes(($before|ConvertTo-Json -Compress));$f.Write($b,0,$b.Length)}finally{$f.Dispose()}
$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
$directoryAcl=Get-Acl $base
$directoryAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($owner,'Modify','ContainerInherit,ObjectInherit','None','Allow'))
Set-Acl $base $directoryAcl
@{personalDistro='Ubuntu-24.04';ownerAccess='Modify';scope=$base;rollback=$receipt;modelsStarted=$false;routerCredentialAclChanged=$false}|ConvertTo-Json -Compress
