# Offline fixtures execute the ACTUAL startup host guard, not a reimplementation.
# No services, installed files, credentials, model calls or production state.
$ErrorActionPreference='Stop'
$startup=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'router-startup.ps1'),[ref]$null,[ref]$null)
$guard=$startup.Find({param($n)$n -is [Management.Automation.Language.IfStatementAst] -and $n.Clauses[0].Item1.Extent.Text -ceq '$policy.PersistentClaudeWorkers'},$true)
if(-not $guard){throw 'Actual independent-host startup guard missing'}
$repair=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'repair-claude-host-20261024.ps1'),[ref]$null,[ref]$null)
$constructor=$repair.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'New-HostInstallationAttestation'},$true)
if(-not $constructor){throw 'Host deployment attestation constructor missing'}
. ([ScriptBlock]::Create($constructor.Extent.Text))
$dll='A'*64;$exe='B'*64;$old='C'*64;$checks=0
$prior=[pscustomobject]@{dll=$old;exe=$old;generation='old';at='old';extra='preserved'}
$updated=New-HostInstallationAttestation $prior $dll $exe 'reviewed-fixture'
foreach($pass in @(($updated.dll -ceq $dll),($updated.exe -ceq $exe),($updated.extra -ceq 'preserved'),($prior.dll -ceq $old),($updated.generation -ceq 'reviewed-fixture'))){if(-not $pass){throw 'Repair attestation fixture failed'};$checks++}
foreach($bad in @(@{dll='';exe=$exe},@{dll=$dll;exe='bad'},@{dll='z'*64;exe=$exe})){
 $rejected=$false;try{$null=New-HostInstallationAttestation $prior $bad.dll $bad.exe 'reviewed-fixture'}catch{$rejected=$true}
 if(-not $rejected){throw 'Malformed reviewed hash accepted'};$checks++
}
foreach($case in @('updated','stale-both','stale-dll','stale-exe','missing-manifest','wrong-account','wrong-path','wrong-start-mode','host-absent','stopped-host')){
 $observed=& {
  $policy=[pscustomobject]@{PersistentClaudeWorkers=$true};$hostRestarted=$false
  function Get-CimInstance {
   param($ClassName,$Filter)
   if($case -eq 'host-absent'){return $null}
   [pscustomobject]@{State=$(if($case -eq 'stopped-host'){'Stopped'}else{'Running'});StartName=$(if($case -eq 'wrong-account'){'pou'}else{'LocalSystem'});PathName=$(if($case -eq 'wrong-path'){'wrong'}else{'"C:\ProgramData\KhadangClaudeHost\bin\KhadangRouter.exe" --claude-host-service'});StartMode=$(if($case -eq 'wrong-start-mode'){'Auto'}else{'Manual'})}
  }
  function Get-Content {
   param($Path,[switch]$Raw)
   if($Path -cne 'C:\ProgramData\KhadangClaudeHost\installed.json'){throw 'Unexpected fixture read'}
   if($case -eq 'missing-manifest'){throw 'Fixture manifest missing'}
   @{dll=$(if($case -in @('stale-both','stale-dll')){$old}else{$updated.dll});exe=$(if($case -in @('stale-both','stale-exe')){$old}else{$updated.exe})}|ConvertTo-Json -Compress
  }
  function Get-FileHash {
   param($Path)
   if($Path -ceq 'C:\ProgramData\KhadangClaudeHost\bin\KhadangRouter.dll'){return @{Hash=$dll}}
   if($Path -ceq 'C:\ProgramData\KhadangClaudeHost\bin\KhadangRouter.exe'){return @{Hash=$exe}}
   throw 'Unexpected fixture hash read'
  }
  try{. ([ScriptBlock]::Create($guard.Extent.Text));@{accepted=$true;restart=$hostRestarted}}catch{@{accepted=$false;restart=$false}}
 }
 $expected=$case -in @('updated','stopped-host')
 if($observed.accepted -ne $expected -or $observed.restart -ne ($case -eq 'stopped-host')){throw "Actual startup attestation guard regression: $case"};$checks++
}
Write-Output "Passed $checks host-release attestation checks (no services/credentials/network/models)."
