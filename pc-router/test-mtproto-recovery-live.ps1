param(
 [ValidateSet('Inspect','Hang','Stop')][string]$Mode='Inspect',
 [Parameter(Mandatory=$true)][ValidatePattern('^C:\\ProgramData\\OracovaMTProtoHealth-[a-f0-9]{32}$')][string]$HealthRoot
)
# Owner-authorized failure drill, fixed unused loopback service only. No reboot,
# direct-proxy outage, broad process matching, secret printing or agent restart.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$name='OracovaMTProto';$task='Oracova-MTProtoHealth'
$mt='C:\ProgramData\OracovaMTProto-2a2ae0dae7f749a2bcd664519271c88d'
$service=Get-CimInstance Win32_Service -Filter ('Name="'+$name+'"')
if($service.PathName -ne ('"'+$mt+'\ServiceHost.exe" '+$name) -or $service.State -ne 'Running' -or $service.StartName -ne 'NT AUTHORITY\LocalService'){throw 'Exact live service required'}
$beforePid=$service.ProcessId
$others=@(Get-CimInstance Win32_Service|Where-Object {$_.Name -in @('OracovaMTProto8443','OracovaVPN','OracovaCloudflare','OracovaCloudflareFallback','KhadangRouter')}|Select-Object Name,ProcessId)
if($Mode -eq 'Inspect'){
 [pscustomobject]@{name=$name;pid=$beforePid;watchdog=(Get-ScheduledTask $task).State.ToString();faultInjected=$false}|ConvertTo-Json -Compress;return
}
if(-not ([Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed administrator required'}
$suspended=$null
try {
 if($Mode -eq 'Hang'){
  if(([DateTime]::UtcNow-(Get-Process -Id $beforePid).StartTime.ToUniversalTime()).TotalSeconds -lt 120){throw 'Startup grace not elapsed; no fault injected'}
  $children=@(Get-CimInstance Win32_Process -Filter ('ParentProcessId='+$beforePid)|Where-Object {$_.Name -eq 'python.exe'})
  if($children.Count -ne 1 -or $children[0].CommandLine -notlike ('*"'+$mt+'\server.py" '+$name)){throw 'Exact contained proxy child required'}
  Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class MtprotoFaultDrill {
 [DllImport("kernel32.dll",SetLastError=true)] static extern IntPtr OpenProcess(uint rights,bool inherit,uint pid);
 [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
 [DllImport("ntdll.dll")] static extern int NtSuspendProcess(IntPtr handle);
 [DllImport("ntdll.dll")] static extern int NtResumeProcess(IntPtr handle);
 public static void Change(uint pid,bool suspend) {
  var handle=OpenProcess(0x800,false,pid);if(handle==IntPtr.Zero)throw new InvalidOperationException("Fault target inaccessible");
  try {if((suspend?NtSuspendProcess(handle):NtResumeProcess(handle))!=0)throw new InvalidOperationException("Fault injection failed");}
  finally {CloseHandle(handle);}
 }
}
'@
  $suspended=$children[0]
  [MtprotoFaultDrill]::Change($suspended.ProcessId,$true)
  # Three real failed authenticated probes. Run existing scheduled SYSTEM task;
  # never seed/fake failure counts or bypass grace/cooldown to make the drill pass.
  for($i=0;$i -lt 3;$i++){
   $deadline=[DateTime]::UtcNow.AddSeconds(27)
   while((Get-ScheduledTask $task).State -eq 'Running'){
    if([DateTime]::UtcNow -gt $deadline){throw 'Watchdog did not finish'};Start-Sleep -Milliseconds 200
   }
   $start=[DateTime]::UtcNow;Start-ScheduledTask -TaskName $task
   do {
    Start-Sleep -Milliseconds 200
    $receipt=Get-Content (Join-Path $HealthRoot 'watchdog-state.json') -Raw|ConvertFrom-Json
    if([DateTime]::UtcNow -gt $deadline){throw 'Watchdog receipt not fresh'}
   } while([DateTime]::Parse($receipt.at).ToUniversalTime() -lt $start -or (Get-ScheduledTask $task).State -eq 'Running')
   [pscustomobject]@{sample=$i+1;health=$receipt.services.$name}|ConvertTo-Json -Depth 4 -Compress
   if((Get-CimInstance Win32_Service -Filter ('Name="'+$name+'"')).ProcessId -ne $beforePid){break}
  }
 } else {
  try {Stop-Service -Name $name}catch{}
  (Get-Service $name).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(20))
  $start=[DateTime]::UtcNow;$deadline=$start.AddSeconds(80)
  # Do not launch the task manually: prove the installed one-minute schedule.
  do {
   Start-Sleep -Milliseconds 500
   $current=Get-CimInstance Win32_Service -Filter ('Name="'+$name+'"')
   if([DateTime]::UtcNow -gt $deadline){throw 'Periodic recovery did not occur'}
  } while($current.State -ne 'Running')
 }
 $after=Get-CimInstance Win32_Service -Filter ('Name="'+$name+'"')
 if($after.State -ne 'Running' -or $after.ProcessId -eq $beforePid){throw 'No watchdog recovery'}
 foreach($s in $others){
  if((Get-CimInstance Win32_Service -Filter ('Name="'+$s.Name+'"')).ProcessId -ne $s.ProcessId){throw 'Unrelated service changed'}
 }
 & 'C:\ProgramData\OracovaVPN-20261003-FA9g4b\python\python.exe' -I -B (Join-Path $HealthRoot 'health_probe.py') $name
 if($LASTEXITCODE -ne 0){throw 'Post-recovery probe failed'}
 [pscustomobject]@{at=[DateTime]::UtcNow.ToString('o');mode=$Mode;beforePid=$beforePid;afterPid=$after.ProcessId;unrelatedServicesUnchanged=$true;manualServiceStart=$false;pcRebooted=$false}|ConvertTo-Json -Compress
} finally {
 if($suspended){
  $still=Get-CimInstance Win32_Process -Filter ('ProcessId='+$suspended.ProcessId)
  if($still -and $still.CreationDate -eq $suspended.CreationDate){[MtprotoFaultDrill]::Change($still.ProcessId,$false)}
 }
 # Failed drills must not intentionally leave the fixed proxy offline.
 if((Get-Service $name).Status -eq 'Stopped'){Start-Service $name}
}
