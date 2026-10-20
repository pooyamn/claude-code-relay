param([Parameter(Mandatory=$true)][ValidateSet('prepare','stage','probe','activate','verify')][string]$Phase)
# Connector-only idle-read repair. No daemon/Claude-host replacement, native
# retry, registry mutation, hold clearing, token change or model inference.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote';$temp='C:\Users\pou\AppData\Local\Temp'
$release="$root\release-native-idle-20261020"
$code='A0D694DA58801A58F5EEBE1B31BC582707445D58060D4A3EC640EC9759055B33'
$oldPolicy='5A2E3C1B24BCC1638CBCF202472C836DD2A3307411CBFDEE4B874E1C0D51E4DE'
$connector='950C02C0B018155ADDF1352DAF02FB1FF2BA56A32354EC01D114E5665F0435CC'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed administrator required'}
$helper="$temp\deploy-switch-isolation-20261014.ps1"
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helpers changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Unknown','Bindings','HostIdentity','ExactTask','Fenced')){$d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true);if(-not $d){throw 'Helper missing'};. ([ScriptBlock]::Create($d.Extent.Text))}
LoadSql "$native\inspect-state.ps1" 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
function Original{if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code -or (Get-FileHash "$root\config.json").Hash -ne $oldPolicy){throw 'Production changed; preserve'}}
if($Phase -eq 'prepare'){
 Original;if(Test-Path $release){throw 'Existing release; reconcile'}
 if((Get-FileHash "$temp\pc_native_stdio-idle-20261020.py").Hash -ne $connector){throw 'Reviewed connector differs'}
 # This deployment does not change/rebuild the already-tested router binary.
 $tested=[IO.File]::ReadAllText("$root\release-dut-queue-20261020\prepared.json")|ConvertFrom-Json
 if($tested.code -ne $code -or $tested.tests -ne 'All 1466 PC-router checks passed (no credentials/network/models).'){throw 'Exact unchanged Windows artifact acceptance required'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 $p=[IO.File]::ReadAllText("$root\config.json")|ConvertFrom-Json;$previous=$p.LinuxCodex.PackageRoot;$next="$native\codex-connector-"+[Guid]::NewGuid().ToString('N')
 New-Item -ItemType Directory $next|Out-Null;Set-Acl $next (Get-Acl $previous)
 foreach($f in $p.LinuxCodex.FileSha256.PSObject.Properties){$from=Join-Path $previous $f.Name;$to=Join-Path $next $f.Name;if((Get-FileHash $from).Hash -ne $f.Value){throw 'Prior connector changed'};$parent=Split-Path $to;if(-not (Test-Path $parent)){New-Item -ItemType Directory $parent|Out-Null;Set-Acl $parent (Get-Acl (Split-Path $from))};if($f.Name -eq 'pc_native_stdio.py'){Copy-Item "$temp\pc_native_stdio-idle-20261020.py" $to}else{Copy-Item $from $to};Set-Acl $to (Get-Acl $from)}
 $p.LinuxCodex.PackageRoot=$next;$p.LinuxCodex.FileSha256.'pc_native_stdio.py'=$connector
 Save "$release\next-policy.json" $p;Save "$release\prepared.json" @{code=$code;policy=(Get-FileHash "$release\next-policy.json").Hash;connector=$next;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='prepared';productionChanged=$false;routerBinaryUnchanged=$true}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'stage'){
 Original;if(-not (Test-Path "$release\prepared.json") -or (Test-Path "$release\before.json")){throw 'Fresh prepared stage required'}
 $s=[IO.File]::ReadAllText("$root\state\status.json")|ConvertFrom-Json
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 18 -or @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Fresh live custody required'}
 Save "$release\before.json" @{host=(HostIdentity);unknown=(Unknown);bindings=(Bindings);held=@($s.nativeSessions|Where-Object held|ForEach-Object {$_.binding.ThreadId});startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled;at=[DateTimeOffset]::UtcNow.ToString('o')}
 Copy-Item "$root\config.json" "$release\previous-config.json";Copy-Item "$root\state\probe.json" "$release\previous-probe.json"
 foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $name;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 if([RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('dispatching','unknown')").Length -or [RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Unsettled effects; preserve'}
 Copy-Item "$release\next-policy.json" "$root\config.json" -Force;Protect "$root\config.json"
 Save "$release\staged.json" @{code=$code;policy=(Get-FileHash "$root\config.json").Hash;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='staged';nativeWorkersRestarted=0;inputsReplayed=0}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'probe'){
 Fenced;$svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --probe-service --config "'+$root+'\config.json"');StartMode='Manual'};if($r.ReturnValue){throw 'Probe path failed'};Start-Service KhadangRouter
 $stage=[IO.File]::ReadAllText("$release\staged.json")|ConvertFrom-Json;$end=[DateTimeOffset]::UtcNow.AddSeconds(55)
 do{$p=[IO.File]::ReadAllText("$root\state\probe.json")|ConvertFrom-Json;if($p.routerSha256 -eq $code -and $p.policySha256 -eq $stage.policy -and $p.verified -and [DateTimeOffset]$p.testedAt -gt [DateTimeOffset]$stage.at){break};Start-Sleep -Milliseconds 500}while([DateTimeOffset]::UtcNow -lt $end)
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 if($p.routerSha256 -ne $code -or $p.policySha256 -ne $stage.policy -or -not $p.verified -or -not $p.credentialAndCodeDenied -or -not $p.nativeWindowsSandboxVerified -or -not $p.nativeLinuxCommandOwnerVerified -or $p.modelInference -or $p.telegramPolling -or [DateTimeOffset]$p.testedAt -le [DateTimeOffset]$stage.at){throw 'Fresh SYSTEM security proof required'}
 Save "$release\generic-proof.json" $p;$old=[IO.File]::ReadAllText("$release\previous-probe.json")|ConvertFrom-Json
 $a=[IO.File]::ReadAllText("$release\previous-config.json")|ConvertFrom-Json;$b=[IO.File]::ReadAllText("$root\config.json")|ConvertFrom-Json
 if(($a.LinuxClaude|ConvertTo-Json -Depth 50 -Compress) -cne ($b.LinuxClaude|ConvertTo-Json -Depth 50 -Compress) -or -not $old.nativeLinuxClaudeContinuityVerified){throw 'Unchanged independent Claude acceptance required'}
 foreach($field in @('nativeLinuxClaudeLaunchVerified','nativeLinuxClaudeToolOwnerVerified','nativeLinuxClaudeContinuityVerified','nativeLinuxClaudeAcceptance')){if($old.PSObject.Properties[$field]){$p|Add-Member $field $old.$field -Force}}
 $p|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Codex connector idle-read change only; independent Claude connector and host unchanged';nativeModelTestsRerun=$false} -Force
 Save "$root\state\probe.json" $p;Save "$release\accepted.json" @{code=$code;policy=$stage.policy;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='probe-accepted';modelsStarted=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'activate'){
 Fenced;$a=[IO.File]::ReadAllText("$release\accepted.json")|ConvertFrom-Json
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code -or (Get-FileHash "$root\config.json").Hash -ne $a.policy){throw 'Accepted artifacts changed'}
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"');StartMode='Manual'};if($r.ReturnValue){throw 'Normal path failed'};Start-Service KhadangRouter
 @{phase='activated';nativeWorkersRestarted=0}|ConvertTo-Json -Compress;return
}
$s=[IO.File]::ReadAllText("$root\state\status.json")|ConvertFrom-Json;$before=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json;$a=[IO.File]::ReadAllText("$release\accepted.json")|ConvertFrom-Json
$base=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq '01a104cc-9a63-7901-8897-abf8aff3dfb3'})
if((Get-Service KhadangRouter).Status -ne 'Running' -or [DateTimeOffset]$s.at -le [DateTimeOffset]$a.at -or [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 18 -or $base.Count -ne 1 -or $base[0].held -or (Unknown) -cne $before.unknown -or (Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host -or @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Fresh live custody/Base readiness not confirmed'}
foreach($id in $before.held){if(@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $id -and $_.held}).Count -ne 1){throw 'Unrelated hold changed'}}
foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){(ExactTask $name).Enabled=[bool]$(if($name -like '*Startup'){$before.startup}else{$before.watchdog})}
Save "$release\verified.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');baseReady=$true;routes=18;nativeDaemonPid=479;hostPreserved=$true;inputReplay=0;startupRestored=$true}
[IO.File]::ReadAllText("$release\verified.json")
