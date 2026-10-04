$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'export-pc-recovery-settings.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Settings source parse failed'}
# Only pure/read-only definitions: never execute production discovery/export.
foreach($fn in $ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){. ([ScriptBlock]::Create($fn.Extent.Text))}
$checks=0
function Assert([bool]$Value,[string]$Label){if(-not $Value){throw $Label};$script:checks++}
$root=Join-Path ([IO.Path]::GetTempPath()) ('recovery-settings-fixture-'+[Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($root,(New-SettingsAcl $true))|Out-Null
try{
 Assert-SettingsParent $root
 $good=Read-SettingsSection 'fixture' {@{hidden='PRIVATE-SETTINGS-MARKER'}}
 $bad=Read-SettingsSection 'fixture-failure' {throw 'PRIVATE-ERROR-MARKER'}
 Assert ($good.state -eq 'observed' -and $good.data.hidden -eq 'PRIVATE-SETTINGS-MARKER') 'Read-only successful data retained privately'
 Assert ($bad.state -eq 'unavailable' -and $null -eq $bad.data -and $bad.errorType -and -not ($bad|ConvertTo-Json -Compress).Contains('PRIVATE-ERROR-MARKER')) 'Failure explicit, exception contents not published'
 $value=Convert-SettingsValue 'FixtureBinary' 'Binary' ([byte[]]@(0,255,10,128))
 Assert ($value.value.base64 -eq 'AP8KgA==' -and $value.kind -eq 'Binary') 'Typed binary registry data encoded without loss'
 $value=Convert-SettingsValue 'FixtureExpand' 'ExpandString' '%PRIVATE_FIXTURE%'
 Assert ($value.value -eq '%PRIVATE_FIXTURE%') 'Expandable registry text not expanded'
 foreach($name in @('DefaultPassword','defaultpassword','DEFAULTPASSWORD')){
  try{Convert-SettingsValue $name 'String' 'PRIVATE-PASSWORD-MARKER';throw 'accepted'}catch{Assert ($_.Exception.Message -eq 'Never export a Winlogon password value') 'Password rejected case-insensitively'}
 }
 $missing=Read-SettingsRegistry CurrentUser ('Software\MissingRecoveryFixture-'+[Guid]::NewGuid().ToString('N'))
 Assert (-not $missing.present -and $missing.entries.Count -eq 0) 'Actual absent registry root is absent, never created'
 $native=Read-SettingsNative 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' '-NoLogo -NoProfile -NonInteractive -Command "[Console]::Write(123)"'
 Assert ($native -eq '123') 'Actual native stdout privately captured with exact value'
 try{Read-SettingsNative 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' '-NoLogo -NoProfile -NonInteractive -Command "exit 7"';throw 'accepted'}catch{Assert ($_.Exception.Message -eq 'Bounded read-only command failed') 'Nonzero native exit is not success'}
 Assert ($null -eq (Convert-SettingsTime $null)) 'Absent next-run timestamp stays null, not a task export failure'
 Assert ((Convert-SettingsTime ([DateTime]::new(2026,10,4,13,0,0,[DateTimeKind]::Utc))) -eq '2026-10-04T13:00:00.0000000Z') 'Actual task timestamp retains invariant ISO precision and timezone'
 Assert ((Convert-SettingsTime ([DateTimeOffset]::new(2026,10,4,13,0,0,[TimeSpan]::FromHours(-7)))) -eq '2026-10-04T13:00:00.0000000-07:00') 'Timestamp offset preserved, not converted to local time'
 try{Convert-SettingsTime 'PRIVATE-INVALID-TIMESTAMP';throw 'accepted'}catch{Assert ($_.Exception.Message -eq 'Unsupported task timestamp type') 'Invalid timestamp remains an explicit failure'}
 $report=@{schema='fixture';run='fixture';finishedAt='fixture';sections=@($good,$bad)}
 $artifact=Write-SettingsArtifact (Join-Path $root 'new-run') $report
 Assert ((Get-FileHash $artifact.path).Hash.ToLowerInvariant() -eq $artifact.sha256 -and (Get-Item $artifact.path).Length -eq $artifact.bytes) 'Real artifact byte count and independent file hash match'
 $acl=Get-Acl $artifact.path
 Assert ($acl.AreAccessRulesProtected -and $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -eq 'S-1-5-32-544') 'Real artifact administrator-owned with protected ACL'
 Assert (@($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])|Where-Object {$_.IdentityReference.Value -notin @('S-1-5-18','S-1-5-32-544')}).Count -eq 0) 'No ordinary-owner file grants'
 try{Write-SettingsArtifact (Join-Path $root 'new-run') $report;throw 'accepted'}catch{Assert ($_.Exception.Message -eq 'Settings run already exists; never overwrite or replay') 'Existing artifact preserved, never overwritten'}
 $summary=Get-SettingsSummary $report $artifact
 Assert (-not $summary.allSelectedSectionsObserved -and -not $summary.fullSystemBackup -and -not $summary.restoreActivated -and -not $summary.encrypted -and -not $summary.writersFrozen) 'Unavailable section and limited recovery scope cannot be relabeled complete'
 Assert (-not ($summary|ConvertTo-Json -Depth 6 -Compress).Contains('PRIVATE-SETTINGS-MARKER')) 'Summary cannot disclose section data'
 $goodReport=@{schema='fixture';run='fixture';finishedAt='fixture';sections=@($good)}
 Assert (Get-SettingsSummary $goodReport $artifact).allSelectedSectionsObserved 'Selected observations can pass without full-backup claim'
 $commands=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.CommandAst]},$true)|ForEach-Object {$_.GetCommandName()}|Where-Object {$_})
 Assert (@($commands|Where-Object {$_ -match '^(Set-|Register-|Start-Service|Stop-Service|Restart-|Invoke-CimMethod|Enable-|Disable-|Remove-ItemProperty|New-ItemProperty)'}).Count -eq 0) 'Source contains no configuration/task/service mutation commands'
 Assert ($ast.Extent.Text.Contains('OpenSubKey($current,$false)') -and $ast.Extent.Text.Contains('DoNotExpandEnvironmentNames')) 'Registry handles explicitly read-only and values unexpanded'
 [Console]::WriteLine(('All '+$checks+' recovery-settings fixtures passed; no real discovery, secrets, network, models or live configuration changes.'))
}finally{
 # Only this literal, generated fixture, never a real source/recovery directory.
 [IO.Directory]::Delete($root,$true)
}
