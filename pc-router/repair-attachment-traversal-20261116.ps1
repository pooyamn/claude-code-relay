# Hot repair of the DrvFS ancestor lookup gap. No service restart, download,
# registry mutation, model prompt or inherited/private-file read permission.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$release='C:\ProgramData\OracovaNativeRemote\attachment-traversal-20261116'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Existing administrator maintenance connection required'}
$p=[IO.File]::ReadAllText("$root\config.json")|ConvertFrom-Json
if($p.OwnerId -ne 110123423 -or $p.OwnerSid -ne 'S-1-5-21-71459778-1164188569-2276148161-1001' -or $p.BotId -ne 8735489806){throw 'Exact existing owner/policy required'}
if(Test-Path $release){throw 'Existing repair receipt: inspect rather than overwrite'}
$paths=@($root,"$root\state")
$before=@()
foreach($path in $paths){
 $item=Get-Item -LiteralPath $path;$acl=Get-Acl -LiteralPath $path
 if($item.Attributes -band [IO.FileAttributes]::ReparsePoint -or -not $acl.AreAccessRulesProtected -or $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne 'S-1-5-32-544'){throw 'Literal administrator-protected ancestor required'}
 $before+=@{path=$path;sddl=$acl.Sddl}
}
New-Item -ItemType Directory $release|Out-Null;Set-Acl $release (Get-Acl 'C:\ProgramData\OracovaNativeRemote\topic-automation-20261013')
function SaveNew($path,$value){$bytes=[Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -InputObject $value -Depth 8 -Compress));$f=[IO.File]::Open($path,'CreateNew','Write','None');try{$f.Write($bytes,0,$bytes.Length);$f.Flush($true)}finally{$f.Dispose()}}
SaveNew "$release\before.json" @{ancestors=$before;policy=(Get-FileHash "$root\config.json").Hash;router=(Get-FileHash "$root\bin\KhadangRouter.dll").Hash;at=[DateTimeOffset]::UtcNow.ToString('o')}
$rights=[Security.AccessControl.FileSystemRights]::Traverse -bor [Security.AccessControl.FileSystemRights]::ReadAttributes
$owner=[Security.Principal.SecurityIdentifier]::new($p.OwnerSid)
foreach($path in $paths){
 $acl=Get-Acl -LiteralPath $path
 $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($owner,$rights,[Security.AccessControl.InheritanceFlags]::None,[Security.AccessControl.PropagationFlags]::None,[Security.AccessControl.AccessControlType]::Allow))
 Set-Acl -LiteralPath $path -AclObject $acl
 $after=Get-Acl -LiteralPath $path
 $grant=@($after.GetAccessRules($true,$false,[Security.Principal.SecurityIdentifier])|Where-Object {$_.IdentityReference.Value -eq $owner.Value -and $_.AccessControlType -eq 'Allow'})
 if($grant.Count -ne 1 -or $grant[0].InheritanceFlags -ne 'None' -or ($grant[0].FileSystemRights -band ([Security.AccessControl.FileSystemRights]::ReadData -bor [Security.AccessControl.FileSystemRights]::Write -bor [Security.AccessControl.FileSystemRights]::ChangePermissions -bor [Security.AccessControl.FileSystemRights]::TakeOwnership)) -ne 0){throw 'Grant must be ancestor lookup only; no list/read/write/inheritance'}
}
SaveNew "$release\applied.json" @{rights=[string]$rights;ancestors=$paths;inheritance='None';privateFilesUnchanged=$true;servicesRestarted=0;nativeInputsReplayed=0;at=[DateTimeOffset]::UtcNow.ToString('o')}
@{phase='ancestor-traversal-applied';rights=[string]$rights;privateFilesUnchanged=$true;restart=$false}|ConvertTo-Json -Compress
