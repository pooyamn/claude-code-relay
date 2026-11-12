param([ValidateSet('Apply','Verify')][string]$Phase='Apply')
# Owner-approved action-only update. Keep task principal, triggers, recovery,
# ACL and running instances; never stop a task, service or native process.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\OracovaNativeRemote';$release=$root+'\quiet-native-remote-20261111'
$launcher=$root+'\remote-host-hidden.vbs';$digest='165C464113F31742839FE3261329ABAEE0D4C45B568746DBFBEEDB44D547390F'
$ownerSid='S-1-5-21-71459778-1164188569-2276148161-1001'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed owner administrator maintenance required'}
if((Get-Item $root).Attributes -band [IO.FileAttributes]::ReparsePoint -or -not (Get-Acl $root).AreAccessRulesProtected){throw 'Protected literal remote root required'}
$helper='C:\Users\pou\AppData\Local\Temp\deploy-switch-isolation-20261014.ps1'
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helper changed'}
$a=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name0 in @('Protect','Save')){$d0=$a.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name0},$true);. ([scriptblock]::Create($d0.Extent.Text))}
$scheduler=New-Object -ComObject Schedule.Service;$scheduler.Connect();$folder=$scheduler.GetFolder('\')
function WithoutActions([string]$Xml){
 $document=[xml]$Xml;$node=$document.DocumentElement.SelectSingleNode('*[local-name()="Actions"]')
 if(-not $node){throw 'Exact task actions missing'};$null=$node.ParentNode.RemoveChild($node);return $document.OuterXml
}
function Instances($Task){return @($Task.GetInstances(0)|ForEach-Object {$_.InstanceGuid})}
function Owner($Principal){
 if($Principal.UserId -match '^S-1-') {return $Principal.UserId}
 return ([Security.Principal.NTAccount]::new($Principal.UserId)).Translate([Security.Principal.SecurityIdentifier]).Value
}
if($Phase -eq 'Apply'){
 if((Test-Path ($release+'\before.json')) -or (Test-Path $launcher)){throw 'Existing attempt; inspect, never blindly overwrite'}
 $source='C:\Users\pou\AppData\Local\OracovaDiagnostics\remote-host-hidden-20261111.vbs'
 if((Get-FileHash $source).Hash -ne $digest){throw 'Tested launcher changed'}
 $targets=@(foreach($provider0 in @('Claude','Codex')){
  $task0=$folder.GetTask('Oracova-'+$provider0+'Remote');$definition0=$task0.Definition
  if(-not $task0.Enabled -or $definition0.Actions.Count -ne 1 -or (Owner $definition0.Principal) -ne $ownerSid -or $definition0.Principal.LogonType -ne 3 -or $definition0.Principal.RunLevel -ne 0){throw 'Exact enabled limited interactive-owner tasks required'}
  $action0=$definition0.Actions.Item(1)
  $expected0='-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$root+'\remote-host.ps1" -Provider '+$provider0
  if($action0.Path -ine 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -or $action0.Arguments -cne $expected0){throw 'Task action changed; preserve'}
  @{name=$task0.Name;provider=$provider0;xml=$task0.Xml;unmodified=(WithoutActions $task0.Xml);acl=$task0.GetSecurityDescriptor(7);working=$action0.WorkingDirectory;instances=(Instances $task0)}
 })
 if(-not (Test-Path $release)){New-Item -ItemType Directory $release|Out-Null;Protect $release $true}
 Copy-Item $source ($release+'\launcher.vbs');Protect ($release+'\launcher.vbs')
 if((Get-FileHash ($release+'\launcher.vbs')).Hash -ne $digest){throw 'Sealed launcher differs'}
 $runnerHash=(Get-FileHash ($root+'\remote-host.ps1')).Hash
 Save ($release+'\before.json') @{at=[DateTimeOffset]::UtcNow.ToString('o');ownerApproval='Pouya: Yeah, make the Claude/Codex remote tasks launch hidden';tasks=$targets;runnerSha256=$runnerHash;modelLaunches=0}
 Copy-Item ($release+'\launcher.vbs') $launcher;Set-Acl $launcher (Get-Acl ($root+'\remote-host.ps1'))
 if((Get-FileHash $launcher).Hash -ne $digest){throw 'Installed launcher differs'}
 foreach($target0 in $targets){
  $current0=$folder.GetTask($target0.name)
  if($current0.Xml -cne $target0.xml -or $current0.GetSecurityDescriptor(7) -cne $target0.acl){throw 'Task changed during review'}
  $definition0=$current0.Definition;$definition0.Actions.Clear();$action0=$definition0.Actions.Create(0)
  $action0.Path='C:\Windows\System32\wscript.exe';$action0.Arguments='//B //NoLogo "'+$launcher+'" '+$target0.provider
  if($target0.working){$action0.WorkingDirectory=$target0.working}
  # UPDATE | DONT_ADD_PRINCIPAL_ACE | IGNORE_REGISTRATION_TRIGGERS.
  $null=$folder.RegisterTaskDefinition($target0.name,$definition0,0x34,$definition0.Principal.UserId,$null,3,$target0.acl)
  Save ($release+'\updated-'+$target0.provider+'.json') @{at=[DateTimeOffset]::UtcNow.ToString('o');task=$target0.name;taskStopped=$false;nativeProcessesStopped=0}
 }
}
$before=Get-Content ($release+'\before.json') -Raw -Encoding UTF8|ConvertFrom-Json
if((Get-FileHash $launcher).Hash -ne $digest -or (Get-FileHash ($root+'\remote-host.ps1')).Hash -ne $before.runnerSha256){throw 'Protected launch artifacts changed'}
$verified=@(foreach($target0 in $before.tasks){
 $task0=$folder.GetTask($target0.name);$definition0=$task0.Definition;$action0=$definition0.Actions.Item(1)
 if(-not $task0.Enabled -or (WithoutActions $task0.Xml) -cne $target0.unmodified -or $task0.GetSecurityDescriptor(7) -cne $target0.acl -or
  $definition0.Actions.Count -ne 1 -or $action0.Path -ine 'C:\Windows\System32\wscript.exe' -or $action0.Arguments -cne ('//B //NoLogo "'+$launcher+'" '+$target0.provider)){throw 'Action-only task preservation verification failed'}
 $instances0=Instances $task0
 if($target0.provider -eq 'Codex'){foreach($instance0 in $target0.instances){if($instance0 -notin $instances0){throw 'Existing Codex task instance changed; inspect'}}}
 @{task=$target0.name;windowless=$true;settingsAndTriggersPreserved=$true;principalAndAclPreserved=$true;instances=$instances0;lastRun=$task0.LastRunTime;lastResult=$task0.LastTaskResult;nextRun=$task0.NextRunTime}
})
Save ($release+'\verified.json') @{at=[DateTimeOffset]::UtcNow.ToString('o');tasks=$verified;nativeProcessesStopped=0;nativeInputsReplayed=0;authenticationChanged=$false}
@{verified=$true;tasks=$verified;nativeProcessesStopped=0;authenticationChanged=$false}|ConvertTo-Json -Depth 7 -Compress
