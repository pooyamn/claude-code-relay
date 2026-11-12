param(
 [ValidateRange(1,30)][int]$Minutes=15,
 [Parameter(Mandatory=$true)][string]$OutputDirectory
)
# Read-only diagnosis: no tasks, services, registry values or audit settings
# are modified. No window titles, keystrokes, tokens or command payloads logged.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$utf8=[Text.UTF8Encoding]::new($false)
$directory=[IO.Path]::GetFullPath($OutputDirectory)
if(-not $directory.StartsWith('C:\Users\pou\AppData\Local\OracovaDiagnostics\console-', [StringComparison]::OrdinalIgnoreCase)){throw 'Explicit diagnostic output directory required'}
if(Test-Path $directory){throw 'Fresh capture directory required'}
[IO.Directory]::CreateDirectory($directory)|Out-Null
Add-Type @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class ConsolePopupObservation {
 public delegate bool Callback(IntPtr window, IntPtr data);
 [DllImport("user32.dll")] static extern bool EnumWindows(Callback callback, IntPtr data);
 [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr window);
 [DllImport("user32.dll")] static extern bool IsIconic(IntPtr window);
 [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr window,StringBuilder name,int count);
 public sealed class Window { public long Handle; public uint Process; public string Class; public bool Minimized; public bool Foreground; }
 public static Window[] Read() {
  var found=new List<Window>(); var foreground=GetForegroundWindow();
  EnumWindows((window,data)=>{
   if(!IsWindowVisible(window))return true;
   var name=new StringBuilder(256);GetClassName(window,name,name.Capacity);
   if(name.ToString()!="ConsoleWindowClass" && name.ToString()!="CASCADIA_HOSTING_WINDOW_CLASS")return true;
   uint process;GetWindowThreadProcessId(window,out process);
   found.Add(new Window { Handle=window.ToInt64(), Process=process, Class=name.ToString(), Minimized=IsIconic(window), Foreground=window==foreground });return true;
  },IntPtr.Zero);return found.ToArray();
 }
}
'@
function SaveJson($Name,$Value){[IO.File]::WriteAllText((Join-Path $directory $Name),($Value|ConvertTo-Json -Depth 12),$utf8)}
function EventLine($Value){[IO.File]::AppendAllText((Join-Path $directory 'events.jsonl'),($Value|ConvertTo-Json -Depth 7 -Compress)+[Environment]::NewLine,$utf8)}
function ProcessMetadata([int]$ProcessId){
 $process0=Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
 if(-not $process0){return @{pid=$ProcessId;exitedBeforeRead=$true}}
 $script0=[regex]::Match([string]$process0.CommandLine,'(?i)-File\s+"?([^"\r\n]+\.ps1)').Groups[1].Value
 $provider0=[regex]::Match([string]$process0.CommandLine,'(?i)-Provider\s+(Claude|Codex)\b').Groups[1].Value
 return @{pid=$ProcessId;parent=[int]$process0.ParentProcessId;name=$process0.Name;image=$process0.ExecutablePath;
  script=$script0;provider=$provider0;session=$process0.SessionId;created=$process0.CreationDate;
  hidden=([string]$process0.CommandLine -match '(?i)-WindowStyle\s+(Hidden|Minimized)')}
}
function Inventory {
 $tasks0=@(Get-ScheduledTask)
 $rows0=@(foreach($task0 in $tasks0){
  $info0=Get-ScheduledTaskInfo -InputObject $task0 -ErrorAction SilentlyContinue
  $actions0=@(foreach($action0 in $task0.Actions){
   $args0=[string]$action0.Arguments
   @{execute=$action0.Execute;hidden=($args0 -match '(?i)-WindowStyle\s+(Hidden|Minimized)');
    script=([regex]::Match($args0,'(?i)-File\s+"?([^"\r\n]+\.ps1)').Groups[1].Value);
    provider=([regex]::Match($args0,'(?i)-Provider\s+(Claude|Codex)\b').Groups[1].Value)}
  })
  @{name=$task0.TaskName;path=$task0.TaskPath;state=[string]$task0.State;user=$task0.Principal.UserId;
   logon=[string]$task0.Principal.LogonType;level=[string]$task0.Principal.RunLevel;
   interval=@($task0.Triggers|ForEach-Object {$_.Repetition.Interval});last=$info0.LastRunTime;next=$info0.NextRunTime;
   result=$info0.LastTaskResult;restartCount=$task0.Settings.RestartCount;restartInterval=$task0.Settings.RestartInterval;actions=$actions0}
 })
 return @{at=[DateTimeOffset]::Now.ToString('o');count=$tasks0.Count;tasks=$rows0}
}
$source='ConsolePopup-'+[Guid]::NewGuid().ToString('N');$subscription=$null;$mode='WMI-process-start'
$started=[DateTimeOffset]::Now;$until=$started.AddMinutes($Minutes)
SaveJson 'inventory-before.json' (Inventory)
$startup0=@(Get-CimInstance Win32_StartupCommand -ErrorAction SilentlyContinue|ForEach-Object {
 @{name=$_.Name;location=$_.Location;user=$_.User;consoleLauncher=([string]$_.Command -match '(?i)\b(cmd|powershell|pwsh|wsl|cscript)\.exe\b');hidden=([string]$_.Command -match '(?i)-WindowStyle\s+(Hidden|Minimized)')}
})
SaveJson 'startup.json' $startup0
try{
 try{$subscription=Register-CimIndicationEvent -Query 'SELECT * FROM Win32_ProcessStartTrace' -SourceIdentifier $source -ErrorAction Stop}
 catch{$mode='polling-250ms';EventLine @{kind='trace-unavailable';error=$_.Exception.GetType().Name;at=[DateTimeOffset]::Now.ToString('o')}}
 $seenWindows=@{};$seenProcesses=@{};$lastProcessPoll=[DateTimeOffset]::MinValue
 SaveJson 'status.json' @{state='running';started=$started.ToString('o');until=$until.ToString('o');pid=$PID;mode=$mode;taskChanges=0}
 while([DateTimeOffset]::Now -lt $until){
  if($subscription){
   foreach($event0 in @(Get-Event -SourceIdentifier $source -ErrorAction SilentlyContinue)){
    $p0=$event0.SourceEventArgs.NewEvent
    if([string]$p0.ProcessName -match '^(?i:cmd|powershell|pwsh|conhost|OpenConsole|WindowsTerminal|wt|wsl|wscript|cscript)\.exe$'){
     $parent0=ProcessMetadata ([int]$p0.ParentProcessID)
     EventLine @{kind='process-start';at=$event0.TimeGenerated.ToString('o');name=$p0.ProcessName;pid=[int]$p0.ProcessID;parent=$parent0;process=(ProcessMetadata ([int]$p0.ProcessID))}
    }
    Remove-Event -EventIdentifier $event0.EventIdentifier
   }
  }elseif(([DateTimeOffset]::Now-$lastProcessPoll).TotalMilliseconds -ge 250){
   foreach($p0 in @(Get-Process -Name cmd,powershell,pwsh,conhost,OpenConsole,WindowsTerminal,wt,wsl,wscript,cscript -ErrorAction SilentlyContinue)){
    try{$key0=[string]$p0.Id+'/'+$p0.StartTime.ToUniversalTime().Ticks}catch{continue}
    if(-not $seenProcesses.ContainsKey($key0)){$seenProcesses[$key0]=$true;EventLine @{kind='process-observed';at=[DateTimeOffset]::Now.ToString('o');process=(ProcessMetadata $p0.Id)}}
   }
   $lastProcessPoll=[DateTimeOffset]::Now
  }
  foreach($window0 in [ConsolePopupObservation]::Read()){
   $key0=[string]$window0.Handle+'/'+$window0.Process+'/'+$window0.Minimized+'/'+$window0.Foreground
   if(-not $seenWindows.ContainsKey($key0)){
    $seenWindows[$key0]=$true;$process0=ProcessMetadata ([int]$window0.Process)
    EventLine @{kind='visible-console';at=[DateTimeOffset]::Now.ToString('o');window=$window0;process=$process0;parent=$(if($process0.parent){ProcessMetadata $process0.parent}else{$null})}
   }
  }
  Start-Sleep -Milliseconds 200
 }
 SaveJson 'inventory-after.json' (Inventory)
 SaveJson 'status.json' @{state='complete';started=$started.ToString('o');finished=[DateTimeOffset]::Now.ToString('o');pid=$PID;mode=$mode;taskChanges=0}
}catch{
 SaveJson 'status.json' @{state='failed';at=[DateTimeOffset]::Now.ToString('o');error=$_.Exception.GetType().Name;taskChanges=0};throw
}finally{
 # No -Action was registered, so this is an event subscription, not a job.
 if($subscription){Unregister-Event -SourceIdentifier $source -ErrorAction SilentlyContinue}
}
