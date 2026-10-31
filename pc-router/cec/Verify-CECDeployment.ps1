$ErrorActionPreference='Stop'
$base='C:\ProgramData\GT105CEC'
$output='C:\Users\pou\Downloads\GT105-BIOS-readout-20261031-qhgCtb\CEC-startup-deployment-audit.json'
$m=Get-Content -Raw (Join-Path $base 'manifest.json') | ConvertFrom-Json
$task=Get-ScheduledTask -TaskName 'GT105-CEC-ClockGate'
$info=Get-ScheduledTaskInfo -TaskName 'GT105-CEC-ClockGate'
if(-not $task.Settings.Enabled -or $info.LastTaskResult -ne 0 -or $task.State -eq 'Running'){throw 'Task not enabled/quiescent/successful'}
$triggers=@($task.Triggers | ForEach-Object {[pscustomobject]@{class=$_.CimClass.CimSystemProperties.ClassName;enabled=$_.Enabled;delay=$_.Delay;subscription=$_.Subscription}})
if($triggers.Count -ne 2 -or @($triggers | Where-Object {-not $_.enabled}).Count){throw 'Unexpected or disabled triggers'}
if(@($triggers | Where-Object {$_.class -eq 'MSFT_TaskBootTrigger'}).Count -ne 1){throw 'Boot trigger missing'}
$resume=@($triggers | Where-Object {$_.class -eq 'MSFT_TaskEventTrigger'})
if($resume.Count -ne 1 -or $resume[0].subscription -notmatch 'EventID=107' -or $resume[0].subscription -notmatch 'EventID=507' -or $resume[0].subscription -notmatch 'EventID=1'){throw 'Resume subscription missing'}
$xml=[xml](Export-ScheduledTask -TaskName 'GT105-CEC-ClockGate')
$ns=New-Object Xml.XmlNamespaceManager $xml.NameTable;$ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
if($xml.SelectSingleNode('//t:Principal/t:UserId',$ns).InnerText -ne 'S-1-5-18'){throw 'Task is not SYSTEM'}
$acl=Get-Acl $base
$sids=@($acl.Access | ForEach-Object {$_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value} | Select-Object -Unique)
if(-not $acl.AreAccessRulesProtected -or @($sids | Where-Object {$_ -notin @('S-1-5-18','S-1-5-32-544')}).Count){throw 'Unexpected policy directory access'}
foreach($pair in @(@('CEC-Policy.ps1',$m.policySha256),@('CECClockGateProbe.dll',$m.helperSha256),@('LpcIO.bin',$m.moduleSha256))){if((Get-FileHash (Join-Path $base $pair[0])).Hash -ne $pair[1]){throw 'Artifact integrity mismatch'}}
$driver=Get-CimInstance Win32_SystemDriver -Filter "Name='PawnIO'"
if($driver.State -ne 'Running' -or (Get-FileHash $driver.PathName).Hash -ne $m.driverSha256){throw 'Provider driver mismatch'}
$security=Get-CimInstance -Namespace root\Microsoft\Windows\DeviceGuard -ClassName Win32_DeviceGuard | Select-Object VirtualizationBasedSecurityStatus,SecurityServicesRunning
if($security.VirtualizationBasedSecurityStatus -ne 2 -or 2 -notin $security.SecurityServicesRunning){throw 'Windows security protections changed'}
Add-Type -Path (Join-Path $base 'CECClockGateProbe.dll')
$probe=New-Object CECClockGateProbe (Join-Path $base 'LpcIO.bin')
try{$registers=$probe.Snapshot();[CECClockGateProbe]::GuardStable($registers,1)}finally{$probe.Dispose()}
$result=[ordered]@{verifiedUtc=[DateTime]::UtcNow.ToString('o');taskName=$task.TaskName;taskState=$task.State.ToString();taskEnabled=$task.Settings.Enabled;taskResult=$info.LastTaskResult;principalSid='S-1-5-18';triggers=$triggers;aclProtected=$acl.AreAccessRulesProtected;aclSids=$sids;owner=$acl.Owner;artifactHashesVerified=$true;driverHashVerified=$true;providerState=$driver.State;security=$security;liveRegisters=$registers;realRebootOrResumeTested=$false;endToEndTvCecTested=$false}
[IO.File]::WriteAllText($output,($result | ConvertTo-Json -Depth 10))
Copy-Item (Join-Path $base 'manifest.json') (Join-Path (Split-Path $output) 'CEC-policy-install-manifest.json') -Force
Copy-Item (Join-Path $base 'latest-run.json') (Join-Path (Split-Path $output) 'CEC-policy-final-status.json') -Force
Write-Output 'PASS: SYSTEM startup/resume task enabled; latest task result0; protected files/driver hashes valid; live CECCG=1 and pin high; HVCI unchanged. No reboot/resume was performed.'
