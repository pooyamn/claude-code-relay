$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$codexPath = 'C:\Users\pou\.codex\config.toml'
$claudePath = 'C:\Users\pou\.claude\settings.json'
$privateRoot = 'C:\ProgramData\KhadangRouter'
if (-not (Get-Acl $privateRoot).AreAccessRulesProtected) { throw 'Protected PC backup root required' }
foreach ($path in @($codexPath,$claudePath)) {
    if (-not (Test-Path -LiteralPath $path)) { throw 'Expected native user configuration absent; inspect first' }
    if ((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Refuse a redirected settings file' }
}
$oldCodex = [IO.File]::ReadAllText($codexPath)
$oldClaude = [IO.File]::ReadAllText($claudePath)
$settings = $oldClaude | ConvertFrom-Json
$backup = Join-Path $privateRoot ('owner-settings-before-full-access-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $backup | Out-Null
Copy-Item -LiteralPath $codexPath -Destination (Join-Path $backup 'codex-config.toml')
Copy-Item -LiteralPath $claudePath -Destination (Join-Path $backup 'claude-settings.json')
$admin = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
Get-ChildItem $backup -Force | ForEach-Object {$acl=Get-Acl $_.FullName;$acl.SetOwner($admin);Set-Acl $_.FullName $acl}
$a=Get-Acl $backup;$a.SetOwner($admin);Set-Acl $backup $a
# Mechanical root-key merge: never rewrite unrelated TOML tables or JSON keys.
$lines = [Collections.Generic.List[string]]::new()
$lines.Add('sandbox_mode = "danger-full-access"');$lines.Add('approval_policy = "never"')
$inRoot = $true
foreach ($line in ($oldCodex -split '\r?\n')) {
    if ($line -match '^\s*\[') {$inRoot=$false}
    if ($inRoot -and $line -match '^\s*(sandbox_mode|approval_policy)\s*=') {continue}
    $lines.Add($line)
}
if (-not $settings.PSObject.Properties['permissions']) { $settings | Add-Member permissions ([PSCustomObject]@{}) }
if (-not $settings.permissions) { $settings.permissions=[PSCustomObject]@{} }
$settings.permissions | Add-Member defaultMode 'bypassPermissions' -Force
$newClaude = $settings | ConvertTo-Json -Depth 100
$newCodex = $lines -join "`r`n"
if ([IO.File]::ReadAllText($codexPath) -ne $oldCodex -or [IO.File]::ReadAllText($claudePath) -ne $oldClaude) { throw 'Settings changed during inspection; no overwrite' }
$utf8 = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText($codexPath,$newCodex,$utf8)
[IO.File]::WriteAllText($claudePath,$newClaude,$utf8)
$readClaude = [IO.File]::ReadAllText($claudePath) | ConvertFrom-Json
$readCodex = [IO.File]::ReadAllText($codexPath)
if ($readClaude.permissions.defaultMode -ne 'bypassPermissions' -or $readCodex -notmatch '(?m)^sandbox_mode = "danger-full-access"\r?$' -or
    $readCodex -notmatch '(?m)^approval_policy = "never"\r?$') { throw 'Full-access settings readback failed; private backups retained' }
if (($settings.env | ConvertTo-Json -Depth 100 -Compress) -ne ($readClaude.env | ConvertTo-Json -Depth 100 -Compress) -or
    $readClaude.autoUpdatesChannel -ne $settings.autoUpdatesChannel -or $readCodex -notmatch 'check_for_update_on_startup = false') { throw 'Unrelated update configuration differs' }
[PSCustomObject]@{host=$env:COMPUTERNAME;codex=@{sandbox_mode='danger-full-access';approval_policy='never';path=$codexPath};
    claude=@{defaultMode=$readClaude.permissions.defaultMode;path=$claudePath};updatesPreserved=$true;backups=$backup;
    note='User defaults only; explicit launcher/session flags can override them. No elevation or SYSTEM agent.'} | ConvertTo-Json -Depth 6
