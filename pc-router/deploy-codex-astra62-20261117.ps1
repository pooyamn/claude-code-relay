param([Parameter(Mandatory=$true)][ValidateSet('Prepare','Run')][string]$Phase,
 [ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$ManifestSha256)
# Exact owner-requested coordinated release. Run waits for this controller's
# final answer and all other work to settle; never interrupts or replays work.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote'
$release=$native+'\codex-astra62-20261117'
$source='C:\Users\pou\AppData\Local\Temp\khadang-astra62-20261117-stage'
$candidate='C:\Users\pou\AppData\Local\Temp\khadang-astra62-20261117-candidate'
$oldCode='C6BAB770BDC160B62CE36A279E8EBF4039852CF7314A088D15CA5EB6F1DC6B45'
$newCode='DAF946D30672C94C0797E6DECE9CA5D7BAA8C5C46CD62792C01CE61EE459457C'
$oldPolicy='CEDA45FF8D4B115F8729F4A02D390A2278A99E86F3612DD530D12167D4212109'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Owner maintenance administrator required'}
$helper='C:\Users\pou\AppData\Local\Temp\deploy-switch-isolation-20261014.ps1'
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helper changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Bindings','Unknown','HostIdentity','ExactTask')){
 $definition=$ast.Find({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $name},$true)
 . ([scriptblock]::Create($definition.Extent.Text))
}
LoadSql ($native+'\inspect-state.ps1') 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
function Status{Get-Content ($root+'\state\status.json') -Raw|ConvertFrom-Json}
function ServiceMode([bool]$Probe){
 $mode=if($Probe){'--probe-service'}else{'--service'}
 $service=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $change=Invoke-CimMethod -InputObject $service -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" '+$mode+' --config "'+$root+'\config.json"');StartMode='Manual'}
 if($change.ReturnValue){throw 'Service mode rejected'}
}
function StopObserver{Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30))}
function ReplaceFile([string]$Source,[string]$Destination){
 $temporary=$Destination+'.astra62-20261117';Copy-Item $Source $temporary;Set-Acl $temporary (Get-Acl $Destination)
 [IO.File]::Replace($temporary,$Destination,[System.Management.Automation.Language.NullString]::Value)
}
function OwnerTask([string]$Name){
 $path='C:\Users\pou\.native-remote\astra62-'+$Name.ToLowerInvariant()+'.json'
 if(Test-Path $path){throw 'Existing owner operation receipt; do not repeat'}
 Start-ScheduledTask -TaskName ('Oracova-CodexAstra62-'+$Name)
 $deadline=[DateTimeOffset]::UtcNow.AddSeconds(100)
 while(-not (Test-Path $path) -and [DateTimeOffset]::UtcNow -lt $deadline){Start-Sleep -Milliseconds 500}
 if(-not (Test-Path $path)){throw 'Owner operation has no receipt; no replay'}
 $value=Get-Content $path -Raw|ConvertFrom-Json
 Save ($release+'\owner-'+$Name.ToLowerInvariant()+'.json') $value
 if(-not $value.success){throw ('Owner operation failed: '+$value.error)}
 return $value
}
if($Phase -eq 'Prepare'){
 if(Test-Path $release){throw 'Existing deployment: inspect instead of overwriting'}
 if((Get-FileHash ($root+'\bin\KhadangRouter.dll')).Hash -ne $oldCode -or (Get-FileHash ($root+'\config.json')).Hash -ne $oldPolicy -or
  (Get-FileHash ($candidate+'\KhadangRouter.dll')).Hash -ne $newCode){throw 'Expected reviewed production/candidate required'}
 if(-not $ManifestSha256 -or (Get-FileHash ($source+'\manifest.json')).Hash -ne $ManifestSha256){throw 'Reviewed source-manifest digest required'}
 $manifest=Get-Content ($source+'\manifest.json') -Raw|ConvertFrom-Json
 foreach($entry in $manifest.PSObject.Properties){if((Get-FileHash ($source+'\'+$entry.Name)).Hash -ne $entry.Value){throw 'Staged source bytes changed'}}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 Copy-Item ($source+'\*') $release -Recurse
 New-Item -ItemType Directory ($release+'\candidate')|Out-Null
 Copy-Item ($candidate+'\*') ($release+'\candidate') -Recurse
 Get-ChildItem $release -Recurse -Force|ForEach-Object {Protect $_.FullName $_.PSIsContainer}
 # The release evidence/configuration remains admin-only. Grant the limited
 # owner only literal code reads plus ancestor lookup, never inherited access.
 $ownerSid=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
 $lookup=[Security.AccessControl.FileSystemRights]::Traverse -bor [Security.AccessControl.FileSystemRights]::ReadAttributes
 $acl=Get-Acl $release;$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($ownerSid,$lookup,'Allow'));Set-Acl $release $acl
 foreach($path in @('pc_native_stdio.py','upgrade_codex_astra62_20261117.py','upgrade-codex-owner-20261117.ps1',
   'relay_core','relay_core\__init__.py','relay_core\contracts.py','relay_core\identity.py','relay_core\native_rpc.py','relay_core\native_ws.py')){
  $literal=$release+'\'+$path;$acl=Get-Acl $literal
  $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($ownerSid,'ReadAndExecute','Allow'));Set-Acl $literal $acl
 }
 foreach($operation in @('Preflight','Upgrade','Verify')){
  $task='Oracova-CodexAstra62-'+$operation
  if(Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue){throw 'Task already exists'}
  $principal=New-ScheduledTaskPrincipal -UserId 'S-1-5-21-71459778-1164188569-2276148161-1001' -LogonType Interactive -RunLevel Limited
  $action=New-ScheduledTaskAction -Execute 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -Argument ('-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+$release+'\upgrade-codex-owner-20261117.ps1" -Phase '+$operation)
  $settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
  Register-ScheduledTask -TaskName $task -Principal $principal -Action $action -Settings $settings|Out-Null
  (ExactTask $task).SetSecurityDescriptor('O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)',0x10)
 }
 Save ($release+'\prepared.json') @{code=$newCode;previous=$oldCode;policy=$oldPolicy;at=[DateTimeOffset]::UtcNow.ToString('o')}
 'PREPARED: production daemon and router still running';return
}
if(Test-Path ($release+'\started.json')){throw 'Existing deployment start: reconcile, never replay'}
try{
 $deadline=[DateTimeOffset]::UtcNow.AddMinutes(15)
 do{
  $status=Status
  $pending=[RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('received','dispatching') LIMIT 1")
  $attempting=[RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText' LIMIT 1")
  $idle=[DateTimeOffset]$status.at -gt [DateTimeOffset]::UtcNow.AddSeconds(-30) -and
   -not @($status.nativeSessions|Where-Object busy).Count -and -not $pending.Length -and -not $attempting.Length
  if($idle){break};Start-Sleep -Seconds 2
 }while([DateTimeOffset]::UtcNow -lt $deadline)
 if(-not $idle){throw 'Work did not become idle; no live systems changed'}
 if((Get-FileHash ($root+'\bin\KhadangRouter.dll')).Hash -ne $oldCode -or (Get-FileHash ($root+'\config.json')).Hash -ne $oldPolicy){throw 'Production changed since preparation'}
 $tasks=@{};foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog','Oracova-CodexWslRemote')){$tasks[$name]=(ExactTask $name).Enabled}
 Save ($release+'\before.json') @{status=$status;tasks=$tasks;bindings=(Bindings);unknown=(Unknown);host=(HostIdentity);at=[DateTimeOffset]::UtcNow.ToString('o')}
 Copy-Item ($root+'\config.json') ($release+'\previous-config.json');Protect ($release+'\previous-config.json')
 Copy-Item ($root+'\state\probe.json') ($release+'\previous-probe.json');Protect ($release+'\previous-probe.json')
 Copy-Item ($root+'\bin\KhadangRouter.dll') ($release+'\previous-router.dll');Protect ($release+'\previous-router.dll')
 foreach($name in $tasks.Keys){(ExactTask $name).Enabled=$false}
 Save ($release+'\started.json') @{at=[DateTimeOffset]::UtcNow.ToString('o')}
 StopObserver
 $lease=[IO.File]::Open($root+'\state\exclusive.lock','Open','ReadWrite','None')
 try{
  if([RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('received','dispatching') LIMIT 1").Length -or
   [RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText' LIMIT 1").Length){throw 'Work arrived during fencing; no native restart'}
  $upgraded=OwnerTask 'Upgrade'
  $policy=Get-Content ($root+'\config.json') -Raw|ConvertFrom-Json
  $connector=$policy.LinuxCodex.PackageRoot+'\pc_native_stdio.py'
  $observer=$native+'\codex-wsl-observer-CgBorX\pc_native_stdio.py'
  foreach($destination in @($connector,$observer)){
   Copy-Item $destination ($release+'\previous-'+$(if($destination -eq $connector){'connector'}else{'observer'})+'.py')
   ReplaceFile ($release+'\pc_native_stdio.py') $destination
  }
  Copy-Item ($native+'\codex-wsl-host.ps1') ($release+'\previous-host.ps1')
  ReplaceFile ($release+'\codex-wsl-host.ps1') ($native+'\codex-wsl-host.ps1')
  $policy.LinuxCodex.FileSha256.'pc_native_stdio.py'=(Get-FileHash $connector).Hash
  Save ($root+'\config.json') $policy
  ReplaceFile ($release+'\candidate\KhadangRouter.dll') ($root+'\bin\KhadangRouter.dll')
  Save ($release+'\staged.json') @{code=$newCode;policy=(Get-FileHash ($root+'\config.json')).Hash;nativeVersion=$upgraded.version.appServerVersion;at=[DateTimeOffset]::UtcNow.ToString('o')}
 }finally{$lease.Dispose()}
 ServiceMode $true;Start-Service KhadangRouter
 $stage=Get-Content ($release+'\staged.json') -Raw|ConvertFrom-Json
 $deadline=[DateTimeOffset]::UtcNow.AddSeconds(90);$proof=$null
 try{
  do{
   Start-Sleep -Milliseconds 500
   $proof=Get-Content ($root+'\state\probe.json') -Raw|ConvertFrom-Json
   if($proof.policySha256 -eq $stage.policy -and $proof.routerSha256 -eq $newCode -and [DateTimeOffset]$proof.testedAt -gt [DateTimeOffset]$stage.at){break}
  }while([DateTimeOffset]::UtcNow -lt $deadline)
 }finally{StopObserver}
 if(-not $proof.verified -or -not $proof.credentialAndCodeDenied -or -not $proof.nativeLinuxCommandOwnerVerified -or
  -not $proof.nativeWindowsSandboxVerified -or $proof.routerSha256 -ne $newCode -or $proof.policySha256 -ne $stage.policy -or
  $proof.modelInference -or $proof.telegramPolling -or [DateTimeOffset]$proof.testedAt -le [DateTimeOffset]$stage.at){throw 'New native security probe failed; preserve fence'}
 Save ($release+'\generic-proof.json') $proof
 $prior=Get-Content ($release+'\previous-probe.json') -Raw|ConvertFrom-Json
 foreach($field in @('nativeLinuxClaudeLaunchVerified','nativeLinuxClaudeToolOwnerVerified','nativeLinuxClaudeContinuityVerified')){if(-not $prior.$field){throw 'Previous independent Claude acceptance missing'}}
 foreach($field in @('nativeLinuxClaudeLaunchVerified','nativeLinuxClaudeToolOwnerVerified','nativeLinuxClaudeContinuityVerified','nativeLinuxClaudeAcceptance')){$proof|Add-Member $field $prior.$field -Force}
 $proof|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Only Linux Codex package identity changed; independent Claude host, binaries, policy and connector unchanged';modelTestsRerun=$false} -Force
 Save ($root+'\state\probe.json') $proof
 ServiceMode $false;Start-Service KhadangRouter
 $deadline=[DateTimeOffset]::UtcNow.AddSeconds(90)
 do{
  Start-Sleep -Seconds 1;$current=Status
  $connected=@($current.nativeSessions|Where-Object {$_.binding.Backend -eq 'codex' -and $_.binding.Runtime -eq 'linux' -and -not $_.nativeConnected}).Count -eq 0
  if([DateTimeOffset]$current.at -gt [DateTimeOffset]$stage.at -and $connected){break}
 }while([DateTimeOffset]::UtcNow -lt $deadline)
 if(-not $connected -or (Bindings) -cne (Get-Content ($release+'\before.json') -Raw|ConvertFrom-Json).bindings -or
  (Unknown) -cne (Get-Content ($release+'\before.json') -Raw|ConvertFrom-Json).unknown -or
  (HostIdentity) -cne (Get-Content ($release+'\before.json') -Raw|ConvertFrom-Json).host){throw 'Connected continuity and unchanged custody not confirmed'}
 $verified=OwnerTask 'Verify'
 foreach($name in $tasks.Keys){(ExactTask $name).Enabled=[bool]$tasks[$name]}
 # Restart only the deterministic owner supervisor, not the daemon it observes.
 $hostTask=ExactTask 'Oracova-CodexWslRemote'
 $definition=$hostTask.Definition;$security=$hostTask.GetSecurityDescriptor(7)
 if($definition.Actions.Count -ne 1 -or $definition.Actions.Item(1).Path -ine 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'){throw 'Expected existing owner supervisor action'}
 if($definition.Actions.Item(1).Arguments -notmatch '-WindowStyle\s+Hidden'){
  $definition.Actions.Item(1).Arguments='-WindowStyle Hidden '+$definition.Actions.Item(1).Arguments
  $null=$script:taskScheduler.GetFolder('\').RegisterTaskDefinition('Oracova-CodexWslRemote',$definition,6,$null,$null,3,$security)
  $hostTask=ExactTask 'Oracova-CodexWslRemote'
 }
 if($hostTask.State -eq 4){$hostTask.Stop(0)}
 Start-ScheduledTask -TaskName Oracova-CodexWslRemote
 Save ($release+'\verified.json') @{at=[DateTimeOffset]::UtcNow.ToString('o');version='0.169.0';model='gpt-6.2-astra';threads=$verified.native.threads;bindingsPreserved=$true;unknownPreserved=$true;claudeHostPreserved=$true;inputReplay=0}
 'VERIFIED: remote model picker and eight migrated topics; same histories, bindings and independent Claude host'
}catch{
 Save ($release+'\failure-'+[DateTime]::UtcNow.ToString('yyyyMMddHHmmss')+'.json') @{at=[DateTimeOffset]::UtcNow.ToString('o');error=$_.Exception.Message;phase='Inspect before any retry; no automatic replay'}
 throw
}
