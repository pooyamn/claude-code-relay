param([Parameter(Mandatory=$true)][ValidateSet('prepare','stage','probe','activate','verify')][string]$Phase)
# One exact connector repair. No native input/approval replay, transcript edits,
# registry writes, host restart, session replacement, or uncertain receipt edits.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote'
$release="$root\release-dut-queue-20261020";$temp='C:\Users\pou\AppData\Local\Temp'
$pin='7dc840b0-402f-451e-bc79-dadfb706d363'
$code='A0D694DA58801A58F5EEBE1B31BC582707445D58060D4A3EC640EC9759055B33'
$oldPolicy='035A754BC5FCC4A53B7AB3463586A746EC5DE609997F83AC0340AEC8CAB16E75'
$connector='87F8E30C4DF08C5CFADAAA6F6D4A62DCD72281F3659D61DEB28B9A6AF2F9644C'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$helper="$temp\deploy-switch-isolation-20261014.ps1"
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helper changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Unknown','Bindings','HostIdentity','ExactTask','Fenced')){
 $d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true)
 if(-not $d){throw 'Helper missing'};. ([ScriptBlock]::Create($d.Extent.Text))
}
LoadSql "$native\inspect-state.ps1" 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
function Original{if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code -or (Get-FileHash "$root\config.json").Hash -ne $oldPolicy){throw 'Production changed; preserve'}}
function Status{[IO.File]::ReadAllText("$root\state\status.json")|ConvertFrom-Json}
if($Phase -eq 'prepare'){
 Original;if(Test-Path $release){throw 'Existing release; reconcile'}
 if((Get-FileHash "$temp\pc_claude_stdio-dut-queue-20261020.py").Hash -ne $connector){throw 'Reviewed connector changed'}
 $tests=(& "$root\bin\KhadangRouter.exe" --self-test)-join "`n";if($LASTEXITCODE){throw 'Windows regressions failed'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 $p=[IO.File]::ReadAllText("$root\config.json")|ConvertFrom-Json
 $previous=$p.LinuxClaude.PackageRoot;$next="$native\claude-connector-"+[Guid]::NewGuid().ToString('N')
 New-Item -ItemType Directory $next|Out-Null;Set-Acl $next (Get-Acl $previous)
 foreach($f in $p.LinuxClaude.FileSha256.PSObject.Properties){
  $from=Join-Path $previous $f.Name;$to=Join-Path $next $f.Name
  if((Get-FileHash $from).Hash -ne $f.Value){throw 'Prior connector changed'}
  $parent=Split-Path $to;if(-not (Test-Path $parent)){New-Item -ItemType Directory $parent|Out-Null;Set-Acl $parent (Get-Acl (Split-Path $from))}
  if($f.Name -eq 'pc_claude_stdio.py'){Copy-Item "$temp\pc_claude_stdio-dut-queue-20261020.py" $to}else{Copy-Item $from $to}
  Set-Acl $to (Get-Acl $from)
 }
 foreach($f in Get-ChildItem $previous -Filter 'handoff-*.json' -File){
  if($f.Name -notmatch '^handoff-[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\.json$'){throw 'Invalid checkpoint name'}
  $to=Join-Path $next $f.Name;Copy-Item $f.FullName $to;Set-Acl $to (Get-Acl $f.FullName)
  if((Get-FileHash $to).Hash -ne (Get-FileHash $f.FullName).Hash){throw 'Checkpoint copy differs'}
 }
 $p.LinuxClaude.PackageRoot=$next;$p.LinuxClaude.FileSha256.'pc_claude_stdio.py'=$connector
 Save "$release\next-policy.json" $p
 Save "$release\prepared.json" @{code=$code;policy=(Get-FileHash "$release\next-policy.json").Hash;connector=$next;tests=$tests;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='prepared';tests=$tests;productionChanged=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'stage'){
 Original;if(-not (Test-Path "$release\prepared.json") -or (Test-Path "$release\before.json")){throw 'Fresh prepared stage required'}
 $s=Status;$target=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $pin})
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 18 -or $target.Count -ne 1 -or -not $target[0].held -or $target[0].claudeConnected -or
  @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and ($_.busy -or ($_.binding.ThreadId -ne $pin -and -not $_.claudeConnected))}).Count){throw 'Fresh exact idle native custody required'}
 $b=[RouterReceipts]::Read("SELECT value FROM meta WHERE key='bubble/$pin'")[0][0]|ConvertFrom-Json
 if($b.busy -or $b.held -or $b.sendUnknown -or $b.claudeState -ne 'idle' -or @($b.pendingResponses).Count -or @($b.pendingAnswers).Count){throw 'Exact idle DUT outbox required'}
 $held=[RouterReceipts]::Read("SELECT key,value FROM meta WHERE key LIKE 'bubble/%' AND json_extract(value,'$.held')=1")
 Save "$release\before.json" @{host=(HostIdentity);unknown=(Unknown);bindings=(Bindings);held=$held;nativeHeld=@($s.nativeSessions|Where-Object held|ForEach-Object {$_.binding.ThreadId});startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled;at=[DateTimeOffset]::UtcNow.ToString('o')}
 Copy-Item "$root\config.json" "$release\previous-config.json";Copy-Item "$root\state\probe.json" "$release\previous-probe.json"
 foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $name;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 if([RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('dispatching','unknown')").Length -or [RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Unsettled native effects; preserve'}
 Copy-Item "$release\next-policy.json" "$root\config.json" -Force;Protect "$root\config.json"
 Save "$release\staged.json" @{code=$code;policy=(Get-FileHash "$root\config.json").Hash;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='staged';nativeHostsRestarted=0;messagesReplayed=0}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'probe'){
 Fenced;$svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --probe-service --config "'+$root+'\config.json"');StartMode='Manual'}
 if($r.ReturnValue){throw 'Probe path failed'};Start-Service KhadangRouter
 $stage=[IO.File]::ReadAllText("$release\staged.json")|ConvertFrom-Json;$end=[DateTimeOffset]::UtcNow.AddSeconds(55)
 do{$p=[IO.File]::ReadAllText("$root\state\probe.json")|ConvertFrom-Json;if($p.routerSha256 -eq $code -and $p.policySha256 -eq $stage.policy -and $p.verified -and [DateTimeOffset]$p.testedAt -gt [DateTimeOffset]$stage.at){break};Start-Sleep -Milliseconds 500}while([DateTimeOffset]::UtcNow -lt $end)
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 if($p.routerSha256 -ne $code -or $p.policySha256 -ne $stage.policy -or -not $p.verified -or -not $p.credentialAndCodeDenied -or -not $p.nativeWindowsSandboxVerified -or -not $p.nativeLinuxCommandOwnerVerified -or $p.modelInference -or $p.telegramPolling -or [DateTimeOffset]$p.testedAt -le [DateTimeOffset]$stage.at){throw 'Fresh actual SYSTEM proof required'}
 Save "$release\generic-proof.json" $p
 $old=[IO.File]::ReadAllText("$release\previous-probe.json")|ConvertFrom-Json
 if(-not $old.nativeLinuxClaudeContinuityVerified){throw 'Prior native continuity missing'}
 foreach($field in @('nativeLinuxClaudeLaunchVerified','nativeLinuxClaudeToolOwnerVerified','nativeLinuxClaudeContinuityVerified','nativeLinuxClaudeAcceptance')){if($old.PSObject.Properties[$field]){$p|Add-Member $field $old.$field -Force}}
 $p|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Known absorbed-mid-turn queue record only; native executable/launch/input unchanged. Exact DUT recovery still requires live attestation.';connectorSha256=$connector;nativeModelTestsRerun=$false} -Force
 Save "$root\state\probe.json" $p;Save "$release\accepted.json" @{code=$code;policy=$stage.policy;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='probe-accepted';modelsStarted=$false;telegramPolling=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'activate'){
 Fenced;$accepted=[IO.File]::ReadAllText("$release\accepted.json")|ConvertFrom-Json
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code -or (Get-FileHash "$root\config.json").Hash -ne $accepted.policy){throw 'Accepted artifacts changed'}
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"');StartMode='Manual'}
 if($r.ReturnValue){throw 'Normal service path failed'};Start-Service KhadangRouter
 @{phase='activated';nativeHostsRestarted=0;messagesReplayed=0}|ConvertTo-Json -Compress;return
}
$s=Status;$before=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json;$accepted=[IO.File]::ReadAllText("$release\accepted.json")|ConvertFrom-Json
$target=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $pin})
if((Get-Service KhadangRouter).Status -ne 'Running' -or [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or [DateTimeOffset]$s.at -le [DateTimeOffset]$accepted.at -or
 $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 18 -or (Unknown) -cne $before.unknown -or (Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host -or
 $target.Count -ne 1 -or $target[0].held -or -not $target[0].claudeConnected -or $target[0].busy -or $target[0].pid -le 0 -or
 @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Fresh exact live DUT recovery not confirmed'}
foreach($row in $before.held){$now=[RouterReceipts]::Read("SELECT value FROM meta WHERE key='$($row[0])'");if($now.Length -ne 1 -or -not ($now[0][0]|ConvertFrom-Json).held){throw 'Unrelated hold changed'}}
$recovery=[RouterReceipts]::Read("SELECT value FROM meta WHERE key='claude/recovery/$pin'")[0][0]|ConvertFrom-Json
if($recovery.state -ne 'connected' -or $recovery.binding.ThreadId -ne $pin -or [DateTimeOffset]$recovery.at -le [DateTimeOffset]$accepted.at -or [RouterReceipts]::Read("SELECT key FROM meta WHERE key='startup-held/$pin'").Length){throw 'Fresh exact recovery receipt required'}
foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$enabled=if($name -like '*Startup'){$before.startup}else{$before.watchdog};(ExactTask $name).Enabled=[bool]$enabled}
Save "$release\verified.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');routes=18;session=$pin;connected=$true;nativePid=$target[0].pid;messagesReplayed=0;nativeHostPreserved=$true;otherHoldsPreserved=$true;startupRestored=$true;phoneRoundTripVerified=$false}
[IO.File]::ReadAllText("$release\verified.json")
