param(
 [Parameter(Mandatory=$true)][string]$CandidateDirectory,
 [Parameter(Mandatory=$true)][ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$ExpectedRouterSha256
)
# Release gate, not deployment. Run inert fixtures as the limited Windows
# owner, never administrator/SYSTEM. No services, real transports or credentials.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or $identity.User.Value -ne 'S-1-5-21-71459778-1164188569-2276148161-1001' -or
 ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
 throw 'Exact ordinary Windows owner required for candidate validation'
}
$dll=Join-Path $CandidateDirectory 'KhadangRouter.dll';$exe=Join-Path $CandidateDirectory 'KhadangRouter.exe'
if((Get-FileHash $dll).Hash -ne $ExpectedRouterSha256){throw 'Reviewed candidate changed'}
$start=[Diagnostics.ProcessStartInfo]::new();$start.FileName=$exe;$start.Arguments='--self-test-startup-isolation'
$start.UseShellExecute=$false;$start.CreateNoWindow=$true;$start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
$child=[Diagnostics.Process]::Start($start)
try{
 $stdout=$child.StandardOutput.ReadToEndAsync();$stderr=$child.StandardError.ReadToEndAsync()
 if(-not $child.WaitForExit(240000)){throw 'Candidate fixture deadline exceeded'}
 $text=$stdout.GetAwaiter().GetResult();$errorText=$stderr.GetAwaiter().GetResult()
 $match=[regex]::Match($text,'Passed (\d+) startup-isolation checks')
 if($child.ExitCode -ne 0 -or -not $match.Success){throw ('Startup isolation fixture failed: '+$errorText)}
 & (Join-Path $PSScriptRoot 'router-watchdog.ps1') -SelfTest
 @{passed=$true;startupChecks=[int]$match.Groups[1].Value;watchdogChecks=10;routerSha256=$ExpectedRouterSha256;
  productionChanged=$false;modelInference=$false;telegramPolling=$false}|ConvertTo-Json -Compress
}finally{if(-not $child.HasExited){$child.Kill();$child.WaitForExit()};$child.Dispose()}
