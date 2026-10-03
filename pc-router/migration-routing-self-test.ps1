param(
 [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9]{6}$')][string]$RunId,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedExecutableSha256,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedRouterSha256
)
# Candidate checks only. Never start a service, poll Telegram, launch a native
# model or touch a bound workspace/history. Running as the administrator would
# expose the live bot secret to unapproved candidate code, so it is forbidden.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$owner='S-1-5-21-71459778-1164188569-2276148161-1001'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=[Security.Principal.WindowsPrincipal]::new($identity)
$session=[Diagnostics.Process]::GetCurrentProcess().SessionId
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or $identity.User.Value -ne $owner -or
 $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or $session -ne 1){
 throw 'Exact limited interactive Windows owner in session 1 required'
}
$release='C:\ProgramData\OracovaRouterRouting-'+$RunId
$state='C:\Users\pou\.native-remote\router-routing-'+$RunId
if(Test-Path -LiteralPath $state){throw 'Prior run exists; inspect receipts, never overwrite or replay'}
foreach($path in @($release,(Join-Path $release 'publish-routing'))){
 if((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint -or (Get-Acl $path).Owner -ne 'BUILTIN\Administrators'){
  throw 'Protected administrator-owned literal candidate required'
 }
}
$exe=Join-Path $release 'publish-routing\MigrationRoutingTests.exe'
$dll=Join-Path $release 'publish-routing\KhadangRouter.dll'
if((Get-FileHash -LiteralPath $exe).Hash -ne $ExpectedExecutableSha256 -or
 (Get-FileHash -LiteralPath $dll).Hash -ne $ExpectedRouterSha256){throw 'Candidate digest changed'}
$denied=$false
try {
 $file=[IO.File]::Open('C:\ProgramData\KhadangRouter\khadang-token.dpapi',[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
 $file.Dispose() # Open/close only; never read even if the OS boundary fails.
}catch [UnauthorizedAccessException]{$denied=$true}
if(-not $denied){throw 'Live bot credential is accessible; candidate execution forbidden'}
[IO.Directory]::CreateDirectory($state)|Out-Null
$acl=[Security.AccessControl.DirectorySecurity]::new();$acl.SetAccessRuleProtection($true,$false)
$acl.SetOwner([Security.Principal.SecurityIdentifier]::new($owner))
foreach($sid in @($owner,'S-1-5-18','S-1-5-32-544')){
 $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
}
Set-Acl -LiteralPath $state -AclObject $acl
[IO.File]::WriteAllText((Join-Path $state 'started.json'),(@{ownerSid=$owner;session=$session;elevated=$false;
 credentialReadDenied=$denied;executableSha256=$ExpectedExecutableSha256;routerSha256=$ExpectedRouterSha256;
 modelInference=$false;telegramPolling=$false;productionChanged=$false;at=[DateTime]::UtcNow.ToString('o')}|ConvertTo-Json -Compress))
$child=$null
try {
 # Windows PowerShell 5's native stderr becomes a RemoteException under Stop;
 # *> then loses the original diagnostic before it reaches the file. Separate
 # OS-level redirection retains the real exit code and both streams instead.
 $stdout=Join-Path $state 'self-test.stdout.private.log'
 $stderr=Join-Path $state 'self-test.stderr.private.log'
 # Own the actual Process handle. Start-Process/Refresh on Windows PowerShell
 # can lose the child's exit status even when its redirected output survived.
 $launch=[Diagnostics.ProcessStartInfo]::new()
 $launch.FileName=$exe;$launch.Arguments='--self-test';$launch.WorkingDirectory=Join-Path $release 'publish-routing'
 $launch.UseShellExecute=$false;$launch.CreateNoWindow=$true;$launch.RedirectStandardOutput=$true;$launch.RedirectStandardError=$true
 $child=[Diagnostics.Process]::Start($launch)
 $outRead=$child.StandardOutput.ReadToEndAsync();$errRead=$child.StandardError.ReadToEndAsync()
 if(-not $child.WaitForExit(480000)){throw 'Owned candidate test exceeded its execution bound'}
 $code=$child.ExitCode
 [IO.File]::WriteAllText($stdout,$outRead.GetAwaiter().GetResult())
 [IO.File]::WriteAllText($stderr,$errRead.GetAwaiter().GetResult())
 $log=[IO.File]::ReadAllText($stdout)
 $matched=[regex]::Match($log,'All (\d+) PC-routing checks passed')
 if($code -ne 0 -or -not $matched.Success){throw 'Actual Windows candidate tests failed; production untouched'}
 [IO.File]::WriteAllText((Join-Path $state 'result.json'),(@{completed=$true;exitCode=$code;checks=[int]$matched.Groups[1].Value;
 ownerSid=$owner;session=$session;elevated=$false;credentialReadDenied=$denied;routerSha256=$ExpectedRouterSha256;
 modelInference=$false;telegramPolling=$false;productionChanged=$false;at=[DateTime]::UtcNow.ToString('o')}|ConvertTo-Json -Compress))
}catch {
 [IO.File]::WriteAllText((Join-Path $state 'failure.json'),(@{completed=$false;errorType=$_.Exception.GetType().Name;
 productionChanged=$false;at=[DateTime]::UtcNow.ToString('o')}|ConvertTo-Json -Compress))
 throw
}finally {
 if($child){if(-not $child.HasExited){$child.Kill();$child.WaitForExit()};$child.Dispose()}
}
