param([string]$SourceRoot=$PSScriptRoot)
# Offline fixtures: extract the actual recovery predicate without executing
# the deployment, providers, scheduler, credentials, SQL or Telegram.
$ErrorActionPreference='Stop';$oldCode='reviewed-code';$oldPolicy='reviewed-policy'
$errors=$null;$tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $SourceRoot 'deploy-codex-astra62-20261117.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Deployment parse failed'}
$function=$ast.Find({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'CanRestoreUnchangedObserver'},$true)
if(-not $function){throw 'Recovery predicate missing'}
. ([scriptblock]::Create($function.Extent.Text))
$cases=@(
 @{receipt=@{success=$false;lifecycleStarted=$false};staged=$false;code=$oldCode;policy=$oldPolicy;expected=$true},
 @{receipt=@{success=$false};staged=$false;code=$oldCode;policy=$oldPolicy;expected=$false},
 @{receipt=@{success=$false;lifecycleStarted=$true};staged=$false;code=$oldCode;policy=$oldPolicy;expected=$false},
 @{receipt=@{success=$true;lifecycleStarted=$false};staged=$false;code=$oldCode;policy=$oldPolicy;expected=$false},
 @{receipt=@{success=$false;lifecycleStarted=$false};staged=$true;code=$oldCode;policy=$oldPolicy;expected=$false},
 @{receipt=@{success=$false;lifecycleStarted=$false};staged=$false;code='changed';policy=$oldPolicy;expected=$false},
 @{receipt=@{success=$false;lifecycleStarted=$false};staged=$false;code=$oldCode;policy='changed';expected=$false}
)
foreach($case in $cases){if((CanRestoreUnchangedObserver $case.receipt $case.staged $case.code $case.policy) -ne $case.expected){throw 'Recovery predicate regression'}}
'Passed 7 pre-lifecycle recovery checks (no native/network/credential operations).'
