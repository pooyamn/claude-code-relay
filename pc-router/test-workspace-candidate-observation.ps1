$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'capture-workspace-candidates.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Candidate preservation helper parse failed'}
$fn=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Assert-CaptureRouterUnchanged'},$true))
if($fn.Count -ne 1){throw 'Expected pure observation invariant'}
. ([ScriptBlock]::Create($fn[0].Extent.Text))
$before=@{serviceState='Stopped';code='same-code';policy='same-policy';nativeLinuxPid=1;nativeWindowsPid=2;connectedClaude=0}
$after=$before.Clone();$after.nativeLinuxPid=99
Assert-CaptureRouterUnchanged $before $after
$checks=1
foreach($field in @('serviceState','code','policy')){
 $after=$before.Clone();$after[$field]='changed';$rejected=$false
 try{Assert-CaptureRouterUnchanged $before $after}catch{$rejected=$true}
 if(-not $rejected){throw 'Service/code/policy transition accepted'};$checks++
}
$before.serviceState='Running';$before.connectedClaude=7
Assert-CaptureRouterUnchanged $before $before;$checks++
foreach($field in @('nativeLinuxPid','nativeWindowsPid','connectedClaude')){
 $after=$before.Clone();$after[$field]=99;$rejected=$false
 try{Assert-CaptureRouterUnchanged $before $after}catch{$rejected=$true}
 if(-not $rejected){throw 'Live native generation transition accepted'};$checks++
}
[Console]::WriteLine(('All '+$checks+' preservation-observation fixtures passed; no live configuration changes.'))
