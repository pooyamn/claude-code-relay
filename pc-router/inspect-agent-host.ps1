# Read-only host readiness, NOT an installer or deployment authorization gate.
# No WSL registration, VM creation, feature enablement, task, credential, model,
# network configuration or reboot operation is available in this script.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
function Get-AgentHostReadiness([hashtable]$Snapshot){
 foreach($name in @('hypervisorPresent','virtualizationFirmwareEnabled','slat','vmMonitor','dep','hyperVModule')){
  if($Snapshot[$name] -isnot [bool]){throw ('Missing typed host observation: '+$name)}
 }
 $hardware='Unknown'
 if($Snapshot.hypervisorPresent){
  # Hyper-V masks bare-hardware discovery; false SLAT here is not a diagnosis.
  $hardware='ExistingHypervisor; independent VM boot still required'
 }elseif($Snapshot.virtualizationFirmwareEnabled -and $Snapshot.slat -and $Snapshot.vmMonitor -and $Snapshot.dep){
  $hardware='ReportedPrerequisitesPresent; independent VM boot still required'
 }else{$hardware='ReportedPrerequisiteMissing; investigate before installation'}
 $required=@('Microsoft-Hyper-V-Hypervisor','Microsoft-Hyper-V-Services','Microsoft-Hyper-V-Management-PowerShell')
 $missing=@($required | Where-Object {$Snapshot.features[$_] -ne 'Enabled'})
 [ordered]@{
  schema='ccrelay.agent_host_readiness.v1';mode='read-only';hardwareObservation=$hardware
  missingOrUnverifiedFeatures=$missing;hyperVModuleAvailable=$Snapshot.hyperVModule
  managementReady=($missing.Count -eq 0 -and $Snapshot.hyperVModule -and $Snapshot.vmmsStatus -eq 'Running')
  liveRoleAccepted=$false;changesApplied=$false;modelsStarted=$false
  remaining=@('Owner topology review','Protected host/guest management and real-token denial tests',
   'Measured guest resource profile','Native app/subscription continuity','Full-system restore and boot recovery')
 }
}
$computer=Get-CimInstance Win32_ComputerSystem
$cpu=@(Get-CimInstance Win32_Processor)
if($cpu.Count -ne 1){throw 'Expected one measured processor package; inspect unsupported target'}
$os=Get-CimInstance Win32_OperatingSystem
$features=@{}
try{
 Get-WindowsOptionalFeature -Online | Where-Object {$_.FeatureName -like 'Microsoft-Hyper-V*' -or $_.FeatureName -eq 'VirtualMachinePlatform'} |
  ForEach-Object {$features[$_.FeatureName]=$_.State.ToString()}
}catch{
 # Read denial is unknown, never permission to install or a green readiness.
 foreach($name in @('Microsoft-Hyper-V-Hypervisor','Microsoft-Hyper-V-Services','Microsoft-Hyper-V-Management-PowerShell')){$features[$name]='Unknown'}
}
$vmms=Get-Service vmms -ErrorAction SilentlyContinue
$snapshot=@{
 hypervisorPresent=$computer.HypervisorPresent
 virtualizationFirmwareEnabled=$cpu[0].VirtualizationFirmwareEnabled
 slat=$cpu[0].SecondLevelAddressTranslationExtensions
 vmMonitor=$cpu[0].VMMonitorModeExtensions;dep=$os.DataExecutionPrevention_Available
 features=$features;hyperVModule=[bool](Get-Module -ListAvailable Hyper-V)
 vmmsStatus=$(if($vmms){$vmms.Status.ToString()}else{'Absent'})
}
$report=Get-AgentHostReadiness $snapshot
$report.at=[DateTime]::UtcNow.ToString('o');$report.host=$computer.Name;$report.os=$os.Caption
$report.cpu=$cpu[0].Name;$report.cores=$cpu[0].NumberOfCores;$report.logicalProcessors=$cpu[0].NumberOfLogicalProcessors
$report.usableMemoryGB=[math]::Round($computer.TotalPhysicalMemory/1GB,2)
$report.availableMemoryGB=[math]::Round($os.FreePhysicalMemory/1MB,2)
$report.observations=$snapshot
$report.pendingRestart=@{
 componentServicing=Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending'
 windowsUpdate=Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired'
}
[Console]::WriteLine(($report | ConvertTo-Json -Depth 6 -Compress))
