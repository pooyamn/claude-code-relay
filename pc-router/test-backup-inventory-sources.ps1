# Pure source-list checks. No administrator access, live content reads, report
# publication, service/model/task operations, temporary files or network calls.
$ErrorActionPreference='Stop'
$source=Join-Path $PSScriptRoot 'inspect-backup-inventory.ps1'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Inventory parse failed'}
$definitions=@($ast.FindAll({param($node)
 $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-RecoverySources'
},$true))
if($definitions.Count -ne 1){throw 'Exact source-list function required'}
. ([ScriptBlock]::Create($definitions[0].Extent.Text))
$sources=@(Get-RecoverySources 'C:\Users\pou\.migration')
if(@($sources.id | Select-Object -Unique).Count -ne $sources.Count){throw 'Duplicate source identities'}
$expected=@{
 'owner-migration-artifacts'='C:\Users\pou\.migration'
 'kicad-installed-code'='C:\Users\pou\AppData\Local\Programs\KiCad'
 'kicad-user-settings'='C:\Users\pou\AppData\Roaming\kicad'
 'python-installed-code'='C:\Users\pou\AppData\Local\Programs\Python\Python312'
}
foreach($id in $expected.Keys){
 $rows=@($sources | Where-Object id -eq $id)
 if($rows.Count -ne 1 -or $rows[0].path -cne $expected[$id] -or $rows[0].required -ne $true){throw ('Migration/CAD root missing: '+$id)}
}
[Console]::WriteLine('Five source-list checks passed; four PC migration/CAD roots retained. No backup/restore certification.')
