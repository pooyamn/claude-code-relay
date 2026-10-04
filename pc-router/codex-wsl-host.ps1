# One native managed Unix daemon, shared by Remote and local clients, as on
# the Mac VM. Task Scheduler supplies only owner logon/periodic supervision.
# Never restart/stop a live daemon or replay a thread, turn or external action.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$ownerSid='S-1-5-21-71459778-1164188569-2276148161-1001'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class WslRemoteOwnerToken {
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool GetTokenInformation(IntPtr token,int informationClass,out int value,int size,out int returned);
 public static bool Elevated(IntPtr token) { int value,returned; if(!GetTokenInformation(token,20,out value,4,out returned))throw new Exception("Token verification failed");return value!=0; }
}
'@
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or $identity.User.Value -ne $ownerSid -or
 $identity.IsSystem -or [WslRemoteOwnerToken]::Elevated($identity.Token) -or
 [Diagnostics.Process]::GetCurrentProcess().SessionId -eq 0){
 throw 'Exact non-elevated interactive PC owner required'
}
$state='C:\Users\pou\.native-remote'
$wsl='C:\Windows\System32\wsl.exe'
$native='/Users/pouya/.local/share/pc-migration-native/codex-0.160.0/package/bin/codex'
$expected='12eb3e81114588aca3b7998f4f19e8997b056aca08e57a7ca7c8a3ec8c652aad'
$utf8=[Text.UTF8Encoding]::new($false)
if(-not (Test-Path -LiteralPath $state)){throw 'Existing private owner state required'}
function Save-HostState($stateName,$details){
 [IO.File]::WriteAllText((Join-Path $state 'codex-wsl-status.json'),(@{provider='Codex';runtime='linux';state=$stateName;
 ownerSid=$identity.User.Value;elevated=$false;sessionId=[Diagnostics.Process]::GetCurrentProcess().SessionId;
 pid=$PID;at=[DateTime]::UtcNow.ToString('o');details=$details}|ConvertTo-Json -Depth 6),$utf8)
}
function Is-AbsentNativeSocket([string]$Output,[string]$ErrorText){
 $expectedError="Error: failed to connect to /Users/pouya/.codex/app-server-control/app-server-control.sock`n`nCaused by:`n    No such file or directory (os error 2)"
 return [string]::IsNullOrWhiteSpace($Output) -and $ErrorText.Replace("`r`n","`n").Trim() -ceq $expectedError
}
function Invoke-Wsl([string[]]$NativeArguments,[string]$Evidence,[switch]$AllowAbsentSocket){
 $info=[Diagnostics.ProcessStartInfo]::new($wsl)
 $info.UseShellExecute=$false;$info.CreateNoWindow=$true
 $info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
 # Fixed executable/distro/user; arguments below contain only reviewed literals.
 $info.Arguments='-d Ubuntu-24.04 -u pou --exec '+($NativeArguments -join ' ')
 $process=[Diagnostics.Process]::Start($info)
 try{
  $output=$process.StandardOutput.ReadToEndAsync();$errorOutput=$process.StandardError.ReadToEndAsync()
  $process.WaitForExit();$text=$output.GetAwaiter().GetResult();$privateError=$errorOutput.GetAwaiter().GetResult()
  [IO.File]::WriteAllText((Join-Path $state ($Evidence+'.stdout.private.txt')),$text,$utf8)
  [IO.File]::WriteAllText((Join-Path $state ($Evidence+'.stderr.private.txt')),$privateError,$utf8)
  if($process.ExitCode -ne 0){
   # 0.160.0 reports an absent daemon as errno 2, not a JSON stopped status.
   # Only this exact measured absence is eligible for native lifecycle start.
   # Permission, configuration, malformed replies and timeouts still fail.
   if($AllowAbsentSocket -and $process.ExitCode -eq 1 -and (Is-AbsentNativeSocket $text $privateError)){return $null}
   throw ('Native WSL operation rejected: '+$Evidence+'; inspect private evidence')
  }
  return $text.Trim()
 }finally{$process.Dispose()}
}
try{
 if((Invoke-Wsl @('/usr/bin/id','-u') 'codex-wsl-owner') -ne '1000'){throw 'Native Linux owner UID mismatch'}
 $digest=Invoke-Wsl @('/usr/bin/sha256sum',$native) 'codex-wsl-image'
 if(-not $digest.StartsWith($expected+' ')){throw 'Pinned native Linux image changed'}
 while($true){
  $versionText=Invoke-Wsl @($native,'app-server','daemon','version') 'codex-wsl-version' -AllowAbsentSocket
  $version=if($null -ne $versionText){$versionText|ConvertFrom-Json}else{$null}
  if($version.status -ne 'running'){
   Save-HostState 'starting' @{previousNativeState=$version.status}
   # Installation separately bootstraps and pins the reviewed package. Native
   # start preserves that pin and the saved remote setting. Never bootstrap or
   # update inside supervision: bootstrap would re-enable package auto-updates.
   Invoke-Wsl @($native,'app-server','daemon','start') 'codex-wsl-start'|Out-Null
   $version=Invoke-Wsl @($native,'app-server','daemon','version') 'codex-wsl-version'|ConvertFrom-Json
  }
  if($version.status -ne 'running' -or $version.cliVersion -ne '0.160.0' -or $version.appServerVersion -ne '0.160.0' -or
   $version.socketPath -ne '/Users/pouya/.codex/app-server-control/app-server-control.sock'){
   throw 'Expected pinned shared native daemon/socket unavailable'
  }
  $observed=Invoke-Wsl @('/usr/bin/python3','-I','-B','/mnt/c/ProgramData/OracovaNativeRemote/codex-wsl-observer-CgBorX/pc_codex_daemon_status.py') 'codex-wsl-read'|ConvertFrom-Json
  if($observed.uid -ne 1000 -or $observed.peerUid -ne 1000 -or $observed.peerPid -le 0){throw 'Native shared peer observation mismatch'}
  if($observed.packageAutoUpdateEnabled){throw 'Reviewed CLI package must remain pinned; automatic package updates are not allowed'}
  $hostState=if($observed.nativeRemoteState -eq 'connected'){'managed-daemon-connected'}else{'managed-daemon-'+$observed.nativeRemoteState}
  Save-HostState $hostState @{nativeVersion=$version.appServerVersion;backend=$version.backend;
   managedCodexPath=$version.managedCodexPath;socket=$version.socketPath;nativePid=$observed.peerPid;
   remoteStatus=$observed.nativeRemoteState;serverName=$observed.serverName;accountFingerprint=$observed.accountFingerprint;
   packageAutoUpdateEnabled=$false;
   phoneRoundTripVerified=$false;existingWindowsSessionsChanged=$false;telegramCutoverVerified=$false}
  Start-Sleep -Seconds 300
 }
}catch{
 Save-HostState 'failed' @{errorType=$_.Exception.GetType().Name;message=$_.Exception.Message}
 exit 1
}
