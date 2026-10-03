# Parse sources and invoke only the pure evaluator. No target inspection or writes.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'inspect-agent-host.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Host inspector parse failure'}
$definition=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-AgentHostReadiness'},$true)
if(-not $definition){throw 'Pure host evaluator absent'}
. ([ScriptBlock]::Create($definition.Extent.Text))
$fixture=@{hypervisorPresent=$true;virtualizationFirmwareEnabled=$true;slat=$false;vmMonitor=$false;dep=$true;hyperVModule=$false;features=@{};vmmsStatus='Absent'}
$result=Get-AgentHostReadiness $fixture
if($result.hardwareObservation -notlike 'ExistingHypervisor*' -or $result.managementReady){throw 'Existing hypervisor misclassified from masked CPU properties'}
if(@($result.missingOrUnverifiedFeatures).Count -ne 3){throw 'Missing features not retained'}
$fixture.hypervisorPresent=$false;$result=Get-AgentHostReadiness $fixture
if($result.hardwareObservation -notlike 'ReportedPrerequisiteMissing*'){throw 'Missing bare-host prerequisite hidden'}
$fixture.slat=$true;$fixture.vmMonitor=$true;$result=Get-AgentHostReadiness $fixture
if($result.hardwareObservation -notlike 'ReportedPrerequisitesPresent*'){throw 'Bare-host observations lost'}
foreach($name in @('Microsoft-Hyper-V-Hypervisor','Microsoft-Hyper-V-Services','Microsoft-Hyper-V-Management-PowerShell')){$fixture.features[$name]='Enabled'}
$fixture.hyperVModule=$true;$fixture.vmmsStatus='Running';$result=Get-AgentHostReadiness $fixture
if(-not $result.managementReady -or $result.liveRoleAccepted -or $result.changesApplied -or $result.modelsStarted){throw 'Management prerequisites confused with deployment/role acceptance'}
$fixture.features['Microsoft-Hyper-V-Services']='Unknown';$result=Get-AgentHostReadiness $fixture
if($result.managementReady){throw 'Unknown feature granted readiness'}
$fixture.slat='false';$denied=$false
try{Get-AgentHostReadiness $fixture | Out-Null}catch{$denied=$true}
if(-not $denied){throw 'Untyped observation accepted'}
$commands=$ast.FindAll({param($node) $node -is [Management.Automation.Language.CommandAst]},$true)
foreach($command in $commands){
 if($command.GetCommandName() -match '^(Enable|Disable|New|Set|Start|Stop|Restart|Register|Unregister|Remove|Add|Install|Import|Invoke|Export|Write)-'){
  throw ('Mutation/indirect execution in read-only inspector: '+$command.GetCommandName())
 }
}
[Console]::WriteLine('8 host-readiness/readonly checks passed; no target inspection, credentials, models, feature changes or reboot')
