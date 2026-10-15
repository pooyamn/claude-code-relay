param([Parameter(Mandatory=$true)][ValidateSet('prepare','stage','probe','activate','verify')][string]$Phase,
 [Parameter(Mandatory=$true)][ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$ManifestSha256,
 [Parameter(Mandatory=$true)][ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$CodeSha256)
# Owner-requested Display recovery. No native turn/goal/approval mutation, no
# uncertain upload replay, no replacement session or changes to other bindings.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$OutputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote'
$release="$root\release-daily-output-20261015";$temp='C:\Users\pou\AppData\Local\Temp'
$oldCode='27AF49C2BBB2409BB33DA9D49BE28B123F8480955ED62DE82C91C6A8FDBCC946'
$code=$CodeSha256.ToUpperInvariant();$policyHash='70AB674B2B297489C6C5D78965335B3E5B738E15C7F9FBCAB9D51D1A78D8A205'
$pin='01a11701-137a-76c2-b997-5f5d0a9c96e0';$bubbleKey='bubble/'+$pin;$op='a1271f1d97834aa2a9637031094c2198'
$normal='"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
# Reuse only reviewed helper definitions, not the old deployment's actions.
$helper="$temp\deploy-switch-isolation-20261014.ps1"
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed maintenance helpers changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Unknown','Bindings','HostIdentity','Hex','ExactTask','Fenced')){
 $definition=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true)
 if(-not $definition){throw 'Reviewed helper definition missing'};. ([ScriptBlock]::Create($definition.Extent.Text))
}
LoadSql "$native\inspect-state.ps1" 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
if($Phase -ne 'prepare'){$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()}
function Original{if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $oldCode -or (Get-FileHash "$root\config.json").Hash -ne $policyHash){throw 'Production changed; preserve'}}
if($Phase -eq 'prepare'){
 Original;if(Test-Path $release){throw 'Existing release; inspect, do not repeat'}
 if((Get-FileHash "$temp\router-daily-manifest-20261015.json").Hash -ne $ManifestSha256){throw 'Reviewed manifest required'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 Copy-Item "$temp\router-daily-manifest-20261015.json" "$release\manifest.json"
 if((Get-FileHash "$release\manifest.json").Hash -ne $ManifestSha256){throw 'Copied manifest mismatch'}
 New-Item -ItemType Directory "$release\candidate"|Out-Null;Protect "$release\candidate" $true
 $m=Get-Content "$release\manifest.json" -Raw -Encoding UTF8|ConvertFrom-Json
 foreach($file in $m.PSObject.Properties){
  if($file.Name -notmatch '^[A-Za-z0-9_.-]+$'){throw 'Invalid artifact name'}
  $p=Join-Path "$release\candidate" $file.Name;Copy-Item (Join-Path "$temp\router-daily-output-20261015" $file.Name) $p
  if((Get-FileHash $p).Hash -ne $file.Value){throw 'Sealed artifact mismatch'}
 }
 if((Get-FileHash "$release\candidate\KhadangRouter.dll").Hash -ne $code){throw 'Wrong candidate'}
 $targeted=(& "$release\candidate\KhadangRouter.exe" --self-test-daily-output) -join "`n";if($LASTEXITCODE){throw 'Daily quota/backlog regression failed'}
 $tests=(& "$release\candidate\KhadangRouter.exe" --self-test) -join "`n";if($LASTEXITCODE){throw 'Full sealed Windows regression failed'}
 Save "$release\prepared.json" @{code=$code;targeted=$targeted;tests=$tests;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='prepared';tests=$tests;dailyTests=$targeted;productionChanged=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'stage'){
 Original;if(-not (Test-Path "$release\prepared.json") -or (Test-Path "$release\before.json")){throw 'Fresh tested stage required'}
 $s=Get-Content "$root\state\status.json" -Raw -Encoding UTF8|ConvertFrom-Json
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 17){throw 'Fresh exact live routes/daemon required'}
 Save "$release\before.json" @{host=(HostIdentity);unknown=(Unknown);bindings=(Bindings);startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled;at=[DateTimeOffset]::UtcNow.ToString('o')}
 Copy-Item "$root\state\probe.json" "$release\previous-probe.json"
 foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $name;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
 try{Stop-Service KhadangRouter}catch{};(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 LoadSql "$native\stage-dut-topic.ps1" '0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF' 'PcbaRegistry'
 $lease=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null
 try{
  $db=[PcbaRegistry]::new()
  if($db.Read("SELECT id FROM updates WHERE status IN ('received','dispatching','unknown')").Length -or $db.Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Unsettled intake/effect; preserve'}
  foreach($row in $db.Read("SELECT id,kind FROM operations WHERE status='unknown' AND kind<>'telegram/editMessageText'")){
   if($row[0] -ne $op -or $row[1] -ne 'telegram/sendDocument'){throw 'Unexpected uncertain effect; no recovery'}
  }
  $binding=$db.Read('SELECT payload FROM bindings WHERE chat=-1004393585932 AND topic=2')[0][0]|ConvertFrom-Json
  $original=$db.Read("SELECT value FROM meta WHERE key='$bubbleKey'")[0][0]
  $b=$original|ConvertFrom-Json
  $effect=$db.Read("SELECT payload,status FROM operations WHERE id='$op'")[0]
  $payload=$effect[0]|ConvertFrom-Json
  if($binding.ThreadId -ne $pin -or $binding.Backend -ne 'codex' -or $binding.Runtime -ne 'linux' -or
   $binding.Workspace -cne '/Users/pouya/.openclaw/workspace/futek-ai/display-source-code-recovery' -or $b.chat -ne $binding.Chat -or $b.topic -ne $binding.Topic -or
   -not $b.held -or $b.sendUnknown -or $effect[1] -ne 'unknown' -or $payload.chat_id -ne $binding.Chat -or $payload.message_thread_id -ne $binding.Topic -or
   $payload.sha256 -ne 'ec8992778478575221b4955fb5b242d91712a2c455113e82f63682af3bccf38e' -or $payload.size -ne 20859985 -or
   $db.Read("SELECT key FROM meta WHERE key='owner-output-quarantine/$op'").Length){throw 'Exact owner-requested topic and ambiguous ZIP required'}
  $answers=@($b.finalAnswer)+@($b.pendingAnswers)+@($b.pendingResponses|ForEach-Object finalAnswer)
  if(@($answers|ForEach-Object Parts|Where-Object SendUnknown).Count -or
   @($b.pendingResponses|Where-Object {$_.sendUnknown -and $null -eq $_.message}).Count){throw 'Another uncertain message remains; do not bypass'}
  $files=@($answers|ForEach-Object Files|Where-Object SendUnknown)
  if($files.Count -ne 1 -or $files[0].Message -or $files[0].Sha256 -ne $payload.sha256 -or $files[0].Size -ne $payload.size -or [IO.Path]::GetFileName($files[0].Path) -cne $payload.filename){throw 'Exact one-to-one uncertain upload receipt required'}
  $file=$files[0];$removed=0
  foreach($a in $answers){if($null -ne $a -and @($a.Files|Where-Object {$_.SendUnknown -and $_.Path -ceq $file.Path}).Count){$a.Files=@($a.Files|Where-Object {-not ($_.SendUnknown -and $_.Path -ceq $file.Path)});$removed++}}
  if($removed -ne 1){throw 'Ambiguous archive location; no mutation'}
  $suppressed=0
  foreach($response in @($b.pendingResponses)){
   if($null -eq $response.message -and -not $response.sendUnknown){$response|Add-Member progressSuperseded $true -Force;$suppressed++}
  }
  # Display-only observation reset. The exact native thread is independently
  # reattached/read by the router, never interrupted, restarted or goal-resumed.
  $b.held=$false;$b.busy=$false;$b.turn=$null;$b.status='Ready';$b.tail=''
  $b|Add-Member nativeStatus 'Ready' -Force
  $b|Add-Member outputRateLimited $false -Force
  $candidate=@{binding=$binding;bubble=$b}|ConvertTo-Json -Depth 100 -Compress
  $validated=($candidate|& "$release\candidate\KhadangRouter.exe" --validate-outbox) -join "`n"
  if($LASTEXITCODE){throw 'Actual candidate rejected full recovered outbox'}
  $validation=$validated|ConvertFrom-Json
  if(-not $validation.valid -or $validation.uncertain -or $validation.pendingAnswers -ne @($b.pendingAnswers).Count -or $validation.pendingBubbles -ne @($b.pendingResponses).Count){throw 'Incomplete outbox reconstruction'}
  $null=$db.Read("VACUUM INTO '$release\previous-router.db'")
  Save "$release\original-bubble.json" ($original|ConvertFrom-Json)
  $digest=[BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($effect[0]))).Replace('-','').ToLowerInvariant()
  $quarantine=@{schema='ccrelay.owner_output_quarantine.v1';operation=$op;chat=$binding.Chat;topic=$binding.Topic;workspace=$binding.Workspace;
   payloadSha256=$digest;action='retain-no-resend';file=$file;reason='Owner requested exact topic recovery without replaying ambiguous upload';at=[DateTimeOffset]::UtcNow.ToString('o')}
  Save "$release\quarantined-upload.json" $quarantine
  $db.Read('BEGIN IMMEDIATE')|Out-Null
  try{
   $null=$db.Read("INSERT INTO meta VALUES('owner-output-quarantine/$op',CAST(X'$(Hex $quarantine)' AS TEXT))")
   $null=$db.Read("UPDATE meta SET value=CAST(X'$(Hex $b)' AS TEXT) WHERE key='$bubbleKey'")
   $db.Read('COMMIT')|Out-Null
  }catch{$db.Read('ROLLBACK')|Out-Null;throw}
  Copy-Item "$root\bin" "$release\previous-bin" -Recurse
  Copy-Item "$release\candidate\*" "$root\bin" -Force;Get-ChildItem "$root\bin" -File|ForEach-Object {Protect $_.FullName}
  Save "$release\recovered.json" @{pendingAnswers=$validation.pendingAnswers;pendingBubbles=$validation.pendingBubbles;unsentOldProgressSuperseded=$suppressed;quarantinedUploads=1;inputsReplayed=0}
 }finally{if($db){$db.Dispose()};$lease.Dispose()}
 $before=Get-Content "$release\before.json" -Raw -Encoding UTF8|ConvertFrom-Json
 if((Unknown) -cne $before.unknown -or (Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host){throw 'Unrelated effects/registry/native custody changed'}
 Save "$release\staged.json" @{code=$code;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='staged';backlogPreserved=$true;uncertainUploadReplayed=$false;nativeMutations=0}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'probe'){
 Fenced;$svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --probe-service --config "'+$root+'\config.json"');StartMode='Manual'}
 if($r.ReturnValue){throw 'Probe path failed'};Start-Service KhadangRouter
 $stage=Get-Content "$release\staged.json" -Raw -Encoding UTF8|ConvertFrom-Json;$end=[DateTimeOffset]::UtcNow.AddSeconds(50)
 do{$p=Get-Content "$root\state\probe.json" -Raw -Encoding UTF8|ConvertFrom-Json;if($p.routerSha256 -eq $code -and $p.verified -and [DateTimeOffset]$p.testedAt -gt [DateTimeOffset]$stage.at){break};Start-Sleep -Seconds 1}while([DateTimeOffset]::UtcNow -lt $end)
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 if($p.routerSha256 -ne $code -or $p.policySha256 -ne $policyHash -or -not $p.verified -or -not $p.credentialAndCodeDenied -or -not $p.nativeWindowsSandboxVerified -or -not $p.nativeLinuxCommandOwnerVerified -or $p.modelInference -or $p.telegramPolling -or [DateTimeOffset]$p.testedAt -le [DateTimeOffset]$stage.at){throw 'Fresh exact OS proof required'}
 $old=Get-Content "$release\previous-probe.json" -Raw -Encoding UTF8|ConvertFrom-Json
 if(-not $old.nativeLinuxClaudeContinuityVerified){throw 'Prior native acceptance missing'}
 Save "$release\generic-proof.json" $p
 foreach($field in @('nativeLinuxClaudeLaunchVerified','nativeLinuxClaudeToolOwnerVerified','nativeLinuxClaudeContinuityVerified','nativeLinuxClaudeAcceptance')){if($old.PSObject.Properties[$field]){$p|Add-Member $field $old.$field -Force}}
 $p|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Router-only daily output and exact Display recovery; native host/connectors/policy unchanged';nativeModelTestsRerun=$false} -Force
 Save "$root\state\probe.json" $p;Save "$release\accepted.json" @{code=$code;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='probe-accepted';modelsStarted=$false;telegramPolling=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'activate'){
 Fenced;if(-not (Test-Path "$release\accepted.json") -or (Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code -or (Get-FileHash "$root\config.json").Hash -ne $policyHash){throw 'Exact accepted candidate required'}
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=$normal;StartMode='Manual'}
 if($r.ReturnValue){throw 'Normal service path failed'};Start-Service KhadangRouter
 @{phase='activated';sameNativeThread=$pin;goalChanged=$false}|ConvertTo-Json -Compress;return
}
$s=Get-Content "$root\state\status.json" -Raw -Encoding UTF8|ConvertFrom-Json;$before=Get-Content "$release\before.json" -Raw -Encoding UTF8|ConvertFrom-Json
$unknownExpected=$before.unknown
if(Test-Path "$release\retained-historical-attachments\recovered.json"){
 # The separate exact owner recovery retains a second observed timeout and
 # parks historical files; compare to that recovery's unchanged receipt set.
 $retainedBefore=Get-Content "$release\retained-historical-attachments\before.json" -Raw -Encoding UTF8|ConvertFrom-Json
 if($retainedBefore.bindings -cne $before.bindings -or $retainedBefore.host -cne $before.host -or
  -not [RouterReceipts]::Read("SELECT key FROM meta WHERE key='owner-output-quarantine/d718435264094f869e0240a49334830d'").Length){throw 'Exact historical-attachment recovery missing'}
 $unknownExpected=$retainedBefore.unknown
}
$display=@($s.nativeSessions|Where-Object {$_.binding.Chat -eq -1004393585932 -and $_.binding.Topic -eq 2})
if((Get-Service KhadangRouter).Status -ne 'Running' -or [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or
 $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 17 -or $display.Count -ne 1 -or $display[0].binding.ThreadId -ne $pin -or $display[0].held -or
 (Unknown) -cne $unknownExpected -or (Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host -or
 [RouterReceipts]::Read("SELECT key FROM meta WHERE key='startup-held/$pin'").Length){throw 'Fresh exact recovered topic/unchanged native custody not confirmed'}
$b=[RouterReceipts]::Read("SELECT value FROM meta WHERE key='$bubbleKey'")[0][0]|ConvertFrom-Json
$budgets=@([RouterReceipts]::Read("SELECT key,value FROM meta WHERE key LIKE 'telegram/daily-output/-1004393585932/2/%'")|ForEach-Object {$_[1]|ConvertFrom-Json})
if(-not $budgets.Count -or @($budgets|Where-Object {$_.Seeded+@($_.Reserved).Count -gt 100}).Count){throw 'Durable daily budget missing/exceeded'}
foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$enabled=if($name -like '*Startup'){$before.startup}else{$before.watchdog};if($enabled){(ExactTask $name).Enabled=$true}}
Save "$release\verified.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');sameNativeThread=$pin;dailyLimit=100;resetZone='America/Los_Angeles';pendingAnswers=@($b.pendingAnswers).Count;
 currentBubble=$b.message;originalUploadStillUnknown=$true;noInputReplay=$true;nativeHostAndCodexPreserved=$true;startupAndWatchdogRestored=$true}
[IO.File]::ReadAllText("$release\verified.json")
