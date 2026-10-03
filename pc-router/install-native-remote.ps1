param([Parameter(Mandatory=$true)][string]$Runner)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = 'C:\ProgramData\OracovaNativeRemote'
$state = 'C:\Users\pou\.native-remote'
$workspace = 'C:\Users\pou\workspaces\pc-control'
$owner = [Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
$admin = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
$system = [Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator-reviewed installation required' }
if ((Test-Path $root) -or (Get-ScheduledTask -TaskName 'Oracova-CodexRemote','Oracova-ClaudeRemote' -ErrorAction SilentlyContinue)) {
    throw 'Existing remote installation; inspect and merge, never overwrite'
}
if ((Test-Path $state) -or (Test-Path $workspace)) { throw 'Expected new dedicated runtime/workspace; inspect existing paths' }
foreach ($path in @($Runner,'C:\Users\pou\.claude\settings.json','C:\Users\pou\.claude.json')) {
    if (-not (Test-Path $path) -or ((Get-Item $path).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Missing or redirected source/configuration' }
}
$settingsPath = 'C:\Users\pou\.claude\settings.json'
$oldSettings = [IO.File]::ReadAllText($settingsPath)
$settings = $oldSettings | ConvertFrom-Json
$globalPath = 'C:\Users\pou\.claude.json'
$oldGlobal = [IO.File]::ReadAllText($globalPath)
$global = $oldGlobal | ConvertFrom-Json
New-Item -ItemType Directory $root,$state,$workspace | Out-Null
$protected = [Security.AccessControl.DirectorySecurity]::new()
$protected.SetAccessRuleProtection($true,$false);$protected.SetOwner($admin)
foreach ($sid in @($admin,$system)) {
    $protected.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
}
$protected.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($owner,'ReadAndExecute','ContainerInherit,ObjectInherit','None','Allow'))
Set-Acl -LiteralPath $root -AclObject $protected
$private = [Security.AccessControl.DirectorySecurity]::new()
$private.SetAccessRuleProtection($true,$false);$private.SetOwner($owner)
foreach ($sid in @($owner,$admin,$system)) {
    $private.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
}
Set-Acl -LiteralPath $state -AclObject $private
Copy-Item -LiteralPath $Runner -Destination "$root\remote-host.ps1"
Copy-Item -LiteralPath $settingsPath -Destination "$root\previous-claude-settings.json"
Copy-Item -LiteralPath $globalPath -Destination "$root\previous-claude-global.json"
Get-ChildItem $root -Force | ForEach-Object {$acl=Get-Acl $_.FullName;$acl.SetOwner($admin);Set-Acl $_.FullName $acl}
# Backups must not expose the global file's account metadata to ordinary agents.
foreach ($backup in @('previous-claude-settings.json','previous-claude-global.json')) {
    $acl = [Security.AccessControl.FileSecurity]::new();$acl.SetAccessRuleProtection($true,$false);$acl.SetOwner($admin)
    foreach ($sid in @($admin,$system)) {$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','Allow'))}
    Set-Acl -LiteralPath "$root\$backup" -AclObject $acl
}
& 'C:\Program Files\Git\cmd\git.exe' -c core.fsmonitor=false -c "core.hooksPath=$root" -C $workspace init --quiet
if ($LASTEXITCODE -ne 0) { throw 'Dedicated control workspace initialization failed' }
# Worktree spawn requires HEAD even in this deliberately empty control repo.
& 'C:\Program Files\Git\cmd\git.exe' -c core.fsmonitor=false -c "core.hooksPath=$root" -c commit.gpgsign=false -c 'user.name=Oracova native bootstrap' -c 'user.email=native-bootstrap@localhost' -C $workspace commit --allow-empty --quiet -m 'Initialize owner Remote Control workspace'
if ($LASTEXITCODE -ne 0) { throw 'Dedicated control workspace HEAD initialization failed' }
foreach($path in @($workspace,"$workspace\.git")){$acl=Get-Acl $path;$acl.SetOwner($owner);Set-Acl $path $acl}
$settings | Add-Member remoteControlAtStartup $true -Force
if (-not $global.PSObject.Properties['projects']) {$global | Add-Member projects ([PSCustomObject]@{})}
# This new empty owner control repo has been inspected and explicitly placed
# in scope by the owner. Trust only this exact directory, never the home/root.
$project = [PSCustomObject]@{hasTrustDialogAccepted=$true}
$global.projects | Add-Member $workspace $project -Force
# Claude uses the slash-normalized project key on native Windows.
$global.projects | Add-Member ($workspace.Replace('\','/')) $project -Force
if ([IO.File]::ReadAllText($settingsPath) -ne $oldSettings -or [IO.File]::ReadAllText($globalPath) -ne $oldGlobal) { throw 'Native settings changed during installation' }
$utf8 = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText($settingsPath,($settings | ConvertTo-Json -Depth 100),$utf8)
[IO.File]::WriteAllText($globalPath,($global | ConvertTo-Json -Depth 100),$utf8)
if (-not ((Get-Content $settingsPath -Raw | ConvertFrom-Json).remoteControlAtStartup)) { throw 'Claude auto-connect readback failed' }
$ps = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$identity = New-ScheduledTaskPrincipal -UserId $owner.Value -LogonType Interactive -RunLevel Limited
# On this machine S4U/Limited nevertheless produced an elevated Session-0 token.
# Logon startup is tested; before-login availability is NOT claimed by this installer.
$logon = New-ScheduledTaskTrigger -AtLogOn -User $owner.Value
$repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval ([TimeSpan]::FromMinutes(1))
$codexSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval ([TimeSpan]::FromMinutes(1))
$claudeSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval ([TimeSpan]::FromMinutes(1))
foreach ($provider in @('Codex','Claude')) {
    $action = New-ScheduledTaskAction -Execute $ps -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$root+'\remote-host.ps1" -Provider '+$provider)
    $triggers = @($logon,$repeat)
    $configuration = if ($provider -eq 'Codex') {$codexSettings} else {$claudeSettings}
    Register-ScheduledTask -TaskName ('Oracova-'+$provider+'Remote') -Action $action -Principal $identity -Trigger $triggers -Settings $configuration | Out-Null
    Start-ScheduledTask -TaskName ('Oracova-'+$provider+'Remote')
}
[PSCustomObject]@{tasks=@('Oracova-CodexRemote','Oracova-ClaudeRemote');identity='Owner Interactive / Limited; no stored password or SYSTEM agent';
    logonEnabled=$true;beforeLoginVerified=$false;onlineVerified=$false;claudeAutoConnect=$true;workspace=$workspace} | ConvertTo-Json -Compress
