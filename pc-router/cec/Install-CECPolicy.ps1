param([string]$SourceDirectory)
$ErrorActionPreference='Stop'
if(-not $SourceDirectory){throw 'Explicit source directory required'}
$base='C:\ProgramData\GT105CEC'
$evidence='C:\Users\pou\Downloads\GT105-BIOS-readout-20261031-qhgCtb'
$taskName='GT105-CEC-ClockGate'
if(Test-Path $base){throw 'Existing policy directory; inspect before updating'}
if(Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue){throw 'Existing task; refusing overwrite'}
if(Get-Service PawnIO -ErrorAction SilentlyContinue){throw 'Existing PawnIO provider; refusing replacement'}
if(Test-Path 'C:\Program Files\PawnIO'){throw 'Existing provider installation'}
$installer=Join-Path $evidence 'PawnIO_setup-2.2.0.exe'
$module=Join-Path $evidence 'PawnIO-inspected-payloads\LpcIO.bin'
if((Get-FileHash $installer).Hash -ne '1f519a22e47187f70a1379a48ca604981c4fcf694f4e65b734aaa74a9fba3032' -or (Get-AuthenticodeSignature $installer).Status -ne 'Valid'){throw 'Installer verification failed'}
if((Get-FileHash $module).Hash -ne 'b3896a1cab0d808fca31fe2ebcae045d59dac690da87b17c858bb8da357eb45e'){throw 'Signed module hash mismatch'}
$null=New-Item -ItemType Directory $base
& icacls.exe $base /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if($LASTEXITCODE -ne 0){throw 'Cannot secure policy directory'}
$null=New-Item -ItemType Directory (Join-Path $base 'runs')
foreach($file in @('CEC-Policy.ps1','CECClockGateProbe.cs','Register-CECTask.ps1')){Copy-Item (Join-Path $SourceDirectory $file) (Join-Path $base $file)}
Copy-Item $module (Join-Path $base 'LpcIO.bin')
Copy-Item $installer (Join-Path $base 'PawnIO_setup.exe')
if((Get-FileHash (Join-Path $base 'PawnIO_setup.exe')).Hash -ne '1f519a22e47187f70a1379a48ca604981c4fcf694f4e65b734aaa74a9fba3032'){throw 'Staged installer mismatch'}
if((Get-FileHash (Join-Path $base 'LpcIO.bin')).Hash -ne 'b3896a1cab0d808fca31fe2ebcae045d59dac690da87b17c858bb8da357eb45e'){throw 'Staged module mismatch'}
Add-Type -TypeDefinition ([IO.File]::ReadAllText((Join-Path $base 'CECClockGateProbe.cs'))) -OutputAssembly (Join-Path $base 'CECClockGateProbe.dll')
Add-Type -Path (Join-Path $base 'CECClockGateProbe.dll')
[CECClockGateProbe]::SelfTest()
$install=Start-Process -FilePath (Join-Path $base 'PawnIO_setup.exe') -ArgumentList '-install','-silent' -Wait -PassThru
if($install.ExitCode -ne 0){throw 'Official restricted provider installation failed'}
$dll='C:\Program Files\PawnIO\PawnIOLib.dll'
if((Get-FileHash $dll).Hash -ne 'd71f62627d66983bb9f5b1c269f27bcd8c1b8a46e794377a6330f84c198f4443' -or (Get-AuthenticodeSignature $dll).Status -ne 'Valid'){throw 'Provider library verification failed'}
$probe=New-Object CECClockGateProbe (Join-Path $base 'LpcIO.bin')
try{$baseline=$probe.Snapshot();[CECClockGateProbe]::GuardIdle($baseline)}finally{$probe.Dispose()}
$manifest=[ordered]@{version=2;biosVersion='1.10';biosDateUtc='20251022';chipId='0x5570';chipRevision=2;originalGateBit=0;moduleSha256='b3896a1cab0d808fca31fe2ebcae045d59dac690da87b17c858bb8da357eb45e';librarySha256='d71f62627d66983bb9f5b1c269f27bcd8c1b8a46e794377a6330f84c198f4443';driverSha256='fca6e7d58b0cf38dbb913a2b9e532f48629145d395f454b16a9f58e97b8d3940';helperSha256=(Get-FileHash (Join-Path $base 'CECClockGateProbe.dll')).Hash;policySha256=(Get-FileHash (Join-Path $base 'CEC-Policy.ps1')).Hash;installedUtc=[DateTime]::UtcNow.ToString('o');baseline=$baseline}
[IO.File]::WriteAllText((Join-Path $base 'manifest.json'),($manifest | ConvertTo-Json -Depth 8))
& ([scriptblock]::Create([IO.File]::ReadAllText((Join-Path $base 'Register-CECTask.ps1'))))
Export-ScheduledTask -TaskName $taskName | Set-Content -LiteralPath (Join-Path $evidence 'CEC-startup-task.xml') -Encoding Unicode
Remove-Item -LiteralPath (Join-Path $base 'PawnIO_setup.exe')
Write-Output 'Installed provider and startup/resume task. No CEC control write performed by installer. Run the task explicitly to apply and verify.'
