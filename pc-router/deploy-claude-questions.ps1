param([Parameter(Mandatory=$true)][ValidateSet('prepare','stage','probe','activate','verify')][string]$Phase)
# Router-only owner-question notification repair. Preserve native workers,
# pending approvals, unknown operations, bindings, goals and protected policy.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$OutputEncoding=[Text.UTF8Encoding]::new($false);[Console]::InputEncoding=[Text.UTF8Encoding]::new($false);[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$root='C:\ProgramData\KhadangRouter';$release="$root\release-claude-questions-20261018";$temp='C:\Users\pou\AppData\Local\Temp'
$old='20890485D499759E6BE4E0120F761EB87DA34C4CC0166C64D65C3BE183159EC6'
$code='E26113C81DAA2D843815EE118C916517188DEE9E9D09E601E59A86BED1B93469'
$manifest='0C77EC1C1BD443307B8A235A737DC2783B7BC2938EC9825E10BAA973E08357B6'
$policy='70AB674B2B297489C6C5D78965335B3E5B738E15C7F9FBCAB9D51D1A78D8A205'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$helper="$temp\deploy-switch-isolation-20261014.ps1"
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helpers changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Unknown','Bindings','HostIdentity','ExactTask','Fenced')){
 $d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true)
 if(-not $d){throw 'Missing reviewed helper'};. ([ScriptBlock]::Create($d.Extent.Text))
}
LoadSql 'C:\ProgramData\OracovaNativeRemote\inspect-state.ps1' 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
function Original{if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $old -or (Get-FileHash "$root\config.json").Hash -ne $policy){throw 'Live release changed; preserve'}}
if($Phase -ne 'prepare'){$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()}
if($Phase -eq 'prepare'){
 Original;if(Test-Path $release){throw 'Existing release; inspect instead of repeating'}
 if((Get-FileHash "$temp\router-questions-manifest-20261018-final.json").Hash -ne $manifest){throw 'Exact reviewed manifest required'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 Copy-Item "$temp\router-questions-manifest-20261018-final.json" "$release\manifest.json"
 New-Item -ItemType Directory "$release\candidate"|Out-Null;Protect "$release\candidate" $true
 $m=Get-Content "$release\manifest.json" -Raw -Encoding UTF8|ConvertFrom-Json
 foreach($f in $m.PSObject.Properties){
  if($f.Name -notmatch '^[A-Za-z0-9_.-]+$'){throw 'Invalid artifact name'}
  $p=Join-Path "$release\candidate" $f.Name;Copy-Item (Join-Path "$temp\router-questions-20261018-final" $f.Name) $p
  if((Get-FileHash $p).Hash -ne $f.Value){throw 'Sealed artifact mismatch'}
 }
 if((Get-FileHash "$release\candidate\KhadangRouter.dll").Hash -ne $code){throw 'Wrong reviewed code'}
 $targeted=(& "$release\candidate\KhadangRouter.exe" --self-test-claude-questions) -join "`n";if($LASTEXITCODE){throw 'Question regression failed'}
 $tests=(& "$release\candidate\KhadangRouter.exe" --self-test) -join "`n";if($LASTEXITCODE){throw 'Full Windows regression failed'}
 Save "$release\prepared.json" @{code=$code;targeted=$targeted;tests=$tests;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='prepared';targeted=$targeted;tests=$tests;productionChanged=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'stage'){
 Original;if(-not (Test-Path "$release\prepared.json") -or (Test-Path "$release\before.json")){throw 'Fresh tested stage required'}
 $s=Get-Content "$root\state\status.json" -Raw -Encoding UTF8|ConvertFrom-Json
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 17){throw 'Fresh exact native custody required'}
 Save "$release\before.json" @{host=(HostIdentity);unknown=(Unknown);bindings=(Bindings);startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled;at=[DateTimeOffset]::UtcNow.ToString('o')}
 Copy-Item "$root\state\probe.json" "$release\previous-probe.json"
 foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $name;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 if([RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('dispatching','unknown')").Length -or
  [RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Unsettled effects; preserve'}
 Copy-Item "$root\bin" "$release\previous-bin" -Recurse
 Copy-Item "$release\candidate\*" "$root\bin" -Force;Get-ChildItem "$root\bin" -File|ForEach-Object {Protect $_.FullName}
 Save "$release\staged.json" @{code=$code;nativeWorkersStopped=0;ledgerRowsRewritten=0;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='staged';nativeWorkersStopped=0;nativeInputReplayed=0}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'probe'){
 Fenced;$svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --probe-service --config "'+$root+'\config.json"');StartMode='Manual'}
 if($r.ReturnValue){throw 'Probe path failed'};Start-Service KhadangRouter
 $stage=Get-Content "$release\staged.json" -Raw -Encoding UTF8|ConvertFrom-Json;$end=[DateTimeOffset]::UtcNow.AddSeconds(50)
 do{$p=Get-Content "$root\state\probe.json" -Raw -Encoding UTF8|ConvertFrom-Json;if($p.routerSha256 -eq $code -and $p.verified -and [DateTimeOffset]$p.testedAt -gt [DateTimeOffset]$stage.at){break};Start-Sleep -Seconds 1}while([DateTimeOffset]::UtcNow -lt $end)
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 if($p.routerSha256 -ne $code -or $p.policySha256 -ne $policy -or -not $p.verified -or -not $p.credentialAndCodeDenied -or -not $p.nativeWindowsSandboxVerified -or -not $p.nativeLinuxCommandOwnerVerified -or $p.modelInference -or $p.telegramPolling -or [DateTimeOffset]$p.testedAt -le [DateTimeOffset]$stage.at){throw 'Fresh exact OS proof required'}
 $oldProof=Get-Content "$release\previous-probe.json" -Raw -Encoding UTF8|ConvertFrom-Json
 if(-not $oldProof.nativeLinuxClaudeContinuityVerified){throw 'Prior native acceptance missing'}
 Save "$release\generic-proof.json" $p
 foreach($field in @('nativeLinuxClaudeLaunchVerified','nativeLinuxClaudeToolOwnerVerified','nativeLinuxClaudeContinuityVerified','nativeLinuxClaudeAcceptance')){if($oldProof.PSObject.Properties[$field]){$p|Add-Member $field $oldProof.$field -Force}}
 $p|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Router-only owner-question presentation; independent host/connectors/policy unchanged';nativeModelTestsRerun=$false} -Force
 Save "$root\state\probe.json" $p;Save "$release\accepted.json" @{code=$code;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='probe-accepted';modelsStarted=$false;telegramPolling=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'activate'){
 Fenced;if(-not (Test-Path "$release\accepted.json") -or (Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code -or (Get-FileHash "$root\config.json").Hash -ne $policy){throw 'Exact accepted release required'}
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"');StartMode='Manual'}
 if($r.ReturnValue){throw 'Normal service path failed'};Start-Service KhadangRouter
 @{phase='activated';pendingNativeRequestsRestored=$true;noAutomaticAnswers=$true}|ConvertTo-Json -Compress;return
}
$s=Get-Content "$root\state\status.json" -Raw -Encoding UTF8|ConvertFrom-Json;$before=Get-Content "$release\before.json" -Raw -Encoding UTF8|ConvertFrom-Json
$ai=@($s.nativeSessions|Where-Object {$_.binding.Chat -eq -1003550185469 -and $_.binding.Topic -eq 1876})
if((Get-Service KhadangRouter).Status -ne 'Running' -or [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or
 $s.nativeLinuxPid -ne 479 -or @($s.bindings).Count -ne 17 -or $ai.Count -ne 1 -or $ai[0].held -or -not $ai[0].claudeConnected -or
 (Unknown) -cne $before.unknown -or (Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host){throw 'Fresh exact live/native custody verification failed'}
$notices=@([RouterReceipts]::Read("SELECT value FROM meta WHERE key LIKE 'claude/owner-question/2c0bce31-f586-4d5e-9422-4be550763ed8/%'")|ForEach-Object {$_[0]|ConvertFrom-Json})
foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$enabled=if($name -like '*Startup'){$before.startup}else{$before.watchdog};if($enabled){(ExactTask $name).Enabled=$true}}
Save "$release\verified.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');routes=17;daemonPid=479;aiHilHeld=$ai[0].held;aiHilStatus=$ai[0].status;
 confirmedQuestionMessages=@($notices|Where-Object {$null -ne $_.Message}|ForEach-Object Message);startupAndWatchdogRestored=$true;nativeWorkersPreserved=$true;nativeInputReplayed=0}
[IO.File]::ReadAllText("$release\verified.json")
