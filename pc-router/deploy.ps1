param(
    [Parameter(Mandatory=$true)][string]$Archive,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedSha256,
    [ValidateSet('probe','canary','live')][string]$Mode = 'probe',
    [switch]$OwnerFullAccess,
    [switch]$WebCutover
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
$runtime = Get-Content "$release\publish-live\KhadangRouter.runtimeconfig.json" -Raw | ConvertFrom-Json
if (-not ($runtime.runtimeOptions.includedFrameworks | Where-Object name -eq 'Microsoft.NETCore.App') -or
    -not (Test-Path "$release\publish-live\coreclr.dll") -or -not (Test-Path "$release\publish-live\System.Private.CoreLib.dll")) {
    throw 'Windows router release must include its reviewed self-contained runtime; live service untouched'
}
# Validate the actual target runtime BEFORE interrupting the service. A Mac
# compile cannot prove Windows packaging, and a mixed overlay is not a runtime.
& (Join-Path $PSScriptRoot 'validate-release.ps1') -CandidateDirectory "$release\publish-live"
if ($LASTEXITCODE -ne 0) { throw 'Windows candidate tests failed; live service untouched' }
Copy-Item "$root\state\probe.json" (Join-Path $release 'previous-probe.json')
[IO.File]::WriteAllText((Join-Path $release 'previous-service.json'), (@{path=$service.PathName;startMode=$service.StartMode} | ConvertTo-Json))
# Serialize administrative staging with deterministic boot supervision. Without
# this fence the new startup task could relaunch a half-replaced release.
$startup = Get-ScheduledTask -TaskName 'Oracova-KhadangStartup' -ErrorAction SilentlyContinue
$startupWasEnabled = $false
if ($startup) {
    if ($startup.Actions.Count -ne 1 -or $startup.Actions[0].Execute -ne 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -or
        $startup.Actions[0].Arguments -ne '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\ProgramData\OracovaNativeRemote\router-startup.ps1"' -or
        $startup.Principal.UserId -notin @('SYSTEM','NT AUTHORITY\SYSTEM','S-1-5-18')) { throw 'Unexpected startup supervisor; preserve it and review' }
    $startupWasEnabled = $startup.State.ToString() -ne 'Disabled'
    [IO.File]::WriteAllText((Join-Path $release 'startup-supervisor-before.json'), (@{task=$startup.TaskName;wasEnabled=$startupWasEnabled;restoreAfterMatchingLiveProbe=$true} | ConvertTo-Json))
    if ($startupWasEnabled) {
        Disable-ScheduledTask -TaskName 'Oracova-KhadangStartup' | Out-Null
        if ((Get-ScheduledTask -TaskName 'Oracova-KhadangStartup').State.ToString() -eq 'Running') { Stop-ScheduledTask -TaskName 'Oracova-KhadangStartup' }
    }
}
Stop-Service KhadangRouter
(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(20))
if ($WebCutover) {
    # Fixed, reviewed migration of the already-created Web checkpoint; never
    # create a model session or alter the existing LG route in the installer.
    & (Join-Path $PSScriptRoot 'stage-web-topic.ps1') -RecoveryDirectory $release
}
if ($OwnerFullAccess) {
    # Explicit owner authorization only; never extend this to employee roles.
    $policyPath = Join-Path $root 'config.json'
    $original = [IO.File]::ReadAllText($policyPath)
    $policy = $original | ConvertFrom-Json
    if ($policy.OwnerId -ne 110123423 -or $policy.BotUsername -ne 'TheKhadangBot') { throw 'Unexpected owner/bot policy' }
    Copy-Item -LiteralPath $policyPath -Destination (Join-Path $release 'previous-config.json')
    $policy | Add-Member OwnerFullAccess $true -Force
    if ([IO.File]::ReadAllText($policyPath) -ne $original) { throw 'Policy changed during inspection' }
    [IO.File]::WriteAllText($policyPath,($policy | ConvertTo-Json -Depth 100),[Text.UTF8Encoding]::new($false))
    if (-not ((Get-Content $policyPath -Raw | ConvertFrom-Json).OwnerFullAccess)) { throw 'Owner profile readback failed' }
}
$backup = Join-Path $release 'previous-bin'
Copy-Item -LiteralPath "$root\bin" -Destination $backup -Recurse
Copy-Item "$release\publish-live\*" "$root\bin" -Recurse -Force
$admin = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
Get-ChildItem $root -Recurse -Force | ForEach-Object {$a=Get-Acl $_.FullName;$a.SetOwner($admin);Set-Acl $_.FullName $a}
& (Join-Path $PSScriptRoot 'validate-release.ps1') -CandidateDirectory "$root\bin"
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
[PSCustomObject]@{service=(Get-Service KhadangRouter).Status.ToString();mode=$Mode;previousBin=$backup;startupSupervisorHeld=$startupWasEnabled;credentials='Protected PC-only store; no plaintext output'} | ConvertTo-Json -Compress
