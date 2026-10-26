param([ValidateSet('Stage','Apply','Verify')][string]$Mode='Stage')
$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\OracovaVPN-20261003-FA9g4b'
$binary=Join-Path $root 'bin\cloudflared.exe'
$stage=Join-Path $root 'updates\cloudflared-2026.10.3-20261026'
$candidate=Join-Path $stage 'cloudflared.exe'
$expected='76B2805253D0D6FFACB092A7ACFBEE99E7AF6917835C0C5410E23F3EF5052DA2'
$names=@('OracovaCloudflare','OracovaCloudflareFallback')
$principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$rootAcl=Get-Acl $root
if(-not $rootAcl.AreAccessRulesProtected -or (Get-Item $root).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Protected non-reparse VPN root required'}
function Save($name,$value){[IO.File]::WriteAllText((Join-Path $stage $name),($value|ConvertTo-Json -Depth 8))}
function Version($path){$s=(& $path --version 2>&1 | Out-String).Trim(); if($LASTEXITCODE -ne 0){throw 'Version probe failed'}; return $s}
function Settings {
 $files=@('services\OracovaCloudflare.xml','services\OracovaCloudflareFallback.xml','config\cloudflare-named.yml','config\named-tunnel-credentials.json','config\cloudflare-secrets.json')
 $hashes=@{}; foreach($f in $files){if(Test-Path (Join-Path $root $f)){$hashes[$f]=(Get-FileHash (Join-Path $root $f)).Hash}}
 $services=@(foreach($n in $names){
  $s=Get-CimInstance Win32_Service | Where-Object Name -eq $n
  $x=[xml](Get-Content (Join-Path $root ('services\'+$n+'.xml')) -Raw)
  if($null -eq $s -or $x.service.executable -ne $binary -or $s.PathName -ne ('"'+$root+'\services\'+$n+'.exe"')){throw 'Unexpected service wiring'}
  $reg=Get-ItemProperty ('HKLM:\SYSTEM\CurrentControlSet\Services\'+$n)
  [ordered]@{name=$n;start=$s.StartMode;account=$s.StartName;failure=[Convert]::ToBase64String($reg.FailureActions);failureFlag=$reg.FailureActionsOnNonCrashFailures;delayed=$reg.DelayedAutoStart}
 })
 return [ordered]@{files=$hashes;services=$services}
}
function SettingsSignature($s){
 $f=@($s.files.PSObject.Properties | ForEach-Object {$_.Name+'='+$_.Value} | Sort-Object)
 return (($f -join ';')+'|'+($s.services|ConvertTo-Json -Depth 6 -Compress))
}
function Connections([int]$port){
 try {
  $text=(Invoke-WebRequest ('http://127.0.0.1:'+$port+'/metrics') -UseBasicParsing -TimeoutSec 2).Content
  $m=[regex]::Match($text,'(?m)^cloudflared_tunnel_ha_connections ([0-9]+)\s*$')
  if($m.Success){return [int]$m.Groups[1].Value}
 }catch{}
 return 0
}
if($Mode -eq 'Stage'){
 if(Test-Path $stage){throw 'Stage already exists; inspect before retrying'}
 $settings=Settings
 [IO.Directory]::CreateDirectory($stage)|Out-Null
 Save 'before.json' ([ordered]@{at=[DateTimeOffset]::UtcNow;version=(Version $binary);hash=(Get-FileHash $binary).Hash;settings=$settings})
 Invoke-WebRequest 'https://github.com/cloudflare/cloudflared/releases/download/2026.10.3/cloudflared-windows-amd64.exe' -OutFile $candidate -UseBasicParsing -TimeoutSec 90
 if((Get-FileHash $candidate).Hash -ne $expected){throw 'Official checksum mismatch; services untouched'}
 $v=Version $candidate
 if($v -notmatch '^cloudflared version 2026\.10\.3\s'){throw 'Candidate version mismatch'}
 Save 'staged.json' ([ordered]@{at=[DateTimeOffset]::UtcNow;version=$v;sha256=$expected;source='https://github.com/cloudflare/cloudflared/releases/tag/2026.10.3'})
 [ordered]@{mode=$Mode;version=$v;checksumVerified=$true;servicesStopped=$false}|ConvertTo-Json -Compress
 return
}
$before=Get-Content (Join-Path $stage 'before.json') -Raw|ConvertFrom-Json
$current=(Settings|ConvertTo-Json -Depth 8|ConvertFrom-Json)
if((SettingsSignature $current) -ne (SettingsSignature $before.settings)){throw 'Settings changed; preserve and review'}
if($Mode -eq 'Apply'){
 if(Test-Path (Join-Path $stage 'applied.json')){throw 'Already applied; use Verify, not replay'}
 if((Get-FileHash $candidate).Hash -ne $expected -or (Get-FileHash $binary).Hash -ne $before.hash){throw 'Candidate or installed preimage changed'}
 $processes=@(Get-Process cloudflared -ErrorAction SilentlyContinue)
 if($processes.Count -ne 2 -or @($processes|Where-Object Path -ne $binary).Count){throw 'Expected exactly the two reviewed connectors'}
 foreach($n in $names){if((Get-Service $n).Status -ne 'Running'){throw 'Expected both services running before update'}}
 Save 'applying.json' ([ordered]@{at=[DateTimeOffset]::UtcNow;oldPids=@($processes.Id)})
 try {
  foreach($n in $names){Stop-Service $n; (Get-Service $n).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(25))}
  if(@(Get-Process cloudflared -ErrorAction SilentlyContinue).Count){throw 'Connector still running; binary not replaced'}
  # No downloaded old application backup; preserve all configuration and policy.
  # Windows PowerShell marshals $null to an empty string for this overload.
  # NullString passes a real null backup path, avoiding ArgumentException.
  [IO.File]::Replace($candidate,$binary,[NullString]::Value)
  if((Get-FileHash $binary).Hash -ne $expected){throw 'Installed checksum mismatch'}
 } finally {
  foreach($n in $names){if((Get-Service $n).Status -eq 'Stopped'){Start-Service $n}}
 }
 Save 'applied.json' ([ordered]@{at=[DateTimeOffset]::UtcNow;sha256=(Get-FileHash $binary).Hash})
}
if((Get-FileHash $binary).Hash -ne $expected){throw 'Installed version not patched'}
$deadline=[DateTime]::UtcNow.AddSeconds(45)
do {
 $counts=@(Connections 18081; Connections 18082)
 if($counts[0] -gt 0 -and $counts[1] -gt 0){break}
 Start-Sleep -Seconds 1
}while([DateTime]::UtcNow -lt $deadline)
if($counts[0] -lt 1 -or $counts[1] -lt 1){throw 'Patched connectors not both connected; inspect without rollback to vulnerable version'}
$processes=@(Get-Process cloudflared -ErrorAction SilentlyContinue)
$oldPids=@((Get-Content (Join-Path $stage 'applying.json') -Raw|ConvertFrom-Json).oldPids)
if($processes.Count -ne 2 -or @($processes|Where-Object {$_.Path -ne $binary -or $_.Id -in $oldPids}).Count){throw 'Running connector identities not renewed'}
$current=(Settings|ConvertTo-Json -Depth 8|ConvertFrom-Json)
if((SettingsSignature $current) -ne (SettingsSignature $before.settings)){throw 'Post-update settings mismatch'}
$url=[uri](Get-Content (Join-Path $root 'config\hiddify-subscription-url.txt') -Raw).Trim()
$response=Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 15
$profile=$response.Content|ConvertFrom-Json
if($response.StatusCode -ne 200 -or @($profile.outbounds).Count -lt 1){throw 'Public profile not available'}
$result=[ordered]@{at=[DateTimeOffset]::UtcNow;version=(Version $binary);sha256=$expected;services=@($names|ForEach-Object {Get-Service $_}|Select-Object Name,Status);runningPids=@($processes.Id);connections=$counts;settingsPreserved=$true;publicProfileStatus=$response.StatusCode;nodes=@($profile.outbounds).Count;clientPhoneTested=$false}
Save 'verified.json' $result
$result|ConvertTo-Json -Depth 5 -Compress
