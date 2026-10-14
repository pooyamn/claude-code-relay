param([Parameter(Mandatory=$true)][ValidateSet('prepare','stage','probe','activate','verify')][string]$Phase)
# Exact owner-reviewed October 14 release. No input replay, policy changes,
# forced worker recovery, credential readout, daemon restart or hold clearing.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote';$hostRoot='C:\ProgramData\KhadangClaudeHost'
$release="$root\release-startup-isolation-20261014";$temp='C:\Users\pou\AppData\Local\Temp'
$code='BA71E22CB633BCC4070EB832EC8E846F78A573F0D65FD164DBC1A6E86F9D00A2'
$oldCode='C24CDDBEA27397E0EE6EEB4E1461AA23F2027CF4836D031E886B7E0AB17F7103'
$oldHost='A2E3E8B6B0A71684A513D270E0F06D21F3A12560B99CA67AF9032F969BCFE369'
$policy='70AB674B2B297489C6C5D78965335B3E5B738E15C7F9FBCAB9D51D1A78D8A205'
$normal='"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Exact reviewed administrator deployment required'}
function Protect([string]$Path,[bool]$Directory=$false){
 $acl=if($Directory){[Security.AccessControl.DirectorySecurity]::new()}else{[Security.AccessControl.FileSecurity]::new()}
 $acl.SetAccessRuleProtection($true,$false);$acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
 foreach($sid in @('S-1-5-18','S-1-5-32-544')){
  $rule=if($Directory){[Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','ContainerInherit,ObjectInherit','None','Allow')}else{[Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','Allow')}
  $acl.AddAccessRule($rule)
 }
 Set-Acl -LiteralPath $Path -AclObject $acl
}
function Save($Path,$Value){[IO.File]::WriteAllText($Path,($Value|ConvertTo-Json -Depth 100),[Text.UTF8Encoding]::new($false));Protect $Path}
function Sql{
 $file="$native\inspect-state.ps1"
 if((Get-FileHash $file).Hash -ne 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2'){throw 'Inspection helper changed'}
 $a=[Management.Automation.Language.Parser]::ParseFile($file,[ref]$null,[ref]$null)
 $d=$a.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type'},$true)
 if(-not ('RouterReceipts' -as [type])){& ([ScriptBlock]::Create($d.Extent.Text))}
}
function Bindings{[RouterReceipts]::Read('SELECT payload FROM bindings ORDER BY chat,topic')|ConvertTo-Json -Depth 100 -Compress}
function Inputs{[RouterReceipts]::Read("SELECT id,kind,status,payload FROM operations WHERE kind IN ('native/turn/start','native/turn/steer','claude/user/send-now','claude/control/answer') ORDER BY id")|ConvertTo-Json -Depth 100 -Compress}
function Uncertainty{[RouterReceipts]::Read("SELECT id,kind,status,payload FROM operations WHERE status='unknown' AND kind<>'telegram/editMessageText' ORDER BY id")|ConvertTo-Json -Depth 100 -Compress}
function Fenced{if((Get-Service KhadangRouter).Status -ne 'Stopped' -or (Get-ScheduledTask Oracova-KhadangStartup).State -ne 'Disabled'){throw 'Stopped fenced router required'}}
Sql
if($Phase -eq 'prepare'){
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $oldCode -or (Get-FileHash "$hostRoot\bin\KhadangRouter.dll").Hash -ne $oldHost -or (Get-FileHash "$root\config.json").Hash -ne $policy -or (Test-Path $release)){throw 'Exact unchanged production and new release required'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 Copy-Item "$temp\router-startup-manifest-20261014.json" "$release\manifest.json"
 if((Get-FileHash "$release\manifest.json").Hash -ne '97EE5059AB44824598E9629363D66D4A5A45C1D892F4C97186363F561CA799AB'){throw 'Manifest mismatch'}
 New-Item -ItemType Directory "$release\candidate"|Out-Null;Protect "$release\candidate" $true
 $m=Get-Content "$release\manifest.json" -Raw -Encoding UTF8|ConvertFrom-Json
 foreach($f in $m.PSObject.Properties){if($f.Name -notmatch '^[A-Za-z0-9_.-]+$'){throw 'Invalid artifact name'};Copy-Item (Join-Path "$temp\router-startup-isolation-20261014" $f.Name) "$release\candidate";if((Get-FileHash (Join-Path "$release\candidate" $f.Name)).Hash -ne $f.Value){throw 'Sealed artifact mismatch'}}
 if((Get-FileHash "$release\candidate\KhadangRouter.dll").Hash -ne $code){throw 'Candidate changed'}
 $tests=(& "$release\candidate\KhadangRouter.exe" --self-test) -join "`n";if($LASTEXITCODE -ne 0 -or $tests -notmatch 'All \d+ PC-router checks passed'){throw 'Protected Windows full regression failed'}
 Save "$release\prepared.json" @{passed=$true;code=$code;tests=$tests;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='prepared';tests=$tests;productionChanged=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'stage'){
 $p=Get-Content "$release\prepared.json" -Raw -Encoding UTF8|ConvertFrom-Json;if(-not $p.passed -or $p.code -ne $code -or (Test-Path "$release\before.json")){throw 'Fresh tested stage required'}
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $oldCode -or (Get-FileHash "$root\config.json").Hash -ne $policy){throw 'Production changed'}
 # The current host restarted after every endpoint file. Refuse to retire
 # any present native worker; independent active custody is not in scope.
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangClaudeHost'"
 foreach($d in Get-ChildItem "$hostRoot\state" -Directory){$file=Join-Path $d.FullName 'endpoint.json';if(Test-Path $file){$e=Get-Content $file -Raw -Encoding UTF8|ConvertFrom-Json;if($e.Server.Pid -eq $svc.ProcessId){throw 'Live worker custody exists; do not restart host'}}}
 Save "$release\before.json" @{bindings=(Bindings);inputs=(Inputs);unknown=(Uncertainty);startup=(Get-ScheduledTask Oracova-KhadangStartup).State.ToString();at=[DateTimeOffset]::UtcNow.ToString('o')}
 [IO.File]::WriteAllText("$release\startup-before.xml",(Export-ScheduledTask Oracova-KhadangStartup),[Text.UTF8Encoding]::new($false))
 Disable-ScheduledTask Oracova-KhadangStartup|Out-Null;Stop-ScheduledTask Oracova-KhadangStartup
 try{Stop-Service KhadangRouter}catch{};(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 if([RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('received','dispatching','unknown')").Length -or [RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Unsettled intake/effects; preserve'}
 $lease=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None')
 try{
  foreach($name in @('router.db','router.db-wal','router.db-shm','probe.json')){if(Test-Path "$root\state\$name"){Copy-Item "$root\state\$name" "$release\before-$name"}}
  foreach($pair in @(@($root,'router'),@($hostRoot,'host'))){foreach($name in @('KhadangRouter.dll','KhadangRouter.exe','KhadangRouter.deps.json','KhadangRouter.runtimeconfig.json')){Copy-Item "$($pair[0])\bin\$name" "$release\before-$($pair[1])-$name"}}
  Copy-Item "$hostRoot\installed.json" "$release\before-host-installed.json"
  Stop-Service KhadangClaudeHost;(Get-Service KhadangClaudeHost).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30))
  foreach($dir in @("$root\bin","$hostRoot\bin")){Copy-Item "$release\candidate\*" $dir -Force;Get-ChildItem $dir -File|ForEach-Object {Protect $_.FullName}}
  $installed=Get-Content "$hostRoot\installed.json" -Raw -Encoding UTF8|ConvertFrom-Json;$installed.dll=$code;$installed.exe=(Get-FileHash "$hostRoot\bin\KhadangRouter.exe").Hash;$installed.generation='startup-isolation-20261014';$installed.at=[DateTimeOffset]::UtcNow.ToString('o');Save "$hostRoot\installed.json" $installed
 }finally{$lease.Dispose()}
 if((Bindings) -cne (Get-Content "$release\before.json" -Raw -Encoding UTF8|ConvertFrom-Json).bindings -or (Uncertainty) -cne (Get-Content "$release\before.json" -Raw -Encoding UTF8|ConvertFrom-Json).unknown){throw 'Original registry/uncertainty changed'}
 Save "$release\staged.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');code=$code;policy=$policy};@{phase='staged';inputsReplayed=0;liveWorkersInterrupted=0}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'probe'){
 Fenced;$s=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $r=Invoke-CimMethod -InputObject $s -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --probe-service --config "'+$root+'\config.json"');StartMode='Manual'};if($r.ReturnValue){throw 'Probe path failed'}
 Start-Service KhadangRouter
 # Probe service deliberately waits for SCM cancellation after writing proof.
 # Wait for fresh exact proof, then stop this no-poll/no-model probe ourselves.
 $deadline=[DateTimeOffset]::UtcNow.AddSeconds(45)
 $stage=Get-Content "$release\staged.json" -Raw -Encoding UTF8|ConvertFrom-Json
 do {
  $p=Get-Content "$root\state\probe.json" -Raw -Encoding UTF8|ConvertFrom-Json
  if($p.routerSha256 -eq $code -and $p.verified -and [DateTimeOffset]$p.testedAt -gt [DateTimeOffset]$stage.at){break}
  Start-Sleep -Seconds 1
 }while([DateTimeOffset]::UtcNow -lt $deadline)
 if($p.routerSha256 -ne $code -or -not $p.verified -or [DateTimeOffset]$p.testedAt -le [DateTimeOffset]$stage.at){throw 'Fresh probe proof timed out'}
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30))
 @{phase='probe-passed';modelsStarted=$false;telegramPolling=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'activate'){
 Fenced;$p=Get-Content "$root\state\probe.json" -Raw -Encoding UTF8|ConvertFrom-Json;$old=Get-Content "$release\before-probe.json" -Raw -Encoding UTF8|ConvertFrom-Json;$stage=Get-Content "$release\staged.json" -Raw -Encoding UTF8|ConvertFrom-Json
 if($p.routerSha256 -ne $code -or $p.policySha256 -ne $policy -or -not $p.verified -or -not $p.credentialAndCodeDenied -or -not $p.nativeLinuxCommandOwnerVerified -or -not $p.nativeWindowsSandboxVerified -or -not $p.nativePersistentClaudeHostAclDenied -or [DateTimeOffset]$p.testedAt -le [DateTimeOffset]$stage.at -or $p.modelInference -or $p.telegramPolling -or -not $old.nativeLinuxClaudeContinuityVerified){throw 'Fresh exact OS proof required'}
 foreach($field in @('nativeLinuxClaudeLaunchVerified','nativeLinuxClaudeToolOwnerVerified','nativeLinuxClaudeContinuityVerified','nativeLinuxClaudeAcceptance')){if($old.PSObject.Properties[$field]){$p|Add-Member $field $old.$field -Force}}
 $p|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Existing protected connector/checkpoint/launcher retained; new admission isolation and host version tested; no paid acceptance prompt';priorHost=$oldHost;nativeModelTestsRerun=$false} -Force
 Save "$root\state\probe.json" $p
 $s=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $s -MethodName Change -Arguments @{PathName=$normal;StartMode='Manual'};if($r.ReturnValue){throw 'Normal service path failed'}
 Save "$release\activation.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');code=$code};Start-Service KhadangClaudeHost;Start-Service KhadangRouter
 @{phase='activated';inputsReplayed=0;policyChanged=$false}|ConvertTo-Json -Compress;return
}
$s=Get-Content "$root\state\status.json" -Raw -Encoding UTF8|ConvertFrom-Json;$before=Get-Content "$release\before.json" -Raw -Encoding UTF8|ConvertFrom-Json
if((Get-Service KhadangRouter).Status -ne 'Running' -or [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 17 -or (Bindings) -cne $before.bindings -or (Uncertainty) -cne $before.unknown){throw 'Fresh exact routes and retained uncertainty required'}
if($before.startup -ne 'Disabled'){Enable-ScheduledTask Oracova-KhadangStartup|Out-Null}
Save "$release\verified.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');code=$code;routes=17;daemonUnchanged=$true;unknownUploadPreserved=$true;heldSessions=$s.heldSessions;claudeConnected=@($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and $_.claudeConnected}).Count}
Get-Content "$release\verified.json" -Raw -Encoding UTF8
