param([Parameter(Mandatory=$true)][ValidateSet('Preflight','Upgrade','Verify')][string]$Phase)
# Scheduled as Interactive/Limited. Never run native providers through elevated SSH.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
$owner='S-1-5-21-71459778-1164188569-2276148161-1001'
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or $who.User.Value -ne $owner -or $who.IsSystem -or
 ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or
 [Diagnostics.Process]::GetCurrentProcess().SessionId -eq 0){throw 'Exact limited interactive owner required'}
$package='C:\ProgramData\OracovaNativeRemote\codex-astra62-20261117'
$output='C:\Users\pou\.native-remote\astra62-'+$Phase.ToLowerInvariant()+'.json'
if(Test-Path $output){throw 'Existing owner receipt: reconcile instead of repeating'}
$python='/mnt/c/ProgramData/OracovaNativeRemote/codex-astra62-20261117/upgrade_codex_astra62_20261117.py'
$old='/Users/pouya/.local/share/pc-migration-native/codex-0.160.0/package/bin/codex'
$new='/Users/pouya/.local/share/pc-migration-native/codex-0.169.0/package/vendor/x86_64-unknown-linux-musl/bin/codex'
function Native([string[]]$Arguments){
 $info=[Diagnostics.ProcessStartInfo]::new('C:\Windows\System32\wsl.exe')
 $info.UseShellExecute=$false;$info.CreateNoWindow=$true
 $info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
 $info.Arguments='-d Ubuntu-24.04 -u pou --exec '+($Arguments -join ' ')
 $process=[Diagnostics.Process]::Start($info)
 try{
  $out=$process.StandardOutput.ReadToEndAsync();$err=$process.StandardError.ReadToEndAsync()
  if(-not $process.WaitForExit(90000)){throw 'Native maintenance timeout: preserve state; do not replay'}
  $text=$out.GetAwaiter().GetResult();$errorText=$err.GetAwaiter().GetResult()
  if($process.ExitCode){throw ('Native maintenance rejected: '+$errorText)}
  return $text.Trim()
 }finally{$process.Dispose()}
}
$result=@{phase=$Phase;success=$false;lifecycleStarted=$false;at=[DateTimeOffset]::UtcNow.ToString('o');inputReplay=0}
try{
 if((Native @('/usr/bin/id','-u')) -ne '1000'){throw 'Unexpected native UID'}
 if($Phase -eq 'Preflight'){
  $result.native=Native @('/usr/bin/python3','-I','-B',$python,'inspect','--old-runtime')|ConvertFrom-Json
  $result.success=$true
  [IO.File]::WriteAllText($output,($result|ConvertTo-Json -Depth 40 -Compress),[Text.UTF8Encoding]::new($false))
  exit 0
 }
 if($Phase -eq 'Upgrade'){
  if((Get-Service KhadangRouter).Status -ne 'Stopped'){throw 'Router must be fenced first'}
  $before=Native @('/usr/bin/python3','-I','-B',$python,'inspect','--old-runtime','--snapshot')|ConvertFrom-Json
  if(@($before.threads|Where-Object {$_.status.type -notin @('idle','notLoaded')}).Count){throw 'Native work still active; no daemon restart'}
  # Exact saved IDs/workspaces are read even when the observer has unloaded
  # them. A loaded-thread count is never an identity or continuity check.
  $result.before=$before
  $result.lifecycleStarted=$true
  $null=Native @($old,'app-server','daemon','stop')
  $result.activation=Native @('/usr/bin/python3','-I','-B',$python,'activate-package')|ConvertFrom-Json
  $null=Native @($new,'app-server','daemon','start')
 }
 $result.version=Native @($new,'app-server','daemon','version')|ConvertFrom-Json
 if($result.version.appServerVersion -ne '0.169.0' -or $result.version.cliVersion -ne '0.169.0'){throw 'Expected upgraded shared server'}
 if($Phase -eq 'Verify'){$result.modelRestore=Native @('/usr/bin/python3','-I','-B',$python,'restore-models')|ConvertFrom-Json}
 $result.native=Native @('/usr/bin/python3','-I','-B',$python,'inspect','--snapshot')|ConvertFrom-Json
 if('gpt-6.2-astra' -notin $result.native.models){throw 'Remote catalog does not advertise requested model'}
 if($Phase -eq 'Verify'){
  if($result.native.remote.status -ne 'connected' -or -not $result.native.remote.environmentPresent){throw 'Remote app connection is not healthy'}
  $prior=Get-Content 'C:\Users\pou\.native-remote\astra62-upgrade.json' -Raw|ConvertFrom-Json
  foreach($thread in @($prior.before.threads)){
   $actual=@($result.native.threads|Where-Object id -eq $thread.id)
   if($actual.Count -ne 1 -or $actual[0].cwd -cne $thread.cwd){throw 'Thread identity/workspace was not preserved across restart'}
  }
 }
 $result.success=$true
}catch{$result.error=$_.Exception.Message}
[IO.File]::WriteAllText($output,($result|ConvertTo-Json -Depth 40 -Compress),[Text.UTF8Encoding]::new($false))
if(-not $result.success){exit 1}
