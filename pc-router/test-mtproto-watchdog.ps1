$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'mtproto\watchdog.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Parse failed'}
$fn=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Choose-Recovery'},$true))
if($fn.Count -ne 1){throw 'Pure recovery decision missing'}
. ([ScriptBlock]::Create($fn[0].Extent.Text))
$checks=0
function Assert([bool]$Value,[string]$Label){if(-not $Value){throw $Label};$script:checks++}
Assert ((Choose-Recovery 'Stopped' $false $false $false 1 9999 9999) -eq 'start') 'Clean stop is automatically started'
Assert ((Choose-Recovery 'Start Pending' $false $false $true 9 9999 9999) -eq 'wait') 'Do not race SCM transition'
Assert ((Choose-Recovery 'Running' $false $false $true 9 100 9999) -eq 'wait') 'Allow startup grace'
Assert ((Choose-Recovery 'Running' $true $true $false 0 500 9999) -eq 'healthy') 'Authenticated resPQ proves health'
Assert ((Choose-Recovery 'Running' $true $false $false 9 500 9999) -eq 'network-outage') 'Upstream outage does not restart healthy local server'
Assert ((Choose-Recovery 'Running' $false $false $true 2 500 9999) -eq 'suspect') 'Transient failure is not a restart'
Assert ((Choose-Recovery 'Running' $false $false $true 3 500 9999) -eq 'restart') 'Persistently hung local server is restarted'
Assert ((Choose-Recovery 'Running' $true $false $true 3 500 9999) -eq 'restart') 'Broken proxy forwarding with reachable DC is restarted'
Assert ((Choose-Recovery 'Running' $false $false $true 9 500 299) -eq 'suspect') 'Five-minute restart cooldown'
foreach($name in @('always-on-policy.ps1','install-mtproto-watchdog.ps1','shutdown-guard-start.ps1')){
 $t=$null;$e=$null;$null=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $name),[ref]$t,[ref]$e)
 Assert ($e.Count -eq 0) ($name+' parses')
}
Assert (-not $ast.Extent.Text.Contains('shutdown.exe')) 'Watchdog never reboots the PC'
Assert ($ast.Extent.Text.Contains("`$statePath+'.previous'")) 'Atomic receipt replacement has a real backup path on Windows PowerShell'
# Exercise actual Windows/.NET replacement, not just the first-run Move path.
$temp=Join-Path ([IO.Path]::GetTempPath()) ('mtproto-state-test-'+[Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($temp)|Out-Null
try {
 $state=Join-Path $temp 'state.json'
 [IO.File]::WriteAllText($state,'0')
 foreach($i in @(1,2,3)){
  [IO.File]::WriteAllText($state+'.new',[string]$i)
  [IO.File]::Replace($state+'.new',$state,$state+'.previous')
  Assert ([IO.File]::ReadAllText($state) -eq [string]$i) 'Repeated receipt write succeeds'
  Assert ([IO.File]::ReadAllText($state+'.previous') -eq [string]($i-1)) 'Previous receipt retained'
 }
} finally {
 # Exact ephemeral files created above; never touch a user data directory.
 foreach($f in @($state,($state+'.new'),($state+'.previous'))){if([IO.File]::Exists($f)){[IO.File]::Delete($f)}}
 [IO.Directory]::Delete($temp)
}
[Console]::WriteLine(('All '+$checks+' watchdog checks passed; no live changes.'))
