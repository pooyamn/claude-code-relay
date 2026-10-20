param([Parameter(Mandatory=$true)][ValidateSet('prepare','stage','probe','activate','verify')][string]$Phase)
# One-time fast-topic rollout. Normal topic creation never invokes this script.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote';$temp='C:\Users\pou\AppData\Local\Temp'
$release="$root\release-topic-fast-20261020"
$old='33BB1D3255662CF185B69A356A4A76F4AE89209685AEDEF789BDE10FA7055B62'
$oldPolicy='70AB674B2B297489C6C5D78965335B3E5B738E15C7F9FBCAB9D51D1A78D8A205'
$code='A0D694DA58801A58F5EEBE1B31BC582707445D58060D4A3EC640EC9759055B33'
$manifest='3B185212FA8CD3703D036DF7EFF0C2F505292A153AAF1FDD9DD0243A3CD7F30C'
$connector='572DC686CA54495A1AAC11458411597E8C459A9F7980A9FEEB59E86C5B11FDC8'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$helper="$temp\deploy-switch-isolation-20261014.ps1"
$bytes=[IO.File]::ReadAllBytes($helper)
if([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($bytes)).Replace('-','') -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helper changed'}
$ast=[Management.Automation.Language.Parser]::ParseInput([Text.Encoding]::UTF8.GetString($bytes),[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Unknown','Bindings','HostIdentity','ExactTask','Fenced')){
 $d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true)
 if(-not $d){throw 'Reviewed helper missing'};. ([ScriptBlock]::Create($d.Extent.Text))
}
LoadSql "$native\inspect-state.ps1" 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
function Original{if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $old -or (Get-FileHash "$root\config.json").Hash -ne $oldPolicy){throw 'Production changed; preserve'}}
if($Phase -ne 'prepare'){$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()}
if($Phase -eq 'prepare'){
 Original;if(Test-Path $release){throw 'Existing release; reconcile'}
 if((Get-FileHash "$temp\router-topic-fast-manifest-20261020.json").Hash -ne $manifest -or (Get-FileHash "$temp\pc_native_stdio-topic-fast-20261020.py").Hash -ne $connector){throw 'Reviewed artifact mismatch'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 Copy-Item "$temp\router-topic-fast-manifest-20261020.json" "$release\manifest.json"
 New-Item -ItemType Directory "$release\candidate"|Out-Null;Protect "$release\candidate" $true
 $m=[IO.File]::ReadAllText("$release\manifest.json")|ConvertFrom-Json
 foreach($f in $m.PSObject.Properties){
  if($f.Name -notmatch '^[A-Za-z0-9_.-]+$'){throw 'Invalid candidate filename'}
  $path=Join-Path "$release\candidate" $f.Name;Copy-Item (Join-Path "$temp\router-topic-fast-20261020-v3" $f.Name) $path
  if((Get-FileHash $path).Hash -ne $f.Value){throw 'Sealed artifact differs'}
 }
 $targeted=(& "$release\candidate\KhadangRouter.exe" --self-test-topics)-join "`n";if($LASTEXITCODE){throw 'Sealed Windows topic tests failed'}
 $tests=(& "$release\candidate\KhadangRouter.exe" --self-test)-join "`n";if($LASTEXITCODE){throw 'Sealed full Windows tests failed'}
 $p=[IO.File]::ReadAllText("$root\config.json")|ConvertFrom-Json
 $previous=$p.LinuxCodex.PackageRoot;$next="$native\codex-connector-"+[Guid]::NewGuid().ToString('N')
 New-Item -ItemType Directory $next|Out-Null;Set-Acl $next (Get-Acl $previous)
 foreach($f in $p.LinuxCodex.FileSha256.PSObject.Properties){
  $source=Join-Path $previous $f.Name;$destination=Join-Path $next $f.Name
  if((Get-FileHash $source).Hash -ne $f.Value){throw 'Existing connector differs'}
  $parent=Split-Path $destination
  if(-not (Test-Path $parent)){New-Item -ItemType Directory $parent|Out-Null;Set-Acl $parent (Get-Acl (Split-Path $source))}
  if($f.Name -eq 'pc_native_stdio.py'){Copy-Item "$temp\pc_native_stdio-topic-fast-20261020.py" $destination}
  else{Copy-Item $source $destination}
  Set-Acl $destination (Get-Acl $source)
 }
 if((Get-FileHash "$next\pc_native_stdio.py").Hash -ne $connector){throw 'Sealed connector differs'}
 $p.LinuxCodex.PackageRoot=$next;$p.LinuxCodex.FileSha256.'pc_native_stdio.py'=$connector
 Save "$release\next-policy.json" $p
 Save "$release\prepared.json" @{code=$code;targeted=$targeted;tests=$tests;policy=(Get-FileHash "$release\next-policy.json").Hash;connector=$next;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='prepared';productionChanged=$false;targeted=$targeted}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'stage'){
 Original;if(-not (Test-Path "$release\prepared.json") -or (Test-Path "$release\before.json")){throw 'Fresh prepared stage required'}
 $s=[IO.File]::ReadAllText("$root\state\status.json")|ConvertFrom-Json
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 18 -or @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and ($_.busy -or (-not $_.held -and -not $_.claudeConnected))}).Count){throw 'Fresh exact quiescent native custody required'}
 $held=[RouterReceipts]::Read("SELECT key,value FROM meta WHERE key LIKE 'bubble/%' AND json_extract(value,'$.held')=1")
 Save "$release\before.json" @{host=(HostIdentity);unknown=(Unknown);bindings=(Bindings);held=$held;nativeHeld=@($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and $_.held}|ForEach-Object {$_.binding.ThreadId});startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled;at=[DateTimeOffset]::UtcNow.ToString('o')}
 Copy-Item "$root\config.json" "$release\previous-config.json";Copy-Item "$root\state\probe.json" "$release\previous-probe.json"
 foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $name;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
 try{Stop-Service KhadangRouter}catch{if((Get-Service KhadangRouter).Status -ne 'Stopped'){throw}}
 (Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 if([RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('dispatching','unknown')").Length -or [RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Unsettled effects; preserve'}
 Copy-Item "$root\bin" "$release\previous-bin" -Recurse
 Copy-Item "$release\candidate\*" "$root\bin" -Force;Get-ChildItem "$root\bin" -File|ForEach-Object {Protect $_.FullName}
 Copy-Item "$release\next-policy.json" "$root\config.json" -Force;Protect "$root\config.json"
 Save "$release\staged.json" @{code=$code;policy=(Get-FileHash "$root\config.json").Hash;nativeWorkersStopped=0;ledgerRowsRewritten=0;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='staged';nativeWorkersStopped=0;nativeInputReplayed=0}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'probe'){
 Fenced;$svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $result=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --probe-service --config "'+$root+'\config.json"');StartMode='Manual'}
 if($result.ReturnValue){throw 'Probe service path failed'};Start-Service KhadangRouter
 $stage=[IO.File]::ReadAllText("$release\staged.json")|ConvertFrom-Json;$end=[DateTimeOffset]::UtcNow.AddSeconds(55)
 do{$p=[IO.File]::ReadAllText("$root\state\probe.json")|ConvertFrom-Json;if($p.routerSha256 -eq $code -and $p.policySha256 -eq $stage.policy -and $p.verified -and [DateTimeOffset]$p.testedAt -gt [DateTimeOffset]$stage.at){break};Start-Sleep -Seconds 1}while([DateTimeOffset]::UtcNow -lt $end)
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 if($p.routerSha256 -ne $code -or $p.policySha256 -ne $stage.policy -or -not $p.verified -or -not $p.credentialAndCodeDenied -or -not $p.nativeWindowsSandboxVerified -or -not $p.nativeLinuxCommandOwnerVerified -or $p.modelInference -or $p.telegramPolling -or [DateTimeOffset]$p.testedAt -le [DateTimeOffset]$stage.at){throw 'Fresh exact OS proof required'}
 Save "$release\generic-proof.json" $p
 $oldProof=[IO.File]::ReadAllText("$release\previous-probe.json")|ConvertFrom-Json
 $oldConfig=[IO.File]::ReadAllText("$release\previous-config.json")|ConvertFrom-Json;$newConfig=[IO.File]::ReadAllText("$root\config.json")|ConvertFrom-Json
 if(($oldConfig.LinuxClaude|ConvertTo-Json -Depth 50 -Compress) -cne ($newConfig.LinuxClaude|ConvertTo-Json -Depth 50 -Compress) -or -not $oldProof.nativeLinuxClaudeContinuityVerified){throw 'Unchanged independent Claude acceptance required'}
 foreach($field in @('nativeLinuxClaudeLaunchVerified','nativeLinuxClaudeToolOwnerVerified','nativeLinuxClaudeContinuityVerified','nativeLinuxClaudeAcceptance')){if($oldProof.PSObject.Properties[$field]){$p|Add-Member $field $oldProof.$field -Force}}
 $p|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Hot Codex topic creation only; independent Claude host/connectors unchanged';nativeModelTestsRerun=$false} -Force
 Save "$root\state\probe.json" $p;Save "$release\accepted.json" @{code=$code;policy=$stage.policy;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='probe-accepted';modelsStarted=$false;telegramPolling=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'activate'){
 Fenced;$accepted=[IO.File]::ReadAllText("$release\accepted.json")|ConvertFrom-Json
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code -or (Get-FileHash "$root\config.json").Hash -ne $accepted.policy){throw 'Accepted artifacts changed'}
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"');StartMode='Manual'}
 if($r.ReturnValue){throw 'Normal service path failed'};Start-Service KhadangRouter
 @{phase='activated';nativeWorkersPreserved=$true}|ConvertTo-Json -Compress;return
}
$s=[IO.File]::ReadAllText("$root\state\status.json")|ConvertFrom-Json;$before=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json;$accepted=[IO.File]::ReadAllText("$release\accepted.json")|ConvertFrom-Json
if((Get-Service KhadangRouter).Status -ne 'Running' -or [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or [DateTimeOffset]$s.at -le [DateTimeOffset]$accepted.at -or
 $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 18 -or (Unknown) -cne $before.unknown -or (Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host){throw 'Fresh exact live custody required'}
foreach($row in $before.held){$now=[RouterReceipts]::Read("SELECT value FROM meta WHERE key='$($row[0])'");if($now.Length -ne 1 -or -not ($now[0][0]|ConvertFrom-Json).held){throw 'Existing hold changed'}}
$heldIds=@($before.held|ForEach-Object {$_.GetValue(0).Substring(7)})
$heldIds+=@($before.nativeHeld)
if(-not $before.PSObject.Properties['nativeHeld']){
 # This release's original snapshot captured durable bubbles, not startup-only
 # holds. Recover that missing baseline ONLY from the older enrollment backup,
 # never from the post-cutover status or newly written startup-held receipts.
 $path="$native\inspect-state.ps1"
 if((Get-FileHash $path).Hash -ne 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2'){throw 'Historical inspector changed'}
 $ast=[Management.Automation.Language.Parser]::ParseFile($path,[ref]$null,[ref]$null)
 $d=$ast.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type' -and $n.Extent.Text -like '*class RouterReceipts*'},$true)
 $historical="$root\topic-enrollment-01a158ac-b686-7011-b706-8549a7f8e6d2\previous-router.db"
 & ([ScriptBlock]::Create($d.Extent.Text.Replace('RouterReceipts','PreTopicReceipts').Replace("$root\state\router.db",$historical)))
 $rows=[PreTopicReceipts]::Read("SELECT key,value FROM meta WHERE key='startup-held/7dc840b0-402f-451e-bc79-dadfb706d363'")
 if($rows.Length -ne 1 -or [DateTimeOffset](($rows[0][1]|ConvertFrom-Json).at) -ge [DateTimeOffset]$before.at){throw 'Historical startup hold not established'}
 $heldIds+='7dc840b0-402f-451e-bc79-dadfb706d363'
 Save "$release\historical-hold-baseline.json" @{source=$historical;key=$rows[0][0];evidence=($rows[0][1]|ConvertFrom-Json);reconstructedAfterCutover=$true}
}
foreach($id in @($heldIds|Where-Object {$_})){if(@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $id -and $_.held}).Count -ne 1){throw 'Existing native hold changed'}}
if(@($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected -and $_.binding.ThreadId -notin $heldIds}).Count){throw 'Previously healthy Claude route disconnected'}
foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$enabled=if($name -like '*Startup'){$before.startup}else{$before.watchdog};if($enabled){(ExactTask $name).Enabled=$true}}
Save "$release\verified.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');routes=18;daemonPid=479;nativeWorkersPreserved=$true;bindingsPreserved=$true;holdsPreserved=$true;restartFreeCodexCreation=$true;latencyBenchmarkPending=$true}
[IO.File]::ReadAllText("$release\verified.json")
