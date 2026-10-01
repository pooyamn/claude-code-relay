# Run ONCE in an elevated PowerShell on Windows. Registers a task that starts the
# WSL distro at boot and holds it open, because WSL stops a distro shortly after
# its last client exits, and that takes systemd (ccrelayd, the codex daemon) down.
$distro = "Ubuntu-24.04"
$action  = New-ScheduledTaskAction -Execute "wsl.exe" -Argument "-d $distro -u pouya -- sleep infinity"
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Highest
Register-ScheduledTask -TaskName "WSL keep-alive ($distro)" -Action $action -Trigger $trigger `
  -Settings $settings -Principal $principal -Force
# Never let the VM idle out, and never sleep the PC.
$cfg = "$env:USERPROFILE\.wslconfig"
if (-not (Select-String -Path $cfg -Pattern "vmIdleTimeout" -Quiet -ErrorAction SilentlyContinue)) {
  Add-Content $cfg "[wsl2]`nvmIdleTimeout=-1"
}
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
Write-Host "Done. Start it now with: Start-ScheduledTask -TaskName 'WSL keep-alive ($distro)'"
