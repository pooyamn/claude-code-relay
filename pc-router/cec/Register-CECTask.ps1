$ErrorActionPreference='Stop'
$base='C:\ProgramData\GT105CEC'
$taskName='GT105-CEC-ClockGate'
if(Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue){throw 'Existing task; inspect before updating'}
if(-not (Test-Path (Join-Path $base 'manifest.json'))){throw 'Policy installation is not prepared'}
$command="& ([scriptblock]::Create([IO.File]::ReadAllText('$base\CEC-Policy.ps1'))) -Mode Apply"
$action=New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument ('-NoProfile -NonInteractive -Command "'+$command+'"')
$principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$startup=New-ScheduledTaskTrigger -AtStartup
$startup.Delay='PT5S'
$subscription='<QueryList><Query Id="0" Path="System"><Select Path="System">*[System[(Provider[@Name="Microsoft-Windows-Power-Troubleshooter"] and EventID=1) or (Provider[@Name="Microsoft-Windows-Kernel-Power"] and (EventID=107 or EventID=507))]]</Select></Query></QueryList>'
$resume=New-CimInstance -ClientOnly -Namespace root/Microsoft/Windows/TaskScheduler -ClassName MSFT_TaskEventTrigger -Property @{Enabled=$true;Subscription=$subscription;Delay='PT3S'}
# Client-only CimInstances lack the cmdlet's required base-class PSTypeName.
# Supply that metadata; retain the actual MSFT_TaskEventTrigger CIM class.
$resume.PSObject.TypeNames.Add('Microsoft.Management.Infrastructure.CimInstance#MSFT_TaskTrigger')
$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 1)
$null=Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Trigger @($startup,$resume) -Settings $settings -Description 'GT105 IT5570: gate only CEC clock at boot/resume; guarded identity/idle checks; no firmware edits.'
