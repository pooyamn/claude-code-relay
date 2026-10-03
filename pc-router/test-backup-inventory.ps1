$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$source=Join-Path $PSScriptRoot 'inspect-backup-inventory.ps1'
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Inventory source parse failed'}
# Compile/load reviewed definitions only. Never execute discovery or private report
# publication against real runtime/credential roots from a fixture.
$definition=$ast.Find({param($node) $node -is [Management.Automation.Language.CommandAst] -and $node.GetCommandName() -eq 'Add-Type'},$true)
& ([ScriptBlock]::Create($definition.Extent.Text))
foreach($function in $ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){. ([ScriptBlock]::Create($function.Extent.Text))}
$checks=0
function Assert([bool]$Value,[string]$Label){if(-not $Value){throw $Label};$script:checks++}
$fixture=Join-Path ([IO.Path]::GetTempPath()) ('oracova-recovery-inventory-tests-'+[Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($fixture) | Out-Null
$inside=Join-Path $fixture 'inside';$outside=Join-Path $fixture 'outside'
[IO.Directory]::CreateDirectory($inside) | Out-Null;[IO.Directory]::CreateDirectory($outside) | Out-Null
[IO.Directory]::CreateDirectory((Join-Path $inside 'empty')) | Out-Null
[IO.File]::WriteAllText((Join-Path $inside 'state_5.sqlite'),'fixture only')
[IO.File]::WriteAllText((Join-Path $inside 'state_5.sqlite-wal'),'fixture WAL only')
[IO.File]::WriteAllText((Join-Path $inside 'one-shot.claim'),'keep this dispatch evidence')
[IO.File]::WriteAllText((Join-Path $inside 'Cargo.lock'),'dependency lock is source state')
[IO.File]::WriteAllText((Join-Path $outside 'never-follow-private-marker'),'not source data')
$original=Join-Path $inside 'literal [name] .txt';[IO.File]::WriteAllText($original,'PRIVATE-CONTENT-MARKER')
$link=Join-Path $inside 'hardlink.txt';$junction=Join-Path $inside 'junction'
& $env:ComSpec /d /c ('mklink /H "'+$link+'" "'+$original+'"') | Out-Null
if($LASTEXITCODE -ne 0){throw 'Actual NTFS hardlink fixture failed'}
& $env:ComSpec /d /c ('mklink /J "'+$junction+'" "'+$outside+'"') | Out-Null
if($LASTEXITCODE -ne 0){throw 'Actual NTFS junction fixture failed'}
try{
 $dynamic=Join-Path $fixture 'OracovaFixture';[IO.Directory]::CreateDirectory($dynamic) | Out-Null
 $sources=@(Get-RecoverySources $fixture)
 Assert (@($sources | Where-Object id -eq 'native-codex').Count -eq 1) 'Fixed source tuples retain their named fields'
 $discovered=$sources | Where-Object id -eq 'oracova-OracovaFixture'
 Assert ($discovered.path -eq $dynamic -and $discovered.required -is [bool] -and $discovered.required) 'Dynamic ProgramData rows retain exact path and boolean requirement'
 $dynamicComponent=Get-RecoveryComponent $discovered.id $discovered.path $discovered.required 100
 Assert ($dynamicComponent.present -and $dynamicComponent.enumerationFinished) 'Real discovered component binds correctly to collector parameters'
 $component=Get-RecoveryComponent 'fixture' $inside $true 100
 Assert $component.present 'Real source observed'
 Assert (-not $component.enumerationFinished) 'Unrepresented junction cannot certify complete enumeration'
 Assert (@($component.entries | Where-Object relativeDisplay -eq 'empty').Count -eq 1) 'Empty directory retained'
 Assert (@($component.entries | Where-Object kind -eq 'sqlite-candidate').Count -eq 1) 'SQLite candidate discovered'
 Assert (@($component.entries | Where-Object kind -eq 'sqlite-sidecar').Count -eq 1) 'WAL retained as sidecar, not coherent snapshot'
 Assert (@($component.entries | Where-Object kind -eq 'persistent-action-deduplication').Count -eq 1) 'One-shot claim retained as durable action evidence'
 Assert (($component.entries | Where-Object relativeDisplay -eq 'Cargo.lock').kind -eq 'file') 'Do not treat arbitrary dependency locks as runtime ownership'
 $a=$component.entries | Where-Object relativeDisplay -eq 'literal [name] .txt';$b=$component.entries | Where-Object relativeDisplay -eq 'hardlink.txt'
 Assert ($a.fileIdentity -eq $b.fileIdentity -and $a.linkCount -ge 2) 'Real same-inode hardlink identities/counts observed'
 Assert ($null -ne $a.sddl) 'Actual source ACL recorded without changing it'
 Assert (@($component.entries | Where-Object relativeDisplay -like 'junction\*').Count -eq 0) 'Junction descendants are not followed'
 Assert (-not (($component | ConvertTo-Json -Depth 8 -Compress).Contains('PRIVATE-CONTENT-MARKER'))) 'File contents are never output'
 $bounded=Get-RecoveryComponent 'bounded' $inside $true 2
 Assert (-not $bounded.enumerationFinished -and @($bounded.issues | Where-Object kind -eq 'EntryBoundReached').Count -eq 1) 'Entry bound reports incomplete, not success/truncation'
 $missing=Get-RecoveryComponent 'missing' (Join-Path $fixture 'absent') $true 100
 Assert (-not $missing.present -and -not $missing.enumerationFinished) 'Required absent source remains absent'
 $literal=[string][char]0xd800+'x';$encoded=[RecoveryFileMetadata]::LiteralPath($literal);$bytes=[Convert]::FromBase64String($encoded)
 Assert ($bytes.Length -eq 4 -and $bytes[0] -eq 0 -and $bytes[1] -eq 216) 'UTF-16 surrogate code units preserved without replacement'
 $private=Join-Path $fixture 'private';New-RecoveryPrivateDirectory $private
 $acl=Get-Acl $private
 Assert ($acl.AreAccessRulesProtected -and $acl.Owner -match 'Administrators|S-1-5-32-544') 'Private report directory protected and administrator-owned'
 Assert (@($acl.Access | Where-Object {$_.IdentityReference.Value -notmatch 'SYSTEM|Administrators|S-1-5-18|S-1-5-32-544'}).Count -eq 0) 'Only SYSTEM/admin report grants'
 try{New-RecoveryPrivateDirectory $private;throw 'Private output overwrite accepted'}catch{Assert ($_.Exception.Message -eq 'Inventory destination already exists; never overwrite') 'Existing output cannot be overwritten'}
 $report=@{schema='fixture';host='fixture';mode='metadata-only';finishedAt='fixture';reportDirectory='fixture';components=@($component);requiredApiSources=@('fixture')}
 $summary=Get-RecoverySummary $report
 Assert ($summary.inventoryOnly -and -not $summary.fullSystemBackup -and -not $summary.writersFrozen -and -not $summary.encrypted -and $summary.restoreMode -eq 'paused') 'Summary cannot relabel metadata as backup/restore proof'
 Assert (-not (($summary|ConvertTo-Json -Depth 8 -Compress).Contains('literal [name]'))) 'Public summary does not disclose leaf paths/ACLs'
 [Console]::WriteLine(('All '+$checks+' Windows recovery-inventory checks passed; no live source contents/models/network.'))
}finally{
 # Remove ONLY the explicit fixture-owned junction (not its target), then the
 # generated unique test tree. No real recovery/source root is a deletion target.
 if(Test-Path -LiteralPath $junction){[IO.Directory]::Delete($junction)}
 [IO.Directory]::Delete($fixture,$true)
}
