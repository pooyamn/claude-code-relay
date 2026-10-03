param([Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RunId)
# One-shot fresh native enrollment. Never run under SSH's elevated token.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$owner='S-1-5-21-71459778-1164188569-2276148161-1001'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or $identity.User.Value -ne $owner -or $identity.IsSystem -or
 ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or
 [Diagnostics.Process]::GetCurrentProcess().SessionId -ne 1){throw 'Exact Interactive/Limited owner session 1 required'}
$release='C:\ProgramData\OracovaNativeRemote\migration-claude-remote-'+$RunId
if($PSScriptRoot -ne $release){throw 'Exact protected diagnostic directory required'}
foreach($name in @('migration-claude-remote.ps1','check-pc-claude-remote.py','check-pc-claude-transport.py')){
 $path=Join-Path $release $name;$acl=Get-Acl -LiteralPath $path
 if(-not $acl.AreAccessRulesProtected -or $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne 'S-1-5-32-544' -or
  (Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Administrator-owned sealed diagnostic code required'}
}
$state='C:\Users\pou\.native-remote\migration-claude-remote-'+$RunId
if(Test-Path -LiteralPath $state){throw 'Prior attempt preserved; never replay'}
[IO.Directory]::CreateDirectory($state)|Out-Null
$result=@{complete=$false;run=$RunId;ownerSid=$owner;elevated=$false;session=1;modelPromptsSent=0;routingChanged=$false}
$child=$null
try{
 $denied=$false
 try{$file=[IO.File]::OpenRead('C:\ProgramData\KhadangRouter\khadang-token.dpapi');$file.Dispose()}
 catch [UnauthorizedAccessException]{$denied=$true}
 $result.windowsCredentialReadDenied=$denied
 if(-not $denied){throw 'Actual protected bot credential denial required'}
 $start=[Diagnostics.ProcessStartInfo]::new('C:\Windows\System32\wsl.exe')
 $start.UseShellExecute=$false;$start.CreateNoWindow=$true;$start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
 $start.Arguments='-d Ubuntu-24.04 -u pou --exec /usr/bin/python3 -I -B /mnt/c/ProgramData/OracovaNativeRemote/migration-claude-remote-'+$RunId+'/check-pc-claude-remote.py --run '+$RunId
 $child=[Diagnostics.Process]::Start($start)
 $stdout=$child.StandardOutput.ReadToEndAsync();$stderr=$child.StandardError.ReadToEndAsync()
 $child.WaitForExit()
 [IO.File]::WriteAllText((Join-Path $state 'linux.stdout.private.txt'),$stdout.GetAwaiter().GetResult())
 [IO.File]::WriteAllText((Join-Path $state 'linux.stderr.private.txt'),$stderr.GetAwaiter().GetResult())
 $result.linuxExitCode=$child.ExitCode
 $observation=$stdout.GetAwaiter().GetResult()|ConvertFrom-Json
 $result.native=$observation
 $result.complete=($child.ExitCode -eq 0 -and $observation.complete -and $observation.nativeStopped -and $observation.uid -eq 1000 -and $observation.modelPromptsSent -eq 0)
}
catch{
 $result.failureType=$_.Exception.GetType().FullName
 [IO.File]::WriteAllText((Join-Path $state 'failure.private.txt'),[string]$_)
}
finally{
 $result.windowsLauncherStopped=($null -eq $child -or $child.HasExited)
 $result.at=[DateTime]::UtcNow.ToString('o')
 [IO.File]::WriteAllText((Join-Path $state 'result.json'),($result|ConvertTo-Json -Depth 8 -Compress))
 if($child){$child.Dispose()}
}
if(-not $result.complete){exit 1}
