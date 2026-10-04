param([string]$SourceRoot=$PSScriptRoot)
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
# Pure source/fixture checks. Never dot-source the runner or start a native CLI.
$runner=$null
foreach($name in @('codex-wsl-host.ps1','install-codex-wsl-host.ps1')){
 $tokens=$null;$errors=$null
 $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $SourceRoot $name),[ref]$tokens,[ref]$errors)
 if($errors.Count){throw ('PowerShell parse failed: '+$name)}
 if($name -eq 'codex-wsl-host.ps1'){$runner=$ast}
}
$fn=$runner.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Is-AbsentNativeSocket'},$true)
if(-not $fn){throw 'Native absence classifier missing'}
. ([ScriptBlock]::Create($fn.Extent.Text))
$absent="Error: failed to connect to /Users/pouya/.codex/app-server-control/app-server-control.sock`n`nCaused by:`n    No such file or directory (os error 2)"
$cases=@(
 @{name='confirmed absence';output='';error=$absent;expected=$true},
 @{name='CRLF absence';output='';error=$absent.Replace("`n","`r`n");expected=$true},
 @{name='permission failure';output='';error=$absent.Replace('error 2','error 13');expected=$false},
 @{name='foreign socket';output='';error=$absent.Replace('control.sock','other.sock');expected=$false},
 @{name='extra error';output='';error=($absent+'unexpected');expected=$false},
 @{name='empty error';output='';error='';expected=$false},
 @{name='timeout';output='';error='Timeout';expected=$false},
 @{name='ambiguous stdout';output='unexpected';error=$absent;expected=$false}
)
foreach($case in $cases){if((Is-AbsentNativeSocket $case.output $case.error) -ne $case.expected){throw ('Classifier regression: '+$case.name)}}
[Console]::WriteLine('Two scripts parse; eight exact absence fixtures passed; no native/network/credential operations')
