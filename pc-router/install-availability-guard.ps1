param(
 [Parameter(Mandatory=$true)][string]$Guard,
 [Parameter(Mandatory=$true)][string]$GuardSha256,
 [Parameter(Mandatory=$true)][string]$Runner,
 [Parameter(Mandatory=$true)][string]$RunnerSha256,
 [Parameter(Mandatory=$true)][string]$InstalledRunnerSha256
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$root='C:\ProgramData\OracovaNativeRemote'
$name='Oracova-RemoteAvailability'
$identity=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if(-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Administrator-reviewed installation required'}
if(-not (Test-Path $root) -or ((Get-Item $root).Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Expected protected native remote installation'}
if((Test-Path "$root\availability-guard.ps1") -or (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue)){throw 'Existing availability installation: inspect and merge'}
if((Get-FileHash "$root\remote-host.ps1").Hash -ne $InstalledRunnerSha256){throw 'Installed runner changed; review again'}
function Read-Reviewed([string]$path,[string]$digest){
 if((Get-Item $path).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Redirected candidate'}
 $bytes=[IO.File]::ReadAllBytes($path)
 $actual=[BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($bytes)).Replace('-','')
 if($actual -ne $digest){throw 'Reviewed candidate digest mismatch'}
 $tokens=$null;$errors=$null
 [Management.Automation.Language.Parser]::ParseInput([Text.Encoding]::UTF8.GetString($bytes),[ref]$tokens,[ref]$errors) | Out-Null
 if($errors.Count){throw 'Candidate PowerShell parse failed'}
 return ,$bytes
}
$guardBytes=Read-Reviewed $Guard $GuardSha256
$runnerBytes=Read-Reviewed $Runner $RunnerSha256
$stamp=[Guid]::NewGuid().ToString('N')
Copy-Item "$root\remote-host.ps1" "$root\runner-before-status-observer-$stamp.ps1"
[IO.File]::WriteAllBytes("$root\availability-guard.ps1",$guardBytes)
# Update the next launch only. Neither connected native agent is restarted.
[IO.File]::WriteAllBytes("$root\remote-host.ps1",$runnerBytes)
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
foreach($path in @("$root\availability-guard.ps1","$root\remote-host.ps1","$root\runner-before-status-observer-$stamp.ps1")){
 $acl=Get-Acl $path;$acl.SetOwner($admin);Set-Acl $path $acl
}
$action=New-ScheduledTaskAction -Execute 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$root+'\availability-guard.ps1"')
$principal=New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest
$boot=New-ScheduledTaskTrigger -AtStartup
$repeat=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval ([TimeSpan]::FromMinutes(1))
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval ([TimeSpan]::FromMinutes(1))
Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Trigger @($boot,$repeat) -Settings $settings | Out-Null
Start-ScheduledTask -TaskName $name
[Console]::WriteLine('Deterministic availability task started; existing native agents untouched')
