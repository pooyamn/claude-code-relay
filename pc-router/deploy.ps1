param(
    [Parameter(Mandatory=$true)][string]$Archive,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedSha256,
    [ValidateSet('probe','canary','live')][string]$Mode = 'probe'
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = 'C:\ProgramData\KhadangRouter'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator-reviewed deployment only; never invoke from an agent' }
$service = Get-CimInstance Win32_Service | Where-Object Name -eq 'KhadangRouter'
if (-not $service -or $service.StartName -ne 'LocalSystem' -or -not $service.PathName.StartsWith('"'+$root+'\bin\KhadangRouter.exe" ')) { throw 'Unexpected service identity/path; refuse replacement' }
if (-not (Get-Acl $root).AreAccessRulesProtected -or -not (Test-Path "$root\config.json") -or -not (Test-Path "$root\khadang-token.dpapi")) { throw 'Existing protected installation required' }
if ((Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash -ne $ExpectedSha256) { throw 'Artifact digest mismatch' }
$release = Join-Path $root ('release-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $release | Out-Null
Expand-Archive -LiteralPath $Archive -DestinationPath $release
if (-not (Test-Path "$release\publish-live\KhadangRouter.exe")) { throw 'Unexpected reviewed archive layout' }
Stop-Service KhadangRouter
(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(20))
$backup = Join-Path $release 'previous-bin'
Copy-Item -LiteralPath "$root\bin" -Destination $backup -Recurse
Copy-Item "$release\publish-live\*" "$root\bin" -Recurse -Force
$admin = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
Get-ChildItem $root -Recurse -Force | ForEach-Object {$a=Get-Acl $_.FullName;$a.SetOwner($admin);Set-Acl $_.FullName $a}
& "$root\bin\KhadangRouter.exe" --self-test
if ($LASTEXITCODE -ne 0) { throw 'Actual Windows joined tests failed; service stays stopped, previous-bin retained' }
# Keep the historical sealed vault item for recovery, but remove ordinary
# worker access. Its active replacement is the protected SYSTEM service seal.
$staged = 'C:\ProgramData\OracovaCredentials-20261003-qcAC6O\khadang-env.dpapi'
$retired = "$root\retired-staged-khadang-env.dpapi"
if (Test-Path -LiteralPath $staged) {
    if (Test-Path -LiteralPath $retired) { throw 'Two staged copies; inspect before moving' }
    Move-Item -LiteralPath $staged -Destination $retired
    $private = [Security.AccessControl.FileSecurity]::new()
    $private.SetAccessRuleProtection($true,$false);$private.SetOwner($admin)
    foreach ($sid in @('S-1-5-18','S-1-5-32-544')) {
        $private.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','Allow'))
    }
    Set-Acl -LiteralPath $retired -AclObject $private
}
$argument = switch ($Mode) { 'probe' {'--probe-service'} 'canary' {'--canary-service'} 'live' {'--service'} }
$command = '"'+$root+'\bin\KhadangRouter.exe" '+$argument+' --config "'+$root+'\config.json"'
$changed = Invoke-CimMethod -InputObject $service -MethodName Change -Arguments @{PathName=$command;StartMode='Manual'}
if ($changed.ReturnValue -ne 0) { throw 'SCM configuration failed' }
if (Test-Path "$root\state\failure.json") { Move-Item "$root\state\failure.json" (Join-Path $release 'previous-failure.json') }
Start-Service KhadangRouter
[PSCustomObject]@{service=(Get-Service KhadangRouter).Status.ToString();mode=$Mode;previousBin=$backup;credentials='Protected PC-only store; no plaintext output'} | ConvertTo-Json -Compress
