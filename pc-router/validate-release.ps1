param([Parameter(Mandatory=$true)][string]$CandidateDirectory)
# Offline release gate. This script must run without live service credentials.
# It never loads production configuration, connects to the PC or deploys code.
$ErrorActionPreference='Stop'
$candidate=(Resolve-Path -LiteralPath $CandidateDirectory).Path
$windows=$env:OS -eq 'Windows_NT'
if($windows -and -not ([Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Windows ACL regression requires an isolated administrator runner; do not run candidate code with live credentials'
}
$executable=Join-Path $candidate $(if($windows){'KhadangRouter.exe'}else{'KhadangRouter'})
$runtime=Get-Content -LiteralPath (Join-Path $candidate 'KhadangRouter.runtimeconfig.json') -Raw | ConvertFrom-Json
$coreclr=Join-Path $candidate $(if($windows){'coreclr.dll'}else{'libcoreclr.so'})
if (-not ($runtime.runtimeOptions.includedFrameworks | Where-Object name -eq 'Microsoft.NETCore.App') -or
    -not (Test-Path -LiteralPath $coreclr) -or -not (Test-Path -LiteralPath $executable)) {
    throw 'Release gate requires a self-contained target-platform artifact'
}
$assembly=Join-Path $candidate 'KhadangRouter.dll'
$before=(Get-FileHash -LiteralPath $assembly -Algorithm SHA256).Hash
foreach($suite in @('--self-test-reliability','--self-test-delivery','--self-test-input-isolation','--self-test-startup-isolation','--self-test-transport-health','--self-test-capacity','--self-test-controller-handoff','--self-test-participants','--self-test')) {
    $output=(& $executable $suite) -join "`n"
    if($LASTEXITCODE -ne 0) { throw "Release validation failed: $suite" }
    # A missing CLI/suite must not be mistaken for an accepted release.
    $expected=switch($suite){
        '--self-test' {'All \d+ PC-router checks passed'}
        '--self-test-startup-isolation' {'Passed \d+ startup-isolation checks'}
        '--self-test-transport-health' {'Passed \d+ transport-health checks'}
        '--self-test-capacity' {'Passed \d+ capacity-admission checks'}
        '--self-test-controller-handoff' {'Passed \d+ controller-handoff checks'}
        '--self-test-participants' {'Passed \d+ participant-access checks'}
        '--self-test-reliability' {'Passed \d+ reliability checks'}
        '--self-test-delivery' {'Passed \d+ delivery checks'}
        default {'Passed \d+ upload-timeout/input-isolation checks'}
    }
    if($output -notmatch $expected) { throw "Missing regression-suite receipt: $suite" }
    Write-Output $output
}
& (Join-Path $PSScriptRoot 'router-watchdog.ps1') -SelfTest
if($windows){
 $acl=(& (Join-Path $PSScriptRoot 'dispatch-controller-handoff.ps1') -SelfTest)-join "`n"
 if($acl -notmatch 'Passed 4 controller-handoff ACL publication checks'){throw 'Handoff ACL publication fixture failed'}
 Write-Output $acl
}
if((Get-FileHash -LiteralPath $assembly -Algorithm SHA256).Hash -ne $before) { throw 'Candidate changed during validation' }
Write-Output "Release validation passed; router SHA256: $before"
