param([Parameter(Mandatory=$true)][ValidateSet('prepare','stage','probe','activate','verify','rollback')][string]$Phase)
# Reviewed router/watchdog-only release. No input, queue, registry or receipt
# mutation; independent native workers remain online. All artifacts are pinned.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote';$temp='C:\Users\pou\AppData\Local\Temp'
$release="$root\release-transport-health-20261020-v3"
$oldCode='A0D694DA58801A58F5EEBE1B31BC582707445D58060D4A3EC640EC9759055B33'
$code='DCE7732FB9B5CC2E9CF2A9420A3E69DF0D7F30A1C35103AEB88FD01B00E9DB8D'
$policy='6271B521E9C069618384FD6632088C7FAF06FDD1CBCB8A7CBCDC36E77215192C'
$zip='D84886077390E8A933D0BFC0EAEBC65E2E3CAA5BB65BC26DA6EE8B4CFDAC354E'
$watchdog='057093FD58A701422AE7EDE4BA0022717C3702288A46C97CF57AA0989EDD6382'
$oldWatchdog='B69990052A673655099A5C11A962DE1CD9D43DF3B38358857330A2B9E39FB52A'
$watchdogPath="$native\router-watchdog-20261014.ps1"
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$helper="$temp\deploy-switch-isolation-20261014.ps1"
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helpers changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Unknown','Bindings','HostIdentity','ExactTask','Fenced')){$d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true);if(-not $d){throw 'Helper missing'};. ([ScriptBlock]::Create($d.Extent.Text))}
LoadSql "$native\inspect-state.ps1" 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
function Original{if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $oldCode -or (Get-FileHash "$root\config.json").Hash -ne $policy -or (Get-FileHash $watchdogPath).Hash -ne $oldWatchdog){throw 'Production changed; preserve'}}
function Status{[IO.File]::ReadAllText("$root\state\status.json")|ConvertFrom-Json}
if($Phase -eq 'rollback'){
 if(-not (Test-Path "$release\previous-bin\KhadangRouter.dll") -or (Get-FileHash "$release\previous-bin\KhadangRouter.dll").Hash -ne $oldCode -or (Get-FileHash "$root\config.json").Hash -ne $policy){throw 'Exact rollback artifacts required'}
 $before=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json
 if((Get-Service KhadangRouter).Status -eq 'Running'){$s=Status;if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or @($s.nativeSessions|Where-Object {$_.binding.Runtime -eq 'windows' -and $_.busy}).Count){throw 'Do not stop active or unobserved owned Windows work'}}
 foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $name;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 if(Test-Path "$release\rolled-back-bin"){throw 'Prior rollback exists; reconcile'}
 Move-Item "$root\bin" "$release\rolled-back-bin";Move-Item "$release\previous-bin" "$root\bin"
 Copy-Item "$release\previous-watchdog.ps1" $watchdogPath -Force;Protect $watchdogPath
 Copy-Item "$release\previous-probe.json" "$root\state\probe.json" -Force;Protect "$root\state\probe.json"
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"');StartMode='Manual'};if($r.ReturnValue){throw 'Rollback normal path failed'};Start-Service KhadangRouter
 foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){(ExactTask $name).Enabled=[bool]$(if($name -like '*Startup'){$before.startup}else{$before.watchdog})}
 @{phase='rolled-back';inputReplay=0;policyUnchanged=$true}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'prepare'){
 Original;if(Test-Path $release){throw 'Existing release; reconcile'}
 if((Get-FileHash "$temp\router-transport-health-20261020-v3.zip").Hash -ne $zip -or (Get-FileHash "$temp\router-watchdog-health-20261020.ps1").Hash -ne $watchdog){throw 'Candidate changed'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 Copy-Item "$temp\router-transport-health-20261020-v3.zip" "$release\candidate.zip";Protect "$release\candidate.zip"
 Copy-Item "$temp\router-watchdog-health-20261020.ps1" "$release\watchdog.ps1";Protect "$release\watchdog.ps1"
 if((Get-FileHash "$release\candidate.zip").Hash -ne $zip -or (Get-FileHash "$release\watchdog.ps1").Hash -ne $watchdog){throw 'Sealed artifacts changed'}
 Add-Type -AssemblyName System.IO.Compression.FileSystem
 $archive=[IO.Compression.ZipFile]::OpenRead("$release\candidate.zip")
 try{foreach($e in $archive.Entries){if($e.FullName -notmatch '^[A-Za-z0-9._-]+$' -or $e.Length -gt 200MB -or ($e.ExternalAttributes -shr 16 -band 0xF000) -eq 0xA000){throw 'Unexpected archive entry'}}}finally{$archive.Dispose()}
 [IO.Compression.ZipFile]::ExtractToDirectory("$release\candidate.zip","$release\candidate");Protect "$release\candidate" $true
 if((Get-FileHash "$release\candidate\KhadangRouter.dll").Hash -ne $code){throw 'Sealed code differs'}
 $target=(& "$release\candidate\KhadangRouter.exe" --self-test-transport-health)-join "`n";if($LASTEXITCODE -or $target -notmatch '^Passed 38 transport-health checks'){throw 'Windows transport regressions failed'}
 foreach($suite in @('--self-test-input-isolation','--self-test-startup-isolation')){$out=(& "$release\candidate\KhadangRouter.exe" $suite)-join "`n";if($LASTEXITCODE -or $out -notmatch '^Passed \d+ '){throw 'Windows named artifact regression failed'}}
 $tests=(& "$release\candidate\KhadangRouter.exe" --self-test)-join "`n";if($LASTEXITCODE -or $tests -notmatch '^All \d+ PC-router checks passed'){throw 'Windows full regressions failed'}
 $wd=(& "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$release\watchdog.ps1" -SelfTest)-join "`n";if($LASTEXITCODE -or $wd -notmatch '^Passed 25 watchdog decisions'){throw 'Watchdog regressions failed'}
 Save "$release\prepared.json" @{code=$code;policy=$policy;target=$target;tests=$tests;watchdog=$wd;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='prepared';tests=$tests;target=$target;watchdog=$wd;productionChanged=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'stage'){
 Original;if(-not (Test-Path "$release\prepared.json") -or (Test-Path "$release\before.json")){throw 'Fresh preparation required'}
 $s=Status
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 18 -or @($s.nativeSessions|Where-Object {$_.binding.Runtime -eq 'windows' -and $_.busy}).Count -or @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Fresh native custody and idle owned Windows work required'}
 Save "$release\before.json" @{host=(HostIdentity);unknown=(Unknown);bindings=(Bindings);held=@($s.nativeSessions|Where-Object held|ForEach-Object {$_.binding.ThreadId});startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled;at=[DateTimeOffset]::UtcNow.ToString('o')}
 Copy-Item "$root\config.json" "$release\previous-config.json";Copy-Item "$root\state\probe.json" "$release\previous-probe.json";Copy-Item $watchdogPath "$release\previous-watchdog.ps1"
 foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $name;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 if([RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('dispatching','unknown')").Length -or [RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Unsettled effects; preserve'}
 Move-Item "$root\bin" "$release\previous-bin";New-Item -ItemType Directory "$root\bin"|Out-Null;Protect "$root\bin" $true
 Copy-Item "$release\candidate\*" "$root\bin";Protect "$root\bin" $true
 Copy-Item "$release\watchdog.ps1" $watchdogPath -Force;Protect $watchdogPath
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code -or (Get-FileHash $watchdogPath).Hash -ne $watchdog -or (Get-FileHash "$root\config.json").Hash -ne $policy){throw 'Staged artifacts differ'}
 Save "$release\staged.json" @{code=$code;policy=$policy;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='staged';independentNativeWorkersRestarted=0;inputsReplayed=0}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'probe'){
 Fenced;$svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --probe-service --config "'+$root+'\config.json"');StartMode='Manual'};if($r.ReturnValue){throw 'Probe path failed'};Start-Service KhadangRouter
 $stage=[IO.File]::ReadAllText("$release\staged.json")|ConvertFrom-Json;$end=[DateTimeOffset]::UtcNow.AddSeconds(55)
 do{$p=[IO.File]::ReadAllText("$root\state\probe.json")|ConvertFrom-Json;if($p.routerSha256 -eq $code -and $p.policySha256 -eq $policy -and $p.verified -and [DateTimeOffset]$p.testedAt -gt [DateTimeOffset]$stage.at){break};Start-Sleep -Milliseconds 500}while([DateTimeOffset]::UtcNow -lt $end)
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 if($p.routerSha256 -ne $code -or $p.policySha256 -ne $policy -or -not $p.verified -or -not $p.credentialAndCodeDenied -or -not $p.nativeWindowsSandboxVerified -or -not $p.nativeLinuxCommandOwnerVerified -or $p.modelInference -or $p.telegramPolling -or [DateTimeOffset]$p.testedAt -le [DateTimeOffset]$stage.at){throw 'Fresh SYSTEM security proof required'}
 Save "$release\generic-proof.json" $p;$old=[IO.File]::ReadAllText("$release\previous-probe.json")|ConvertFrom-Json
 if((Get-FileHash "$root\config.json").Hash -ne $policy -or -not $old.nativeLinuxClaudeContinuityVerified){throw 'Unchanged native host/connector acceptance required'}
 foreach($field in @('nativeLinuxClaudeLaunchVerified','nativeLinuxClaudeToolOwnerVerified','nativeLinuxClaudeContinuityVerified','nativeLinuxClaudeAcceptance')){if($old.PSObject.Properties[$field]){$p|Add-Member $field $old.$field -Force}}
 $p|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Router observer and watchdog only; policy, native connectors and independent Claude host unchanged';nativeModelTestsRerun=$false} -Force
 Save "$root\state\probe.json" $p;Save "$release\accepted.json" @{code=$code;policy=$policy;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='probe-accepted';modelsStarted=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'activate'){
 Fenced;$a=[IO.File]::ReadAllText("$release\accepted.json")|ConvertFrom-Json
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code -or (Get-FileHash "$root\config.json").Hash -ne $policy){throw 'Accepted artifacts changed'}
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"');StartMode='Manual'};if($r.ReturnValue){throw 'Normal path failed'};Start-Service KhadangRouter
 @{phase='activated';independentNativeWorkersRestarted=0}|ConvertTo-Json -Compress;return
}
$s=Status;$before=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json;$a=[IO.File]::ReadAllText("$release\accepted.json")|ConvertFrom-Json
if((Get-Service KhadangRouter).Status -ne 'Running' -or [DateTimeOffset]$s.at -le [DateTimeOffset]$a.at -or [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 18 -or -not $s.nativeTransportHealthy -or -not $s.backgroundHealthy -or -not $s.nativeLinuxConnected -or (Unknown) -cne $before.unknown -or (Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host -or @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Fresh live custody/health not confirmed'}
$held=@($s.nativeSessions|Where-Object held|ForEach-Object {$_.binding.ThreadId})
if(($held|Sort-Object|ConvertTo-Json -Compress) -cne ($before.held|Sort-Object|ConvertTo-Json -Compress)){throw 'Topic holds changed'}
foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){(ExactTask $name).Enabled=[bool]$(if($name -like '*Startup'){$before.startup}else{$before.watchdog})}
Save "$release\verified.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');routes=18;nativeDaemonPid=479;nativeTransportHealthy=$s.nativeTransportHealthy;backgroundHealthy=$s.backgroundHealthy;hostPreserved=$true;inputReplay=0;supervisorsRestored=$true;phoneRoundTripVerified=$false}
[IO.File]::ReadAllText("$release\verified.json")
