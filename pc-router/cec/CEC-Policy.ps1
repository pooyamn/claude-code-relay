param([ValidateSet('Apply','DryRun','Status','Restore')][string]$Mode='Status')
$ErrorActionPreference='Stop'
$base='C:\ProgramData\GT105CEC'
$taskName='GT105-CEC-ClockGate'
$result=[ordered]@{startedUtc=[DateTime]::UtcNow.ToString('o');mode=$Mode;identity=[Security.Principal.WindowsIdentity]::GetCurrent().Name;changed=$false;success=$false}
$probe=$null;$lease=$null;$held=$false;$changedHere=$false;$exitCode=1
try{
 if($Mode -eq 'Restore'){
  $task=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
  if($task){Disable-ScheduledTask -TaskName $taskName | Out-Null;if($task.State -eq 'Running'){Stop-ScheduledTask -TaskName $taskName}}
 }
 $manifest=Get-Content -Raw (Join-Path $base 'manifest.json') | ConvertFrom-Json
 foreach($entry in @(@('CEC-Policy.ps1',$manifest.policySha256),@('CECClockGateProbe.dll',$manifest.helperSha256),@('LpcIO.bin',$manifest.moduleSha256))){
  if((Get-FileHash (Join-Path $base $entry[0]) -Algorithm SHA256).Hash -ne $entry[1]){throw "Protected artifact hash mismatch: $($entry[0])"}
 }
 $dll='C:\Program Files\PawnIO\PawnIOLib.dll'
 if((Get-FileHash $dll).Hash -ne $manifest.librarySha256 -or (Get-AuthenticodeSignature $dll).Status -ne 'Valid'){throw 'Provider library verification failed'}
 $driver=Get-CimInstance Win32_SystemDriver -Filter "Name='PawnIO'"
 if(-not $driver -or $driver.State -ne 'Running' -or (Get-FileHash -LiteralPath $driver.PathName).Hash -ne $manifest.driverSha256){throw 'Provider driver not ready or kernel binary changed'}
 $bios=Get-CimInstance Win32_BIOS
 # WMI converts the firmware date into local time; compare the UTC calendar day.
 if($bios.SMBIOSBIOSVersion -ne $manifest.biosVersion -or $bios.ReleaseDate.ToUniversalTime().ToString('yyyyMMdd') -ne $manifest.biosDateUtc){throw 'BIOS version/date changed; policy refuses a write'}
 $security=Get-CimInstance -Namespace root\Microsoft\Windows\DeviceGuard -ClassName Win32_DeviceGuard
 if($security.VirtualizationBasedSecurityStatus -ne 2 -or 2 -notin $security.SecurityServicesRunning){throw 'Expected Windows security protections are not running'}
 Add-Type -Path (Join-Path $base 'CECClockGateProbe.dll')
 $lease=[CECClockGateProbe]::CreateLease('Global\GT105CEC-Policy')
 $held=[CECClockGateProbe]::AcquireLease($lease)
 if(-not $held){throw 'Another policy/restore operation is active'}
 $probe=New-Object CECClockGateProbe (Join-Path $base 'LpcIO.bin')
 $before=$probe.Snapshot();$result.before=$before
 switch($Mode){
  'Status' {$result.outcome=if(($before['1E09'] -band 1) -ne 0){'CEC clock gated'}else{'CEC clock operating'}}
  'Restore' {
   $after=$probe.SetClockGateBit([int]$manifest.originalGateBit)
   $result.changed=$before['1E09'] -ne $after['1E09']
   $result.after=$after;$result.outcome='Original clock bit restored; startup/resume task disabled'
  }
  default {
   if($before['1E09'] -eq 1){
    [CECClockGateProbe]::GuardStable($before,1)
    $result.outcome='Already gated; no control write';$result.after=$before
   }else{
    # Bounded wait for an idle interval. No writes are used to force idleness.
    $idleCount=0;$wait=[Diagnostics.Stopwatch]::StartNew()
    while($wait.Elapsed.TotalSeconds -lt 5 -and $idleCount -lt 6){
     try{[CECClockGateProbe]::GuardIdle($probe.Snapshot());$idleCount++}catch{$idleCount=0}
     Start-Sleep -Milliseconds 10
    }
    if($idleCount -lt 6){throw 'CEC remained busy/unknown; deferred without a control write'}
    if($Mode -eq 'DryRun'){$result.outcome='Idle and eligible; dry run made no control write';$result.after=$probe.Snapshot()}
    else{
     # Mark ownership BEFORE the write so any post-write exception restores it.
     $changedHere=$true
     $result.after=$probe.SetClockGateBit(1);$result.changed=$true
     [CECClockGateProbe]::GuardStable($result.after,1)
     $observations=0;$timer=[Diagnostics.Stopwatch]::StartNew()
     while($timer.Elapsed.TotalSeconds -lt 2){[CECClockGateProbe]::GuardStable($probe.Snapshot(),1);$observations++;Start-Sleep -Milliseconds 100}
     $result.observations=$observations;$result.outcome='CEC clock gated; pin selection unchanged'
    }
   }
  }
 }
 $result.success=$true;$exitCode=0
}catch{
 $result.error=$_.Exception.ToString()
 if($changedHere -and $probe){
  try{$result.rollback=$probe.SetClockGateBit(0);$result.restoredOnFailure=$result.rollback['1E09'] -eq 0}
  catch{$result.rollbackError=$_.Exception.ToString()}
 }
}finally{
 if($probe){try{$probe.Dispose()}catch{$result.disposeError=$_.Exception.ToString();$exitCode=1}}
 if($held){$lease.ReleaseMutex()};if($lease){$lease.Dispose()}
 $result.finishedUtc=[DateTime]::UtcNow.ToString('o')
 $json=$result | ConvertTo-Json -Depth 10
 $latest=Join-Path $base 'latest-run.json';$temp=Join-Path $base ('result-'+[guid]::NewGuid().ToString('N')+'.tmp')
 [IO.File]::WriteAllText($temp,$json)
 Move-Item -LiteralPath $temp -Destination $latest -Force
 $history=Join-Path (Join-Path $base 'runs') ([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff')+'-'+[guid]::NewGuid().ToString('N')+'.json')
 [IO.File]::WriteAllText($history,$json)
 $json
}
exit $exitCode
