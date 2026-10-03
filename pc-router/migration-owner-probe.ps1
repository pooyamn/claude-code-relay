param(
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RunId,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$MigrationRun,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$HistoryScriptSha256,
 [switch]$NativeReads,
 [ValidatePattern('^[0-9a-fA-F]{64}$')][string]$NativeScriptSha256,
 [switch]$ClaudeContext,
 [ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ClaudeScriptSha256,
 [ValidatePattern('^[0-9a-f]{32}$')][string]$ClaudeContinueRun
)
# One-shot migration evidence, not a new broker or production authorization.
# Never read credential bytes, start models, replay actions or change routing.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$ownerSid='S-1-5-21-71459778-1164188569-2276148161-1001'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class MigrationOwnerToken {
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool GetTokenInformation(IntPtr token,int kind,out int value,int size,out int returned);
 public static bool Elevated(IntPtr token) { int value,returned; if(!GetTokenInformation(token,20,out value,4,out returned))throw new Exception("Token verification failed");return value!=0; }
}
'@
$elevated=[MigrationOwnerToken]::Elevated($identity.Token)
$session=[Diagnostics.Process]::GetCurrentProcess().SessionId
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or $identity.User.Value -ne $ownerSid -or $identity.IsSystem -or $elevated -or $session -eq 0){
 throw 'Exact limited interactive PC owner required'
}
$expectedRoot='C:\ProgramData\OracovaNativeRemote\migration-probe-'+$RunId
if($PSScriptRoot -ne $expectedRoot){throw 'Reviewed literal migration probe required'}
$historyScript=Join-Path $PSScriptRoot 'verify-pc-migration-histories.py'
if((Get-FileHash -LiteralPath $historyScript).Hash -ne $HistoryScriptSha256){throw 'Reviewed history checker digest mismatch'}
if($NativeReads -and (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'restore-pc-native-histories.py')).Hash -ne $NativeScriptSha256){throw 'Reviewed native reader digest required'}
if($ClaudeContext -and (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'check-pc-claude-context.py')).Hash -ne $ClaudeScriptSha256){throw 'Reviewed Claude context checker digest required'}
if($NativeReads -and $ClaudeContext){throw 'Separate history restore from idle Claude inspection'}
$state=Join-Path 'C:\Users\pou\.native-remote' ('migration-probe-'+$RunId)
if(Test-Path -LiteralPath $state){throw 'Existing attempt preserved; never replay'}
[IO.Directory]::CreateDirectory($state)|Out-Null
$result=[ordered]@{run=$RunId;ownerSid=$identity.User.Value;elevated=$elevated;session=$session;pid=$PID;
 startedAt=[DateTime]::UtcNow.ToString('o');modelsStarted=$false;routingChanged=$false;complete=$false}
$utf8=[Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText((Join-Path $state 'started.json'),($result|ConvertTo-Json -Compress),$utf8)
try {
 $result.failureStage='windows-credential-read'
 $denied=$false
 try {$handle=[IO.File]::Open('C:\ProgramData\KhadangRouter\khadang-token.dpapi','Open','Read','ReadWrite');$handle.Dispose()}
 catch [UnauthorizedAccessException] {$denied=$true}
 $result.windowsCredentialReadDenied=$denied
 if(-not $denied){throw 'Windows credential boundary failed'}
 # This deterministic root probe only opens/closes the Windows file: no bytes,
 # models or root changes. UID 0 cannot be a shortcut around the Windows ACL.
 $readProbe=@'
import errno,json,os,sys
uid=os.getuid()
try:
 fd=os.open('/mnt/c/ProgramData/KhadangRouter/khadang-token.dpapi',os.O_RDONLY)
 os.close(fd)
 print(json.dumps({'uid':uid,'readDenied':False}))
 sys.exit(1)
except OSError as error:
 denied=error.errno in (errno.EACCES,errno.EPERM)
 print(json.dumps({'uid':uid,'readDenied':denied,'errno':error.errno}))
 sys.exit(0 if denied else 2)
'@
 foreach($user in @('pou','root')){
  $result.failureStage='linux-credential-read-'+$user
  $raw=& 'C:\Windows\System32\wsl.exe' -d Ubuntu-24.04 -u $user --exec /usr/bin/python3 -I -c $readProbe 2> (Join-Path $state ('linux-'+$user+'-stderr.private.txt'))
  $code=$LASTEXITCODE
  [IO.File]::WriteAllText((Join-Path $state ('linux-'+$user+'-stdout.private.txt')),($raw -join "`n"),$utf8)
  $result['linuxCredentialExit_'+$user]=$code
  if($code -ne 0){throw 'Linux entry/probe failed; inspect captured output before parsing'}
  $observation=$raw|ConvertFrom-Json
  $result['linuxCredentialProbe_'+$user]=$observation
  if($code -ne 0 -or -not $observation.readDenied -or ($user -eq 'pou' -and $observation.uid -ne 1000) -or ($user -eq 'root' -and $observation.uid -ne 0)){
   throw 'Linux entry credential boundary failed'
  }
 }
 $linuxScript='/mnt/c/ProgramData/OracovaNativeRemote/migration-probe-'+$RunId+'/verify-pc-migration-histories.py'
 $result.failureStage='captured-histories'
 $raw=& 'C:\Windows\System32\wsl.exe' -d Ubuntu-24.04 -u pou --exec /usr/bin/python3 -I -B $linuxScript $MigrationRun 2> (Join-Path $state 'history-stderr.private.txt')
 $result.historyCheckExit=$LASTEXITCODE
 [IO.File]::WriteAllText((Join-Path $state 'histories.json'),($raw -join "`n"),$utf8)
 $histories=$raw|ConvertFrom-Json
 if($result.historyCheckExit -ne 0 -or $histories.uid -ne 1000 -or $histories.bindings.Count -ne 14){throw 'Captured history check failed; retain evidence'}
 if($NativeReads){
  $result.failureStage='native-history-restore-and-read'
  $nativeScript='/mnt/c/ProgramData/OracovaNativeRemote/migration-probe-'+$RunId+'/restore-pc-native-histories.py'
  $raw=& 'C:\Windows\System32\wsl.exe' -d Ubuntu-24.04 -u pou --exec /usr/bin/python3 -I -B $nativeScript $MigrationRun $RunId 2> (Join-Path $state 'native-read-stderr.private.txt')
  $result.nativeReadExit=$LASTEXITCODE
  [IO.File]::WriteAllText((Join-Path $state 'native-read.json'),($raw -join "`n"),$utf8)
  if($result.nativeReadExit -ne 0){throw 'Native restore/read failed; retain its evidence before further action'}
  $native=$raw|ConvertFrom-Json
  if(-not $native.complete -or -not $native.nativeStopped -or $native.nativeReads.Count -ne 5 -or $native.loadedThreadsAfterReads.Count -ne 0 -or $native.modelTurnsStarted -ne 0 -or $native.sessionsResumed){throw 'Native read acceptance missing'}
  $result.nativeReadComplete=$true
 }
 if($ClaudeContext){
  $result.failureStage='claude-idle-context'
  $claudeScript='/mnt/c/ProgramData/OracovaNativeRemote/migration-probe-'+$RunId+'/check-pc-claude-context.py'
  $claudeArgs=@('-d','Ubuntu-24.04','-u','pou','--exec','/usr/bin/python3','-I','-B',$claudeScript,$MigrationRun,$RunId)
  if($ClaudeContinueRun){$claudeArgs+=@($ClaudeContinueRun)}
  $raw=& 'C:\Windows\System32\wsl.exe' @claudeArgs 2> (Join-Path $state 'claude-stderr.private.txt')
  $result.claudeContextExit=$LASTEXITCODE
  [IO.File]::WriteAllText((Join-Path $state 'claude-context.json'),($raw -join "`n"),$utf8)
  if($result.claudeContextExit -ne 0){throw 'Idle Claude context inspection failed; retain evidence before another launch'}
  $claude=$raw|ConvertFrom-Json
  if(-not $claude.complete -or -not $claude.nativeStopped -or $claude.checks.Count -ne 10 -or $claude.modelPromptsSent -ne 0){throw 'Idle Claude acceptance missing'}
  $result.claudeControlReadComplete=$true
 }
 $result.complete=$true
 $result.Remove('failureStage')
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
