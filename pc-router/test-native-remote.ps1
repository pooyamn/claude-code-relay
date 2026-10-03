param([string]$SourceRoot=$PSScriptRoot)
$ErrorActionPreference='Stop'
# Only parse reviewed source and extract its pure status parser. Never launch an
# agent, install a task, hold a power request, read credentials or use a network.
$runner=$null
foreach($name in @('remote-host.ps1','install-native-remote.ps1','availability-guard.ps1','install-availability-guard.ps1')) {
 $tokens=$null;$errors=$null
 $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $SourceRoot $name),[ref]$tokens,[ref]$errors)
 if($errors.Count){throw ('PowerShell parse failure: '+$name)}
 if($name -eq 'remote-host.ps1'){$runner=$ast}
}
$function=$runner.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Read-ClaudeRemoteStatus'},$true)
if(-not $function){throw 'Native status parser absent'}
. ([ScriptBlock]::Create($function.Extent.Text))
$dot=[char]183
$cases=@(
 @{text='Enable Remote Control? (y/n)';expected=$null},
 @{text='Connected';expected=$null},
 @{text="$dot Connected $dot pc-control";expected='connected'},
 @{text="$dot Connecting $dot pc-control`n$dot Connected $dot pc-control`n$dot Disconnected $dot pc-control";expected='disconnected'},
 @{text="$([char]27)[8A$([char]27)[J$dot Connected $dot pc-control";expected='connected'}
)
foreach($case in $cases){if((Read-ClaudeRemoteStatus $case.text) -ne $case.expected){throw 'Native status parser regression'}}
[Console]::WriteLine('All four scripts parse; five native status-parser checks passed (no credentials/network/models/power changes)')
