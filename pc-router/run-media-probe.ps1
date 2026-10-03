param(
    [Parameter(Mandatory=$true)][string]$Archive,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedSha256,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RunId,
    [switch]$ObserveOnly,
    [switch]$Steer
)
$ErrorActionPreference = 'Stop'
if ($ObserveOnly -and $Steer) { throw 'Observation and inference/steering modes are mutually exclusive' }
$ProgressPreference = 'SilentlyContinue'
$root = 'C:\ProgramData\KhadangRouter'
$policy = "$root\config.json"
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Reviewed administrator diagnostic only' }
if (-not (Get-Acl $root).AreAccessRulesProtected -or
    (Get-FileHash $policy -Algorithm SHA256).Hash -ne '653FD4D37637BEA5ED8C88BF063A1669D5A0DCA5E3B6BDD795189D151A2FD2EC') {
    throw 'Existing protected, pinned Khadang policy required'
}
if ((Get-Service KhadangRouter).Status.ToString() -ne 'Running') { throw 'Live router must remain running; this diagnostic never replaces it' }
if ((Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash -ne $ExpectedSha256) { throw 'Reviewed diagnostic archive digest mismatch' }
$release = Join-Path $root ('media-probe-'+$RunId)
$taskName = 'Oracova-MediaProbe-'+$RunId
if ((Test-Path -LiteralPath $release) -or (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) { throw 'Prior diagnostic run exists; reconcile it, never restart/replay' }
New-Item -ItemType Directory $release | Out-Null
Expand-Archive -LiteralPath $Archive -DestinationPath $release
$exe = "$release\publish-probe\MediaProbe.exe"
$runtime = Get-Content "$release\publish-probe\MediaProbe.runtimeconfig.json" -Raw | ConvertFrom-Json
if (-not (Test-Path $exe) -or -not ($runtime.runtimeOptions.includedFrameworks | Where-Object name -eq 'Microsoft.NETCore.App') -or
    -not (Test-Path "$release\publish-probe\coreclr.dll")) { throw 'Self-contained Windows diagnostic required' }
if ((Get-FileHash "$release\publish-probe\KhadangRouter.dll" -Algorithm SHA256).Hash -ne
    (Get-FileHash "$root\bin\KhadangRouter.dll" -Algorithm SHA256).Hash) { throw 'Use the exact deployed router assembly for provider download/native launcher proof' }
$admin = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
Get-ChildItem -LiteralPath $release -Recurse -Force | ForEach-Object { $acl=Get-Acl $_.FullName; $acl.SetOwner($admin); Set-Acl $_.FullName $acl }
& $exe --self-test
if ($LASTEXITCODE -ne 0) { throw 'Actual Windows generated-fixture test failed' }
& "$release\publish-probe\KhadangRouter.exe" --self-test
if ($LASTEXITCODE -ne 0) { throw 'Actual Windows router dependency tests failed' }
$arguments = '--config "'+$policy+'" --run '+$RunId
if ($ObserveOnly) { $arguments += ' --observe-only' }
if ($Steer) { $arguments += ' --steer' }
$action = New-ScheduledTaskAction -Execute $exe -Argument $arguments -WorkingDirectory "$release\publish-probe"
$owner = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
# No triggers, repetition, restart policy, or credential/key arguments. SYSTEM
# only handles Telegram and launches the pinned native executable as medium pou.
Register-ScheduledTask -TaskName $taskName -Action $action -Principal $owner -Settings $settings | Out-Null
[IO.File]::WriteAllText((Join-Path $release 'reviewed-run.json'), (@{run=$RunId;archiveSha256=$ExpectedSha256;task=$taskName;oneShot=$true;liveServiceChanged=$false;modelTurnLimit=1} | ConvertTo-Json))
Start-ScheduledTask -TaskName $taskName
[Console]::WriteLine((@{task=$taskName;state=(Get-ScheduledTask -TaskName $taskName).State.ToString();release=$release;result="$root\state\diagnostics\media-$RunId\result.json"} | ConvertTo-Json -Compress))
