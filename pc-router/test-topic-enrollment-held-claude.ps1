$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'enroll-codex-topic-fast.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Enrollment script parse failed'}
$function=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'DisconnectedActiveClaude'},$true)
if(-not $function){throw 'Readiness predicate missing'}
. ([ScriptBlock]::Create($function.Extent.Text))
$held=@{binding=@{Backend='claude';ThreadId='held-dut'};claudeConnected=$false;held=$true}
$active=@{binding=@{Backend='claude';ThreadId='active'};claudeConnected=$true;held=$false}
if(@(DisconnectedActiveClaude @($held,$active) @('held-dut')).Count){throw 'Pre-existing scoped hold must not block another topic'}
$active.claudeConnected=$false
if(@(DisconnectedActiveClaude @($held,$active) @('held-dut')).Count -ne 1){throw 'Disconnected healthy route must block enrollment'}
$active.held=$true
if(@(DisconnectedActiveClaude @($held,$active) @('held-dut')).Count -ne 1){throw 'A new hold after restart must not be exempted'}
if(@(DisconnectedActiveClaude @($held) @()).Count -ne 1){throw 'An unrecorded hold must not be exempted'}
@{passed=$true;cases=4;topicsCreated=0;holdsChanged=0}|ConvertTo-Json -Compress
