$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'configure-vpn-recovery.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'VPN recovery script parse failed'}
$fn=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Read-VpnFailureActions'},$true))
if($fn.Count -ne 1){throw 'Expected pure recovery decoder'}
. ([ScriptBlock]::Create($fn[0].Extent.Text))
$checks=0
function Assert([bool]$Value,[string]$Label){if(-not $Value){throw $Label};$script:checks++}
function Fixture([uint32[]]$Words){$bytes=[Collections.Generic.List[byte]]::new();foreach($w in $Words){$bytes.AddRange([BitConverter]::GetBytes($w))};return ,$bytes.ToArray()}
$old=Read-VpnFailureActions (Fixture @(3600,0,0,3,20,1,10000,1,30000,0,0))
Assert ($old.resetSeconds -eq 3600 -and $old.actions.Count -eq 3 -and $old.actions[-1].type -eq 0) 'Existing third-failure stop is observed accurately'
$new=Read-VpnFailureActions (Fixture @(3600,0,0,3,20,1,10000,1,30000,1,60000))
Assert ($new.actions[-1].type -eq 1 -and $new.actions[-1].delayMs -eq 60000) 'Last action remains a restart with backoff'
$single=Read-VpnFailureActions (Fixture @(86400,0,0,1,20,1,10000))
Assert ($single.resetSeconds -eq 86400 -and $single.actions.Count -eq 1) 'Original single-action service recovery retained accurately'
foreach($b in @((Fixture @(0)),(Fixture @(3600,0,0,17,20)),(Fixture @(3600,0,0,1,19,1,10)),
 (Fixture @(3600,0,0,2,20,1,10)),(Fixture @(3600,0,0,1,20,2,10)),(Fixture @(3600,0,0,1,20,3,10)))){
 $rejected=$false;try{$null=Read-VpnFailureActions $b}catch{$rejected=$true}
 Assert $rejected 'Malformed policy and reboot/command actions fail closed'
}
Assert ($ast.Extent.Text.Contains("[ValidateSet('Inspect','Apply')][string]`$Mode='Inspect'")) 'Default inspection is read-only'
Assert ($ast.Extent.Text.Contains("'restart/10000/restart/30000/restart/60000'")) 'Persistent bounded-backoff policy configured'
[Console]::WriteLine(('All '+$checks+' VPN recovery fixtures passed; no live service changes.'))
