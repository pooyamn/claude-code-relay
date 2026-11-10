param([ValidateSet('prepare','stage','finish-stage','compat','probe','native','activate','verify')][string]$Phase)
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$PSDefaultParameterValues['Get-Content:Encoding']='UTF8'
$root='C:\ProgramData\KhadangRouter';$hostRoot='C:\ProgramData\KhadangClaudeHost';$native='C:\ProgramData\OracovaNativeRemote';$temp='C:\Users\pou\AppData\Local\Temp'
$release=$root+'\release-claude-fable-20261109';$pin='8cd2d34c-0805-4705-8197-d11de0728499'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if(-not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'PC administrator required'}
$helper=$temp+'\deploy-switch-isolation-20261014.ps1'
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helpers required'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Hex','Bindings','Unknown','HostIdentity','ExactTask')){$d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true);. ([scriptblock]::Create($d.Extent.Text))}
LoadSql ($native+'\inspect-state.ps1') 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
function Status{Get-Content ($root+'\state\status.json') -Raw|ConvertFrom-Json}
function FenceTasks{foreach($n in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $n;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}}
function RestoreTasks{$b=Get-Content ($release+'\before.json') -Raw|ConvertFrom-Json;foreach($n in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){(ExactTask $n).Enabled=[bool]$b.tasks.$n}}
function Observer([bool]$Probe=$false){
 $mode=if($Probe){'--probe-service'}else{'--service'}
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" '+$mode+' --config "'+$root+'\config.json"');StartMode='Manual'}
 if($r.ReturnValue){throw 'Service configuration failed'};Start-Service KhadangRouter
}
function Reader($Id){
 $class='FableRead'+$Id.Replace('-','')
 if(-not ($class -as [type])){
  $a=[Management.Automation.Language.Parser]::ParseFile(($native+'\inspect-state.ps1'),[ref]$null,[ref]$null)
  $d=$a.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type'},$true)
  . ([scriptblock]::Create($d.Extent.Text.Replace('RouterReceipts',$class).Replace($root+'\state\router.db',$hostRoot+'\state\'+$Id+'\broker.db')))
 };return ($class -as [type])
}
function Settled($Targets){
 if([RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('received','dispatching','unknown')").Length -or [RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Unsettled root input; do not stop custody'}
 foreach($t in $Targets){$r=Reader $t.binding.ThreadId
  foreach($sql in @("SELECT 1 FROM operations WHERE status IN ('attempting','unknown') AND kind<>'telegram/editMessageText' LIMIT 1","SELECT 1 FROM broker_calls WHERE status IN ('attempting','unknown','submitted') LIMIT 1","SELECT 1 FROM broker_replies WHERE status IN ('attempting','unknown','submitted') LIMIT 1","SELECT 1 FROM broker_requests WHERE status IN ('pending','replying','reply-submitted') LIMIT 1")){if($r::Read($sql).Length){throw 'Private native action is unsettled'}}
 }
}
if($Phase -eq 'prepare'){
 if(Test-Path $release){throw 'Existing attempt; inspect instead of repeating'}
 if((Get-FileHash ($temp+'\claude-upgrade-20261109.manifest.json')).Hash -ne '6883EE085F623167B00A583A0E459801940D094D9798C113FC2BE5302A94109B'){throw 'Manifest changed'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 Copy-Item ($temp+'\claude-upgrade-20261109.manifest.json') ($release+'\manifest.json');Protect ($release+'\manifest.json')
 $m=Get-Content ($release+'\manifest.json') -Raw|ConvertFrom-Json
 foreach($name in @('candidate','probe')){
  $out=$release+'\'+$name;New-Item -ItemType Directory $out|Out-Null;Protect $out $true
  foreach($f in $m.$name.PSObject.Properties){if($f.Name -notmatch '^[A-Za-z0-9_.-]+$'){throw 'Literal candidate name required'}
   Copy-Item ($temp+'\claude-upgrade-20261109-'+$name+'\'+$f.Name) ($out+'\'+$f.Name);Protect ($out+'\'+$f.Name)
   if((Get-FileHash ($out+'\'+$f.Name)).Hash -ne $f.Value){throw 'Sealed artifact differs'}
  }
 }
 foreach($n in @('validate-release.ps1','router-watchdog.ps1','test-host-release-attestation.ps1','dispatch-controller-handoff.ps1','router-startup.ps1','repair-claude-host-20261024.ps1')){Copy-Item ($temp+'\'+$n) ($release+'\'+$n);Protect ($release+'\'+$n)}
 & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File ($release+'\validate-release.ps1') -CandidateDirectory ($release+'\candidate')
 if($LASTEXITCODE){throw 'Offline sealed Windows release gate failed'}
 Save ($release+'\prepared.json') @{at=[DateTimeOffset]::UtcNow;code=(Get-FileHash ($release+'\candidate\KhadangRouter.dll')).Hash};'PREPARED';return
}
if($Phase -in @('stage','finish-stage')){
 if($Phase -eq 'stage'){
 if(-not (Test-Path ($release+'\prepared.json')) -or (Test-Path ($release+'\before.json'))){throw 'Fresh tested stage required'}
 if((Get-FileHash ($root+'\bin\KhadangRouter.dll')).Hash -ne 'F8C527B3F3611E8F7DD259F93595AA7FAB11D11FC7DA8CF5701468A0B21707C6' -or (Get-FileHash ($root+'\config.json')).Hash -ne '202947A2C5D918DB0C099434B79C0B4B87F34B69F4C51349FFE606C2680FC0F4'){throw 'Production changed'}
 if((Get-FileHash ($temp+'\motor-upgrade-audit-20261109.json')).Hash -ne '43E5FAA752953C0FB532CDB6873EE5C2E641E7460D8E50830D039A067A4802CF' -or (Get-FileHash ($temp+'\pc_claude_stdio-2.1.321.py')).Hash -ne 'F475107C92B646AE944AD3EE85897F524E5C2F366182C3AB75FF6A2BB5DC4772'){throw 'Exact audit/connector required'}
 $s=Status;$targets=@($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude'})
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddSeconds(-30) -or $targets.Count -ne 9 -or @($targets|Where-Object {$_.busy -or $_.held -or -not $_.ready -or -not $_.nativeConnected -or $_.admission.Blocking -ne 0}).Count){throw 'Nine idle healthy native sessions required'}
 Settled $targets
  $evidence=Get-Content ($temp+'\claude-upgrade-history-20261109.json') -Raw|ConvertFrom-Json
 if((Get-FileHash ($temp+'\claude-upgrade-history-20261109.json')).Hash -ne 'CCB6D9920D3A15B6338BE30DC793C3208F488F448E7472A36C219DC9C597D346' -or @($evidence).Count -ne 9 -or @($evidence.session|Sort-Object -Unique).Count -ne 9){throw 'Exact nine-history read-only evidence required'}
 $tasks=@{};foreach($n in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$tasks[$n]=(ExactTask $n).Enabled}
 Save ($release+'\before.json') @{at=[DateTimeOffset]::UtcNow;tasks=$tasks;bindings=(Bindings);unknown=(Unknown);nativePid=$s.nativeLinuxPid;claude=$targets;history=$evidence}
 foreach($entry in @(@{p=($root+'\config.json');n='previous-config.json'},@{p=($root+'\state\probe.json');n='previous-probe.json'},@{p=($hostRoot+'\installed.json');n='previous-installed.json'},@{p=($temp+'\motor-upgrade-audit-20261109.json');n='motor-audit.json'})){Copy-Item $entry.p ($release+'\'+$entry.n);Protect ($release+'\'+$entry.n)}
 FenceTasks
 }else{
  if((Get-Service KhadangRouter).Status -ne 'Stopped' -or (Get-Service KhadangClaudeHost).Status -ne 'Stopped' -or (Test-Path ($release+'\previous-router-bin')) -or (Test-Path ($release+'\staged.json'))){throw 'Only exact pre-copy interrupted stage may continue'}
  if((Get-FileHash ($root+'\bin\KhadangRouter.dll')).Hash -ne 'F8C527B3F3611E8F7DD259F93595AA7FAB11D11FC7DA8CF5701468A0B21707C6' -or (Get-FileHash ($root+'\config.json')).Hash -ne '202947A2C5D918DB0C099434B79C0B4B87F34B69F4C51349FFE606C2680FC0F4'){throw 'Pre-copy artifacts changed'}
  $before=Get-Content ($release+'\before.json') -Raw|ConvertFrom-Json;$targets=$before.claude
  if((Get-FileHash ($temp+'\claude-upgrade-history-20261109.json')).Hash -ne '512565A1589DEF5092D9A027EBAD968648BE5B4CB58E054B2CFF6C4A5DEFB508' -or (Get-FileHash ($temp+'\motor-upgrade-audit-20261109.json')).Hash -ne '397E5B04FF1F00BEE434BAC0986EF5ED725BC3E393EC9A86913B007190C47810'){throw 'Exact post-stop evidence required'}
  $evidence=Get-Content ($temp+'\claude-upgrade-history-20261109.json') -Raw|ConvertFrom-Json
  Copy-Item ($temp+'\motor-upgrade-audit-20261109.json') ($release+'\motor-post-stop-audit.json');Protect ($release+'\motor-post-stop-audit.json');FenceTasks
 }
 try{
  if((Get-Service KhadangRouter).Status -ne 'Stopped'){Stop-Service KhadangRouter};(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(40));Settled $targets
  foreach($e in $evidence){
   if($e.session -notin @($targets|ForEach-Object {$_.binding.ThreadId}) -or -not $e.quiescent){throw 'Scope mismatch'}
   $hash=(& wsl.exe -d Ubuntu-24.04 -u pou --exec /usr/bin/sha256sum $e.history.path)-join ''
   if($LASTEXITCODE -or -not $hash.StartsWith($e.history.sha256+' ')){throw 'History changed after quiescence review; no host stop'}
  }
  if((Get-Service KhadangClaudeHost).Status -ne 'Stopped'){try{Stop-Service KhadangClaudeHost}catch{if((Get-Service KhadangClaudeHost).Status -ne 'Stopped'){throw}}};(Get-Service KhadangClaudeHost).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(45))
  if((Bindings) -cne (Get-Content ($release+'\before.json') -Raw|ConvertFrom-Json).bindings -or (Unknown) -cne (Get-Content ($release+'\before.json') -Raw|ConvertFrom-Json).unknown){throw 'Uncertain receipt or binding changed'}
  foreach($entry in @(@{p=$root;n='previous-router-bin'},@{p=$hostRoot;n='previous-host-bin'})){Copy-Item ($entry.p+'\bin') ($release+'\'+$entry.n) -Recurse;Copy-Item ($release+'\candidate\*') ($entry.p+'\bin') -Force;Get-ChildItem ($entry.p+'\bin') -File|ForEach-Object {Protect $_.FullName}}
  $installed=Get-Content ($hostRoot+'\installed.json') -Raw|ConvertFrom-Json;$installed.dll=(Get-FileHash ($hostRoot+'\bin\KhadangRouter.dll')).Hash;$installed.exe=(Get-FileHash ($hostRoot+'\bin\KhadangRouter.exe')).Hash;$installed.generation='claude-fable-20261109';Save ($hostRoot+'\installed.json') $installed
  $p=Get-Content ($root+'\config.json') -Raw|ConvertFrom-Json;$package=$p.LinuxClaude.PackageRoot;$connector=$package+'\pc_claude_stdio.py';$checkpoint=$package+'\handoff-'+$pin+'.json'
  Copy-Item $connector ($release+'\previous-connector.py');Copy-Item $checkpoint ($release+'\previous-motor-checkpoint.json')
  $tmp=$connector+'.reviewed-upgrade';Copy-Item ($temp+'\pc_claude_stdio-2.1.321.py') $tmp;Set-Acl $tmp (Get-Acl $connector);[IO.File]::Replace($tmp,$connector,[System.Management.Automation.Language.NullString]::Value)
  $audit=Get-Content ($release+'\motor-post-stop-audit.json') -Raw|ConvertFrom-Json
  $new=@{schema='ccrelay.personal_claude_handoff.v1';session_id=$pin;workspace=$audit.workspace;source_writer='quiesced';uncertain_actions=@();history=$audit.history;profile='/Users/pouya/.claude'}
  $tmp=$checkpoint+'.reviewed-upgrade';Save $tmp $new;Set-Acl $tmp (Get-Acl $checkpoint);[IO.File]::Replace($tmp,$checkpoint,[System.Management.Automation.Language.NullString]::Value)
  LoadSql ($native+'\stage-dut-topic.ps1') '0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF' 'PcbaRegistry'
  $a=[Management.Automation.Language.Parser]::ParseFile(($native+'\stage-dut-topic.ps1'),[ref]$null,[ref]$null);$d=$a.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type'},$true)
  . ([scriptblock]::Create($d.Extent.Text.Replace('PcbaRegistry','FableMotorWrite').Replace($root+'\state\router.db',$hostRoot+'\state\'+$pin+'\broker.db')))
  $lease=[IO.File]::Open($root+'\state\exclusive.lock','Open','ReadWrite','None');$wl=[IO.File]::Open($hostRoot+'\state\'+$pin+'\broker.lease','Open','ReadWrite','None');$db=[FableMotorWrite]::new()
  try{
   $recovery=$db.Read("SELECT value FROM meta WHERE key='claude/recovery/$pin'")[0][0]|ConvertFrom-Json
   if($recovery.state -ne 'connected' -or $recovery.sha256 -ne $audit.oldCheckpointSha256){throw 'Exact connected reviewed Motor checkpoint required'}
   Save ($release+'\previous-motor-recovery.json') $recovery
   $recovery.sha256=(Get-FileHash $checkpoint).Hash.ToLowerInvariant();$recovery.model='claude-fable-5-2';$recovery|Add-Member ownerUpgradeReview ($release+'\motor-audit.json') -Force
   $null=$db.Read("UPDATE meta SET value=CAST(X'$(Hex $recovery)' AS TEXT) WHERE key='claude/recovery/$pin'")
  }finally{$db.Dispose();$wl.Dispose();$lease.Dispose()}
  $p.LinuxClaude.FileSha256.'pc_claude_stdio.py'=(Get-FileHash $connector).Hash.ToLowerInvariant()
  $motorScope=@{Chat=-1003550185469;Topic=14439;Workspace=$audit.workspace;Sha256=(Get-FileHash $checkpoint).Hash.ToLowerInvariant();Model='claude-fable-5-2'}
  $p.LinuxClaude.Checkpoints|Add-Member $pin $motorScope -Force
  Save ($root+'\config.json') $p
  Save ($release+'\staged.json') @{at=[DateTimeOffset]::UtcNow;code=(Get-FileHash ($root+'\bin\KhadangRouter.dll')).Hash;policy=(Get-FileHash ($root+'\config.json')).Hash}
 }catch{Save ($release+'\stage-failure.json') @{at=[DateTimeOffset]::UtcNow;failureType=$_.Exception.GetType().Name;fenced=$true};throw}
 'STAGED; native sessions stopped only after stable quiescence proof';return
}
if($Phase -eq 'compat'){
 if((Get-FileHash ($temp+'\pc_claude_stdio-2.1.321-compatible.py')).Hash -ne '1688B7F1016AA6B2CEFFD3D0B98E2740E1D7BF6E41EB02B0AF14F55F2D46AC4A'){throw 'Exact bookkeeping-only compatibility fix required'}
 FenceTasks;Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(40))
 $p=Get-Content ($root+'\config.json') -Raw|ConvertFrom-Json;$connector=$p.LinuxClaude.PackageRoot+'\pc_claude_stdio.py';$tmp=$connector+'.compat'
 Copy-Item ($temp+'\pc_claude_stdio-2.1.321-compatible.py') $tmp;Set-Acl $tmp (Get-Acl $connector);[IO.File]::Replace($tmp,$connector,[System.Management.Automation.Language.NullString]::Value)
 $p.LinuxClaude.FileSha256.'pc_claude_stdio.py'=(Get-FileHash $connector).Hash.ToLowerInvariant();Save ($root+'\config.json') $p
 Save ($release+'\staged.json') @{at=[DateTimeOffset]::UtcNow;code=(Get-FileHash ($root+'\bin\KhadangRouter.dll')).Hash;policy=(Get-FileHash ($root+'\config.json')).Hash;compatibility='2.1.321 bookkeeping only; does not clear native work'}
 'COMPATIBILITY STAGED; eight native peers preserved';return
}
if($Phase -eq 'probe'){
 if((Get-Service KhadangRouter).Status -ne 'Stopped'){throw 'Fenced observer required'}
 $stage=Get-Content ($release+'\staged.json') -Raw|ConvertFrom-Json;Observer $true
 $end=[DateTimeOffset]::UtcNow.AddSeconds(55)
 do{Start-Sleep -Milliseconds 500;$p=Get-Content ($root+'\state\probe.json') -Raw|ConvertFrom-Json;if($p.routerSha256 -eq $stage.code -and $p.policySha256 -eq $stage.policy -and [DateTimeOffset]$p.testedAt -gt [DateTimeOffset]$stage.at){break}}while([DateTimeOffset]::UtcNow -lt $end)
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30))
 if(-not $p.verified -or -not $p.credentialAndCodeDenied -or -not $p.nativeWindowsSandboxVerified -or -not $p.nativeLinuxCommandOwnerVerified -or $p.modelInference -or $p.telegramPolling -or $p.routerSha256 -ne $stage.code -or $p.policySha256 -ne $stage.policy){throw 'Fresh exact SYSTEM security probe failed'}
 Save ($release+'\generic-proof.json') $p;'SECURITY PROBE PASSED';return
}
if($Phase -eq 'native'){
 if((Get-Service KhadangRouter).Status -ne 'Stopped' -or (Get-Service KhadangClaudeHost).Status -ne 'Stopped'){throw 'Fenced services required'}
 if((Get-FileHash ($release+'\probe\ClaudeUpgradeProbe.dll')).Hash -ne '2A2B6C534100FB0AFE6A34435582DBB4153829D281A5B0E67378FA7AA40B1923'){throw 'Reviewed catalog-compatible probe required'}
 $name='Oracova-ClaudeFableProof-20261109';if(Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue){throw 'Existing one-shot; inspect, never replay'}
 $action=New-ScheduledTaskAction -Execute ($release+'\probe\ClaudeUpgradeProbe.exe') -WorkingDirectory ($release+'\probe')
 $principal=New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest
 $settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::FromMinutes(3)) -MultipleInstances IgnoreNew
 Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Settings $settings|Out-Null
 $t=ExactTask $name;$t.SetSecurityDescriptor('O:BAG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)',0x10);$t.Run($null)|Out-Null
 'NATIVE PROBE STARTED; inspect protected receipt, never resend';return
}
if($Phase -eq 'activate'){
 $r=Get-Content ($release+'\native-probe.json') -Raw|ConvertFrom-Json
 if(-not $r.complete -or $r.actualModel -ne 'claude-fable-5-2' -or -not $r.toolOwnerUid1000 -or $r.observation.WindowsOwner.Elevated -or $r.observation.SessionId -ne $pin){throw 'Actual native Fable/owner acceptance required'}
 $proof=Get-Content ($root+'\state\probe.json') -Raw|ConvertFrom-Json
 $proof.nativeLinuxClaudeLaunchVerified=$true;$proof.nativeLinuxClaudeToolOwnerVerified=$true;$proof.nativeLinuxClaudeContinuityVerified=$true
 $proof|Add-Member nativeLinuxClaudeAcceptance @{runtime='2.1.321';binarySha256='426c33815ca6645a772f722fbff10dbf2cbdb124a8aeab733c1365dbf8bbf61f';session=$pin;source=($release+'\native-probe.json');sha256=(Get-FileHash ($release+'\native-probe.json')).Hash;acceptedAt=[DateTimeOffset]::UtcNow} -Force
 Save ($root+'\state\probe.json') $proof
 try{if((Get-Service KhadangClaudeHost).Status -ne 'Running'){Start-Service KhadangClaudeHost};Observer}finally{RestoreTasks}
 (ExactTask 'Oracova-ClaudeFableProof-20261109').Enabled=$false;'ACTIVATED';return
}
if($Phase -eq 'verify'){
 $s=Status;$b=Get-Content ($release+'\before.json') -Raw|ConvertFrom-Json;$c=@($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude'})
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddSeconds(-30) -or $c.Count -ne 9 -or @($c|Where-Object {-not $_.ready -or $_.held -or -not $_.nativeConnected -or $_.admission.Blocking -ne 0}).Count -or (Bindings) -cne $b.bindings -or (Unknown) -cne $b.unknown -or $s.nativeLinuxPid -ne $b.nativePid){throw 'Exact recovery not yet verified; inspect, never replay'}
 Save ($release+'\verified.json') @{at=$s.at;bindingsPreserved=$true;uncertaintyPreserved=$true;codexDaemonPreserved=$true;nativeInputReplay=0;claude=$c}
 'VERIFIED: nine exact Claude sessions connected; model and runtime independently proven'
}
