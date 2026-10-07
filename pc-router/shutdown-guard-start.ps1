# Ordinary interactive owner only. Protected executable; user preference data
# permits ten-minute maintenance, never arbitrary commands or privileged work.
$ErrorActionPreference='Stop'
$id=[Security.Principal.WindowsIdentity]::GetCurrent()
if($id.User.Value -ne 'S-1-5-21-71459778-1164188569-2276148161-1001' -or
 ([Security.Principal.WindowsPrincipal]::new($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
 throw 'Unelevated interactive owner required'
}
$exe=Join-Path $PSScriptRoot 'ShutdownGuard.exe'
$marker=Join-Path $env:LOCALAPPDATA 'OracovaShutdownGuard\maintenance-until.txt'
if(Test-Path $marker){
 $until=[DateTime]::MinValue
 if([DateTime]::TryParse((Get-Content $marker -Raw),[ref]$until)){
  $remaining=($until.ToUniversalTime()-[DateTime]::UtcNow).TotalMinutes
  if($remaining -gt 0 -and $remaining -le 10){return}
 }
}
$process=Start-Process -FilePath $exe -Wait -PassThru
if($process.ExitCode -ne 0){throw 'Shutdown guard failed'}
