# Read-only Windows-owner -> WSL root diagnostic. Never reads credential files,
# installs accounts, changes WSL configuration or starts any model process.
# Run as Interactive/Limited from a reviewed administrator-owned task/script.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=[Security.Principal.WindowsPrincipal]::new($identity)
$session=[Diagnostics.Process]::GetCurrentProcess().SessionId
if($identity.User.Value -ne 'S-1-5-21-71459778-1164188569-2276148161-1001' -or
   $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or $session -eq 0){
 throw 'Actual non-elevated interactive owner required'
}
$result=(& 'C:\Windows\System32\wsl.exe' --distribution Ubuntu-24.04 --user root --exec /usr/bin/id --user 2>$null)
$exitCode=$LASTEXITCODE
$rootObserved=$exitCode -eq 0 -and ([string]($result -join "")).Trim() -eq '0'
$report=[ordered]@{
 schema='ccrelay.wsl_owner_boundary_probe.v1';at=[DateTime]::UtcNow.ToString('o')
 ownerSid=$identity.User.Value;windowsElevated=$false;sessionId=$session
 distribution='Ubuntu-24.04';linuxRootObserved=$rootObserved;wslExitCode=$exitCode
 credentialsRead=$false;modelsStarted=$false;liveRoleAcceptance=$false
}
$directory=Join-Path $env:LOCALAPPDATA 'OracovaDiagnostics'
if(-not (Test-Path $directory)){New-Item -ItemType Directory -Path $directory | Out-Null}
[IO.File]::WriteAllText((Join-Path $directory 'wsl-owner-boundary.json'),($report | ConvertTo-Json -Compress))
if($exitCode -ne 0){exit $exitCode}
if(-not $rootObserved){throw 'Unexpected id output; no root-boundary conclusion'}
exit 0
