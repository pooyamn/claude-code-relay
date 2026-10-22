param([Parameter(Mandatory=$true)][ValidateSet('prepare','stage','probe','activate','verify','rollback')][string]$Phase)
# Exact Web observer recovery and owner-reviewed controller handoff lane.
# No topic rebinding, native-worker restart, input replay or receipt rewrites.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote';$temp='C:\Users\pou\AppData\Local\Temp'
$release="$root\release-web-handoff-20261022"
$oldCode='F1222851B3E607CE8F1563E7D3B4A4BBF25A493786E76BDFA9FD1F9403056C9A'
$code='C58FB5EB22F673055072F6FCFFBC5A069E111279402C7680AE2F330A9D0CAA51'
$policy='6271B521E9C069618384FD6632088C7FAF06FDD1CBCB8A7CBCDC36E77215192C'
$zip='62FBC3BBEB70D782EA065E4536CC661A5EA6D3CE902DE5640FAC8B88F6A13AA2'
$publisher='6F99331B285FC1C902569722E290A2B33CEA2C6635670F2A4966231697790D4E'
$watchdog='057093FD58A701422AE7EDE4BA0022717C3702288A46C97CF57AA0989EDD6382'
$watchdogPath="$native\router-watchdog-20261014.ps1";$publishPath="$native\dispatch-controller-handoff.ps1"
$pin='01a104a6-9fce-74a3-bdb0-e6dc04237ce7'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$helper="$temp\deploy-switch-isolation-20261014.ps1"
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helpers changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Unknown','Bindings','HostIdentity','ExactTask','Fenced','Hex')){$d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true);if(-not $d){throw 'Helper missing'};. ([ScriptBlock]::Create($d.Extent.Text))}
LoadSql "$native\inspect-state.ps1" 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
function Original{if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $oldCode -or (Get-FileHash "$root\config.json").Hash -ne $policy -or (Get-FileHash $watchdogPath).Hash -ne $watchdog){throw 'Production changed; preserve'}}
function Status{[IO.File]::ReadAllText("$root\state\status.json")|ConvertFrom-Json}
function SafeStop{
 if((Get-Service KhadangRouter).Status -eq 'Running'){$s=Status;if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or @($s.nativeSessions|Where-Object {$_.binding.Runtime -eq 'windows' -and $_.busy}).Count){throw 'Do not stop active or unobserved owned Windows work'}}
 foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $name;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
}
function RestoreSupervisors($before){foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){(ExactTask $name).Enabled=[bool]$(if($name -like '*Startup'){$before.startup}else{$before.watchdog})}}
function NormalStart{
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"');StartMode='Manual'};if($r.ReturnValue){throw 'Normal path failed'};Start-Service KhadangRouter
}
if($Phase -eq 'rollback'){
 if(-not (Test-Path "$release\previous-bin\KhadangRouter.dll") -or (Get-FileHash "$release\previous-bin\KhadangRouter.dll").Hash -ne $oldCode -or (Get-FileHash "$root\config.json").Hash -ne $policy){throw 'Exact rollback artifacts required'}
 $before=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json;SafeStop
 if(Test-Path "$release\rolled-back-bin"){throw 'Prior rollback exists; reconcile'}
 Move-Item "$root\bin" "$release\rolled-back-bin";Move-Item "$release\previous-bin" "$root\bin"
 Copy-Item "$release\previous-probe.json" "$root\state\probe.json" -Force;Protect "$root\state\probe.json"
 NormalStart;RestoreSupervisors $before
 @{phase='rolled-back';inputReplay=0;policyUnchanged=$true}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'prepare'){
 Original;if(Test-Path $release){throw 'Existing release; reconcile'}
 if((Get-FileHash "$temp\router-controller-handoff-20261022.zip").Hash -ne $zip -or (Get-FileHash "$temp\dispatch-controller-handoff-20261022.ps1").Hash -ne $publisher -or (Test-Path $publishPath)){throw 'Fresh reviewed artifacts required'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 Copy-Item "$temp\router-controller-handoff-20261022.zip" "$release\candidate.zip";Protect "$release\candidate.zip"
 Copy-Item "$temp\dispatch-controller-handoff-20261022.ps1" "$release\publisher.ps1";Protect "$release\publisher.ps1"
 if((Get-FileHash "$release\candidate.zip").Hash -ne $zip -or (Get-FileHash "$release\publisher.ps1").Hash -ne $publisher){throw 'Sealed artifacts changed'}
 Add-Type -AssemblyName System.IO.Compression.FileSystem;$archive=[IO.Compression.ZipFile]::OpenRead("$release\candidate.zip")
 try{foreach($e in $archive.Entries){if($e.FullName -notmatch '^[A-Za-z0-9._-]+$' -or $e.Length -gt 200MB -or ($e.ExternalAttributes -shr 16 -band 0xF000) -eq 0xA000){throw 'Unexpected archive entry'}}}finally{$archive.Dispose()}
 [IO.Compression.ZipFile]::ExtractToDirectory("$release\candidate.zip","$release\candidate");Protect "$release\candidate" $true
 if((Get-FileHash "$release\candidate\KhadangRouter.dll").Hash -ne $code){throw 'Sealed code differs'}
 $aclTests=(& "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$release\publisher.ps1" -SelfTest)-join "`n"
 if($LASTEXITCODE -or $aclTests -notmatch '^Passed 4 controller-handoff ACL publication checks'){throw 'State ACL publication regressions failed'}
 $results=@();foreach($suite in @('--self-test-controller-handoff','--self-test-input-isolation','--self-test-startup-isolation','--self-test-transport-health','--self-test-capacity','--self-test')){
  $out=(& "$release\candidate\KhadangRouter.exe" $suite)-join "`n";if($LASTEXITCODE -or $out -notmatch '^(Passed \d+ |All \d+ PC-router checks passed)'){throw 'Sealed Windows regressions failed'};$results+=$out
 }
 Save "$release\prepared.json" @{code=$code;policy=$policy;tests=$results;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='prepared';tests=$results;productionChanged=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'stage'){
 Original;if(-not (Test-Path "$release\prepared.json") -or (Test-Path "$release\before.json")){throw 'Fresh preparation required'}
 $s=Status;$web=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $pin})
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 18 -or $web.Count -ne 1 -or $web[0].busy -or -not $web[0].nativeConnected -or @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Fresh idle Web and native custody required'}
 Save "$release\before.json" @{host=(HostIdentity);unknown=(Unknown);bindings=(Bindings);held=@($s.nativeSessions|Where-Object held|ForEach-Object {$_.binding.ThreadId});startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled;at=[DateTimeOffset]::UtcNow.ToString('o')}
 Copy-Item "$root\config.json" "$release\previous-config.json";Copy-Item "$root\state\probe.json" "$release\previous-probe.json"
 SafeStop
 # Keep the existing effective rules, but make the protected boundary explicit.
 # An inherited secure DACL is not sufficient for ProtectedPath's root pin.
 $stateAcl=Get-Acl -LiteralPath "$root\state"
 if($stateAcl.GetOwner([Security.Principal.SecurityIdentifier]).Value -notin @('S-1-5-18','S-1-5-32-544') -or (Get-Item "$root\state").Attributes -band [IO.FileAttributes]::ReparsePoint -or @($stateAcl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])|Where-Object {$_.AccessControlType -eq 'Allow' -and $_.IdentityReference.Value -notin @('S-1-5-18','S-1-5-32-544')}).Count){throw 'Unexpected state ACL; preserve'}
 Save "$release\previous-state-acl.json" @{sddl=$stateAcl.Sddl}
 $stateAcl.SetAccessRuleProtection($true,$true);Set-Acl -LiteralPath "$root\state" -AclObject $stateAcl
 if([RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('dispatching','unknown')").Length -or [RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Unsettled effects; preserve'}
 Move-Item "$root\bin" "$release\previous-bin";New-Item -ItemType Directory "$root\bin"|Out-Null;Protect "$root\bin" $true
 Copy-Item "$release\candidate\*" "$root\bin";Protect "$root\bin" $true
 Copy-Item "$release\publisher.ps1" $publishPath;Protect $publishPath
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code -or (Get-FileHash $publishPath).Hash -ne $publisher -or (Get-FileHash "$root\config.json").Hash -ne $policy){throw 'Staged artifacts differ'}
 LoadSql "$native\stage-dut-topic.ps1" '0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF' 'PcbaRegistry'
 $lease=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null
 try{
  $db=[PcbaRegistry]::new();$binding=$db.Read('SELECT payload FROM bindings WHERE chat=-1003550185469 AND topic=8660')[0][0]|ConvertFrom-Json
  if($binding.ThreadId -ne $pin -or $binding.Backend -ne 'codex' -or $binding.Runtime -ne 'linux' -or $binding.Workspace -cne '/Users/pouya/.openclaw/workspace/ai-hil/web'){throw 'Exact Web binding required'}
  $b=$db.Read("SELECT value FROM meta WHERE key='bubble/$pin'")[0][0]|ConvertFrom-Json
  if(-not $b.held -or $b.busy -or $null -ne $b.turn -or $b.sendUnknown -or $b.status -ne ('Held '+[char]0x2014+' reconcile interrupted turn') -or @($b.pendingResponses).Count -or @($b.pendingAnswers).Count){throw 'Exact idle Web observer changed'}
  $null=$db.Read("VACUUM INTO '$release\previous-router.db'");Protect "$release\previous-router.db";Save "$release\original-web-bubble.json" $b
  $b.held=$false;$b.busy=$false;$b.status='Ready';$b|Add-Member nativeStatus 'Ready' -Force
  $envelope=@{binding=$binding;bubble=$b}|ConvertTo-Json -Depth 100 -Compress
  $check=($envelope|& "$root\bin\KhadangRouter.exe" --validate-outbox)-join "`n";if($LASTEXITCODE){throw 'Outbox validation failed'}
  $v=$check|ConvertFrom-Json;if(-not $v.valid -or $v.uncertain){throw 'Web outbox remains uncertain'}
  $null=$db.Read("UPDATE meta SET value=CAST(X'$(Hex $b)' AS TEXT) WHERE key='bubble/$pin'")
  Save "$release\web-restored.json" @{thread=$pin;observerOnly=$true;latestVerifiedNativeTurn='01a10860-e657-7413-9348-8e5b77a79a0d';inputReplay=0;inputAndOperationRowsChanged=0;at=[DateTimeOffset]::UtcNow.ToString('o')}
 }finally{if($db){$db.Dispose()};$lease.Dispose()}
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
 $p|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Protected controller handoff, identical acknowledged resume reconciliation and Web observer only; policy, native connectors and independent Claude host unchanged';nativeModelTestsRerun=$false} -Force
 Save "$root\state\probe.json" $p;Save "$release\accepted.json" @{code=$code;policy=$policy;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='probe-accepted';modelsStarted=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'activate'){
 Fenced;$a=[IO.File]::ReadAllText("$release\accepted.json")|ConvertFrom-Json
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code -or (Get-FileHash "$root\config.json").Hash -ne $policy){throw 'Accepted artifacts changed'}
 NormalStart;@{phase='activated';independentNativeWorkersRestarted=0}|ConvertTo-Json -Compress;return
}
$before=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json;$a=[IO.File]::ReadAllText("$release\accepted.json")|ConvertFrom-Json;$end=[DateTimeOffset]::UtcNow.AddSeconds(55)
do{try{$s=Status}catch{$s=$null};if($s -and [DateTimeOffset]$s.at -gt [DateTimeOffset]$a.at){break};Start-Sleep -Milliseconds 500}while([DateTimeOffset]::UtcNow -lt $end)
if((Get-Service KhadangRouter).Status -ne 'Running' -or [DateTimeOffset]$s.at -le [DateTimeOffset]$a.at -or [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 18 -or -not $s.nativeTransportHealthy -or -not $s.backgroundHealthy -or -not $s.nativeLinuxConnected -or (Unknown) -cne $before.unknown -or (Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host -or @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Fresh live custody/health not confirmed'}
$held=@($s.nativeSessions|Where-Object held|ForEach-Object {$_.binding.ThreadId});$expected=@($before.held|Where-Object {$_ -ne $pin})
if(($held|Sort-Object|ConvertTo-Json -Compress) -cne ($expected|Sort-Object|ConvertTo-Json -Compress)){throw 'Unrelated holds changed or Web remains held'}
RestoreSupervisors $before
Save "$release\verified.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');routes=18;nativeDaemonPid=479;nativeTransportHealthy=$s.nativeTransportHealthy;backgroundHealthy=$s.backgroundHealthy;hostPreserved=$true;inputReplay=0;supervisorsRestored=$true;webUnheld=$true;capacity=3;phoneRoundTripVerified=$false}
[IO.File]::ReadAllText("$release\verified.json")
