param(
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RunId,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$MigrationRun,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ActivationSha256,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$NativeReaderSha256
)
# Personal owner migration only. No Telegram polling, imported resumes or prompts.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$ownerSid='S-1-5-21-71459778-1164188569-2276148161-1001'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class NativeProfileToken {
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool GetTokenInformation(IntPtr token,int kind,out int value,int size,out int returned);
 public static bool Elevated(IntPtr token) { int value,returned; if(!GetTokenInformation(token,20,out value,4,out returned))throw new Exception("Token verification failed");return value!=0; }
}
'@
$elevated=[NativeProfileToken]::Elevated($identity.Token)
$session=[Diagnostics.Process]::GetCurrentProcess().SessionId
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or $identity.User.Value -ne $ownerSid -or $identity.IsSystem -or $elevated -or $session -eq 0){throw 'Exact limited interactive PC owner required'}
$release='C:\ProgramData\OracovaNativeRemote\migration-profile-'+$RunId
if($PSScriptRoot -ne $release){throw 'Reviewed literal profile release required'}
foreach($entry in @(@('activate-pc-native-profile.py',$ActivationSha256),@('restore-pc-native-histories.py',$NativeReaderSha256))){
 $path=Join-Path $release $entry[0];$acl=Get-Acl $path
 if((Get-FileHash -LiteralPath $path).Hash -ne $entry[1] -or $acl.Owner -ne 'BUILTIN\Administrators' -or -not $acl.AreAccessRulesProtected -or (Get-Item $path).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Reviewed protected profile helper required'}
}
$state=Join-Path 'C:\Users\pou\.native-remote' ('migration-profile-'+$RunId)
if(Test-Path -LiteralPath $state){throw 'Existing activation evidence preserved; no replay'}
[IO.Directory]::CreateDirectory($state)|Out-Null
$utf8=[Text.UTF8Encoding]::new($false)
$result=[ordered]@{run=$RunId;ownerSid=$identity.User.Value;elevated=$elevated;session=$session;pid=$PID;startedAt=[DateTime]::UtcNow.ToString('o');modelPromptsSent=0;sessionsResumed=$false;routingChanged=$false;complete=$false}
[IO.File]::WriteAllText((Join-Path $state 'started.json'),($result|ConvertTo-Json -Compress),$utf8)
try {
 $windowsPaths=@('C:\Users\pou\.codex\auth.json','C:\Users\pou\.codex\config.toml','C:\Users\pou\.claude\.credentials.json','C:\Users\pou\.claude\settings.json','C:\Users\pou\.claude.json')
 $before=@{}
 foreach($path in $windowsPaths){
  foreach($part in @($path,(Split-Path $path -Parent))){if((Get-Item -LiteralPath $part).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Redirected Windows owner profile refused'}}
  $before[$path]=(Get-FileHash -LiteralPath $path).Hash
 }
 $denied=$false
 try {$handle=[IO.File]::Open('C:\ProgramData\KhadangRouter\khadang-token.dpapi','Open','Read','ReadWrite');$handle.Dispose()}
 catch [UnauthorizedAccessException] {$denied=$true}
 $result.windowsCredentialReadDenied=$denied
 if(-not $denied){throw 'Windows bot credential boundary failed'}
 $readProbe=@'
import errno,json,os,sys
try:
 fd=os.open('/mnt/c/ProgramData/KhadangRouter/khadang-token.dpapi',os.O_RDONLY)
 os.close(fd)
 print(json.dumps({'uid':os.getuid(),'readDenied':False}));sys.exit(1)
except OSError as error:
 denied=error.errno in (errno.EACCES,errno.EPERM)
 print(json.dumps({'uid':os.getuid(),'readDenied':denied}));sys.exit(0 if denied else 2)
'@
 foreach($user in @('pou','root')){
  $raw=& C:\Windows\System32\wsl.exe -d Ubuntu-24.04 -u $user --exec /usr/bin/python3 -I -c $readProbe 2> (Join-Path $state ('boundary-'+$user+'-stderr.private.txt'))
  if($LASTEXITCODE -ne 0){throw 'Linux credential boundary/entry check failed'}
  $check=$raw|ConvertFrom-Json
  $result['linuxBoundary_'+$user]=$check
  if(-not $check.readDenied -or ($user -eq 'pou' -and $check.uid -ne 1000) -or ($user -eq 'root' -and $check.uid -ne 0)){throw 'Linux bot credential boundary failed'}
 }
 $script='/mnt/c/ProgramData/OracovaNativeRemote/migration-profile-'+$RunId+'/activate-pc-native-profile.py'
 $raw=& C:\Windows\System32\wsl.exe -d Ubuntu-24.04 -u pou --exec /usr/bin/python3 -I -B $script $MigrationRun $RunId 2> (Join-Path $state 'activation-stderr.private.txt')
 $result.activationExit=$LASTEXITCODE
 [IO.File]::WriteAllText((Join-Path $state 'profile.json'),($raw -join "`n"),$utf8)
 if($result.activationExit -ne 0){throw 'Profile activation/check failed; inspect retained evidence before another action'}
 $profile=$raw|ConvertFrom-Json
 if(-not $profile.complete -or $profile.uid -ne 1000 -or $profile.modelPromptsSent -ne 0 -or $profile.sessionsResumed -or -not $profile.checks.nativeStopped){throw 'Native profile acceptance missing'}
 $result.windowsFilesUnchanged=$true
 foreach($path in $windowsPaths){if((Get-FileHash -LiteralPath $path).Hash -ne $before[$path]){$result.windowsFilesUnchanged=$false}}
 if(-not $result.windowsFilesUnchanged){throw 'Windows profile changed during activation; inspect current external writers'}
 $result.checks=$profile.checks
 $result.complete=$true
}
catch {
 $result.failureType=$_.Exception.GetType().FullName
 [IO.File]::WriteAllText((Join-Path $state 'failure.private.txt'),[string]$_,$utf8)
}
finally {
 $result.finishedAt=[DateTime]::UtcNow.ToString('o')
 [IO.File]::WriteAllText((Join-Path $state 'result.json'),($result|ConvertTo-Json -Depth 8),$utf8)
}
if(-not $result.complete){exit 1}
