param([string]$SourceRoot=$PSScriptRoot)
$ErrorActionPreference='Stop'
# Only parse reviewed source and extract its pure status parser. Never launch an
# agent, install a task, hold a power request, read credentials or use a network.
$runner=$null
$names=@('remote-host.ps1','install-native-remote.ps1','availability-guard.ps1','install-availability-guard.ps1','configure-autologon.ps1','router-startup.ps1','install-router-startup.ps1','test-recovery.ps1','test-native-remote-hidden.ps1','quiet-native-remote-tasks-20261111.ps1')
$installer=$null
foreach($name in $names) {
 $tokens=$null;$errors=$null
 $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $SourceRoot $name),[ref]$tokens,[ref]$errors)
 if($errors.Count){throw ('PowerShell parse failure: '+$name)}
 if($name -eq 'remote-host.ps1'){$runner=$ast}
 if($name -eq 'install-native-remote.ps1'){$installer=$ast.Extent.Text}
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
if($installer -notmatch 'New-ScheduledTaskAction -Execute \$windowless' -or $installer -notmatch 'System32\\wscript\.exe' -or $installer -notmatch 'remote-host-hidden\.vbs'){throw 'Native remote tasks must use the windowless launcher'}
$launcher=[IO.File]::ReadAllText((Join-Path $SourceRoot 'remote-host-hidden.vbs'))
if($launcher -notmatch 'shell\.Run\(command, 0, True\)' -or $launcher -notmatch 'WScript\.Quit result' -or
 $launcher -notmatch 'provider <> "Claude" And provider <> "Codex"' -or $launcher -notmatch '-WindowStyle Hidden'){throw 'Hidden child, strict provider and exit-code propagation required'}
[Console]::WriteLine(('All '+$names.Count+' scripts parse; five native status-parser and two windowless-launcher checks passed (no credentials/network/models/power changes)'))
