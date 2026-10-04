param(
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RunId,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedSha256
)
# Replace the quarantined implementation, not restore or exclude it.
# Existing secrets/routes remain fixed. Only the two MTProto services and their
# existing TCP8443 program filter change; all old source/configs are retained.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$original='C:\ProgramData\OracovaVPN-20261003-FA9g4b'
$archive=Join-Path $original ('mtproto-replacement-'+$RunId+'.zip')
$release='C:\ProgramData\OracovaMTProto-'+$RunId
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=[Security.Principal.WindowsPrincipal]::new($identity)
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
 throw 'Reviewed PC administrator required'
}
if((Test-Path -LiteralPath $release) -or (Get-Item -LiteralPath $archive).Attributes -band [IO.FileAttributes]::ReparsePoint -or
 (Get-FileHash -LiteralPath $archive).Hash -ne $ExpectedSha256){throw 'New verified release required; never replay'}
if(-not (Get-Acl $original).AreAccessRulesProtected -or (Get-Acl $original).Owner -ne 'BUILTIN\Administrators'){
 throw 'Existing protected VPN root required'
}
$python=Join-Path $original 'python\python.exe'
$signature=Get-AuthenticodeSignature $python
if($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation'){
 throw 'Existing signed Python required'
}
$services=@(Get-CimInstance Win32_Service | Where-Object {$_.Name -in @('OracovaMTProto','OracovaMTProto8443')})
if($services.Count -ne 2 -or @($services|Where-Object {$_.StartName -ne 'NT AUTHORITY\LocalService' -or $_.PathName -notlike ('*'+$original+'\services\*')}).Count){
 throw 'Exact original LocalService MTProto services required'
}
$filter=Get-NetFirewallRule -Name OracovaMTProto-TCP8443 | Get-NetFirewallApplicationFilter
if($filter.Program -notlike ($original+'\bin\mtg\*\mtg.exe')){throw 'Original scoped firewall filter required'}
if(-not (Get-MpComputerStatus).RealTimeProtectionEnabled){throw 'Defender must remain enabled'}
[IO.Directory]::CreateDirectory($release)|Out-Null
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$service=[Security.Principal.SecurityIdentifier]::new('S-1-5-19')
$inherit=[Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'
$acl=[Security.AccessControl.DirectorySecurity]::new();$acl.SetOwner($admin);$acl.SetAccessRuleProtection($true,$false)
foreach($sid in @($admin,$system)){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl',$inherit,'None','Allow'))}
$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($service,'ReadAndExecute',$inherit,'None','Allow'))
Set-Acl -LiteralPath $release -AclObject $acl
Expand-Archive -LiteralPath $archive -DestinationPath $release
if((Get-FileHash (Join-Path $release 'pycryptodome.whl')).Hash -ne 'C75B52AACC6C0C260F204CBDD834F76EDC9FB0D8E0DA9FBF8352EF58202564E2'){
 throw 'Pinned official PyCryptodome wheel mismatch'
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::ExtractToDirectory((Join-Path $release 'pycryptodome.whl'),(Join-Path $release 'deps'))
[IO.Directory]::CreateDirectory((Join-Path $release 'logs'))|Out-Null
[IO.File]::WriteAllText((Join-Path $release 'rollback.json'),(@{originalServices=@($services|Select-Object Name,PathName,StartName,StartMode);
 originalFirewallProgram=$filter.Program;flaggedExecutableRestored=$false;defenderExceptionAdded=$false}|ConvertTo-Json -Depth 6))
& 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe' /nologo /target:exe /r:System.ServiceProcess.dll ('/out:'+(Join-Path $release 'ServiceHost.exe')) (Join-Path $release 'ServiceHost.cs')
if($LASTEXITCODE -ne 0){throw 'Native service-host compilation failed'}
& $python -I -B (Join-Path $release 'server.py') --prepare
if($LASTEXITCODE -ne 0){throw 'Private config conversion or accelerated crypto check failed'}
# Remove the installing owner's implicit WriteDAC from every executable/config.
Get-ChildItem -LiteralPath $release -Recurse -Force | ForEach-Object {$entryAcl=Get-Acl -LiteralPath $_.FullName;$entryAcl.SetOwner($admin);Set-Acl -LiteralPath $_.FullName -AclObject $entryAcl}
$logs=Join-Path $release 'logs';$logAcl=Get-Acl $logs
$logAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($service,'Modify',$inherit,'None','Allow'));Set-Acl $logs $logAcl
Start-MpScan -ScanType CustomScan -ScanPath $release
if(-not (Test-Path (Join-Path $release 'ServiceHost.exe')) -or -not (Test-Path (Join-Path $release 'upstream\mtprotoproxy.py'))){throw 'Prepared files unavailable after Defender scan'}
foreach($entry in $services){
 Stop-Service -Name $entry.Name
 $path='"'+(Join-Path $release 'ServiceHost.exe')+'" '+$entry.Name
 $changed=Invoke-CimMethod -InputObject (Get-CimInstance Win32_Service -Filter ('Name="'+$entry.Name+'"')) -MethodName Change -Arguments @{PathName=$path}
 if($changed.ReturnValue -ne 0){throw 'MTProto service path change failed'}
 & 'C:\Windows\System32\sc.exe' failure $entry.Name reset= 3600 actions= 'restart/10000/restart/30000/restart/60000'
 if($LASTEXITCODE -ne 0){throw 'Bounded service recovery configuration failed'}
 & 'C:\Windows\System32\sc.exe' config $entry.Name start= auto
 if($LASTEXITCODE -ne 0){throw 'Automatic startup configuration failed'}
 & 'C:\Windows\System32\sc.exe' failureflag $entry.Name 1
 if($LASTEXITCODE -ne 0){throw 'Non-crash failure recovery configuration failed'}
}
$filter|Set-NetFirewallApplicationFilter -Program $python | Out-Null
foreach($entry in $services){Start-Service -Name $entry.Name}
[IO.File]::WriteAllText((Join-Path $release 'installation.json'),(@{release=$release;sourceCommit='0614c35020943b2080c9bd27b5e6336270af389f';
 source='alexbers/mtprotoproxy';pycryptodome='3.23.0';services=@($services.Name);secretsChanged=$false;linksChanged=$false;
 flaggedExecutableRestored=$false;defenderExceptionAdded=$false;networkTestPassed=$false;installedAt=[DateTime]::UtcNow.ToString('o')}|ConvertTo-Json -Depth 5))
Get-CimInstance Win32_Service | Where-Object {$_.Name -in @('OracovaMTProto','OracovaMTProto8443')} | Select-Object Name,State,ProcessId,StartMode,StartName | ConvertTo-Json -Compress
