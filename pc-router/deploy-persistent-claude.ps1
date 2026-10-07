param([Parameter(Mandatory=$true)][ValidateSet('prepare','fence','stage','probe','accept','activate','capture','restart','verify')][string]$Phase,
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{32}$')][string]$Generation,
 [Parameter(Mandatory=$true)][ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$CodeSha256)
# Independent Claude custody, not a new native session or Telegram input.
# Every phase is inspectable; a failed gate leaves the deployment fenced.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$nativeRoot='C:\ProgramData\OracovaNativeRemote';$hostRoot='C:\ProgramData\KhadangClaudeHost';$release="$root\release-$Generation"
$oldCode='D065CEEAF5BD19214824D97E8F8EDAFBDC48F872BF7BD6D593C9562ED7484322'
$oldPolicy='4C580D6017E40988A30D30E11B75EAA2D2E85AFCA88E35512D244694E449A8E7'
$oldStartup='C5E9E9F0397654D2F4594B23E7B8BF8FA4A1099B1E50242751C866B821AB3D50'
$normal='"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"'
$hostPath='"'+$hostRoot+'\bin\KhadangRouter.exe" --claude-host-service'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Exact PC administrator required'}
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544');$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18');$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
$helper="$nativeRoot\migrate-lab-topics-65fc17bfcb9d47a190ab128b096bba5d.ps1"
foreach($entry in @(@($helper,'86F3D550CBA51D280CE2D6BCDCBD7A3C3B1B1CBB7435FE9BC54590C0F87E6513'),@("$nativeRoot\inspect-state.ps1",'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2'),@("$nativeRoot\stage-dut-topic.ps1",'0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF'))){if((Get-FileHash $entry[0]).Hash -ne $entry[1]){throw 'Protected helper changed'}}
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$t,[ref]$e)
foreach($name in @('Protect','Save')){$def=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true);if($e.Count -or -not $def){throw 'Protected helper syntax'};. ([ScriptBlock]::Create($def.Extent.Text))}
function Receipt([string]$Path,$Value){Save $Path $Value;Protect $Path $false}
function Sql([string]$File,[string]$Class){$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($File,[ref]$t,[ref]$e);$d=$a.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type' -and $n.Extent.Text.Contains("class $Class")},$true);if($e.Count -or -not $d){throw 'Protected SQL helper syntax'};if(-not ($Class -as [type])){& ([ScriptBlock]::Create($d.Extent.Text))}}
Sql "$nativeRoot\inspect-state.ps1" 'RouterReceipts'
if(-not ('ClaudeHostReceipts' -as [type])){Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ClaudeHostReceipts {
 [DllImport("winsqlite3.dll",CharSet=CharSet.Ansi)] static extern int sqlite3_open_v2(string path,out IntPtr db,int flags,IntPtr vfs);
 [DllImport("winsqlite3.dll",CharSet=CharSet.Ansi)] static extern int sqlite3_prepare_v2(IntPtr db,string sql,int bytes,out IntPtr statement,IntPtr tail);
 [DllImport("winsqlite3.dll")] static extern int sqlite3_step(IntPtr statement);
 [DllImport("winsqlite3.dll")] static extern long sqlite3_column_int64(IntPtr statement,int column);
 [DllImport("winsqlite3.dll")] static extern int sqlite3_finalize(IntPtr statement);
 [DllImport("winsqlite3.dll")] static extern int sqlite3_close_v2(IntPtr db);
 public static long Registrations(string path) {
  if(!System.Text.RegularExpressions.Regex.IsMatch(path,@"\AC:\\ProgramData\\KhadangClaudeHost\\state\\[a-f0-9-]{36}\\broker.db\z"))throw new Exception("Exact private worker journal required");
  IntPtr db=IntPtr.Zero, statement=IntPtr.Zero;
  try {
   if(sqlite3_open_v2(path,out db,1|0x10000,IntPtr.Zero)!=0 || sqlite3_prepare_v2(db,"SELECT COUNT(*) FROM operations WHERE kind='claude/control/remote_control'",-1,out statement,IntPtr.Zero)!=0 || sqlite3_step(statement)!=100)throw new Exception("Read-only host receipt observation failed");
   return sqlite3_column_int64(statement,0);
  } finally {if(statement!=IntPtr.Zero)sqlite3_finalize(statement);if(db!=IntPtr.Zero)sqlite3_close_v2(db);}
 }
}
'@}
function Original {if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $oldCode -or (Get-FileHash "$root\config.json").Hash -ne $oldPolicy -or (Get-FileHash "$nativeRoot\router-startup.ps1").Hash -ne $oldStartup){throw 'Production changed; preserve'}}
function Fenced {if((Get-Service KhadangRouter).Status.ToString() -ne 'Stopped' -or (Get-ScheduledTask Oracova-KhadangStartup).State.ToString() -ne 'Disabled'){throw 'Stopped fenced router required'}}
function Inputs {[RouterReceipts]::Read("SELECT id,kind,status FROM operations WHERE kind IN ('native/turn/start','native/turn/steer','claude/user/send-now','claude/control/answer') ORDER BY id")}
function Healthy {
 $s=Get-Content "$root\state\status.json" -Raw|ConvertFrom-Json
 if((Get-Service KhadangRouter).Status.ToString() -ne 'Running' -or $s.unknown -or @($s.bindings).Count -ne 16 -or $s.nativeLinuxPid -ne 479 -or [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-2) -or
  @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude'}).Count -ne 7 -or @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Fresh sixteen connected routes/unchanged Linux daemon required'}
 foreach($row in [RouterReceipts]::Read("SELECT key,value FROM meta WHERE key LIKE 'bubble/%'")){
  $b=$row[1]|ConvertFrom-Json
  if($b.sendUnknown -or @($b.finalAnswer.Parts|Where-Object SendUnknown).Count -or @($b.finalAnswer.Files|Where-Object SendUnknown).Count -or
   @($b.pendingAnswers|ForEach-Object {$_.Parts+$_.Files}|Where-Object SendUnknown).Count -or $b.backend -eq 'claude' -and ($b.busy -or $b.held -or $b.claudeState -ne 'idle')){throw 'Uncertain output or non-idle Claude; preserve'}
  if($b.busy){$route=@($s.bindings|Where-Object ThreadId -eq $row[0].Substring(7));if($route.Count -ne 1 -or $route[0].Backend -ne 'codex' -or $route[0].Runtime -ne 'linux' -or $b.held -or -not $b.turn){throw 'Only independently supervised exact Linux turns may remain active'}}
 }
 return $s
}
function EndpointProof {
 $service=Get-CimInstance Win32_Service -Filter "Name='KhadangClaudeHost'"
 if($service.State -ne 'Running' -or $service.PathName -cne $hostPath -or $service.StartName -ne 'LocalSystem'){throw 'Independent SYSTEM host required'}
 $hostEndpoint=Get-Content "$hostRoot\host.json" -Raw|ConvertFrom-Json
 if($hostEndpoint.Server.Pid -ne $service.ProcessId){throw 'Exact host generation required'}
 $workers=@(Get-ChildItem "$hostRoot\state" -Directory|ForEach-Object {
  $ep=Get-Content "$($_.FullName)\endpoint.json" -Raw|ConvertFrom-Json
  if($ep.Server.Pid -ne $hostEndpoint.Server.Pid -or $ep.Server.CreationTime -ne $hostEndpoint.Server.CreationTime -or -not $ep.NativePid -or -not $ep.Epoch){throw 'Host-bound native worker generation required'}
  $ep|Add-Member RemoteRegistrations ([ClaudeHostReceipts]::Registrations("$($_.FullName)\broker.db"))
  $ep
 })
 if($workers.Count -ne 7){throw 'Seven independent workers required'}
 return @{host=$hostEndpoint;workers=@($workers|Sort-Object {$_.Binding.ThreadId})}
}
if($Phase -eq 'prepare'){
 Original;if(Test-Path "$release\prepared.json"){throw 'Already prepared; reconcile'}
 if((Get-FileHash "$release\candidate\KhadangRouter.dll").Hash -ne $CodeSha256){throw 'Reviewed candidate required'}
 $output=(& "$release\candidate\KhadangRouter.exe" --self-test) -join "`n";if($LASTEXITCODE -ne 0){throw 'Full Windows regression failed; production untouched'}
 Receipt "$release\prepared.json" @{code=$CodeSha256;tests=$output;passed=$true;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='prepared';tests=$output;productionChanged=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'fence'){
 Original;$p=Get-Content "$release\prepared.json" -Raw|ConvertFrom-Json;if(-not $p.passed -or $p.code -ne $CodeSha256){throw 'Windows tests required'}
 if(Test-Path "$release\fenced.json"){throw 'Already fenced; reconcile'}
 if((Get-Service KhadangRouter).Status.ToString() -eq 'Stopped' -and (Test-Path "$release\before.json")){
  Fenced;$prior=Get-Content "$release\before.json" -Raw -Encoding UTF8|ConvertFrom-Json
  if(([RouterReceipts]::Read('SELECT payload FROM bindings ORDER BY chat,topic')|ConvertTo-Json -Compress) -cne ($prior.bindings|ConvertTo-Json -Compress) -or ((Inputs)|ConvertTo-Json -Compress) -cne ($prior.inputs|ConvertTo-Json -Compress)){throw 'Partial fence changed input/registry; preserve'}
  Receipt "$release\fenced.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');stopReadbackReconciled=$true};@{phase='fenced';scmStoppedVerified=$true}|ConvertTo-Json -Compress;return
 }
 $s=Healthy
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";if($svc.PathName -cne $normal -or $svc.StartName -ne 'LocalSystem'){throw 'Exact router service required'}
 Receipt "$release\before.json" @{bindings=[RouterReceipts]::Read('SELECT payload FROM bindings ORDER BY chat,topic');inputs=(Inputs);remote=[RouterReceipts]::Read("SELECT key,value FROM meta WHERE key LIKE 'claude/remote/%' ORDER BY key");bubbles=[RouterReceipts]::Read("SELECT key,value FROM meta WHERE key LIKE 'bubble/%'");startup=(Get-ScheduledTask Oracova-KhadangStartup).State.ToString();at=[DateTimeOffset]::UtcNow.ToString('o')}
 Copy-Item "$root\config.json" "$release\previous-config.json";Copy-Item "$root\state\probe.json" "$release\previous-probe.json";Copy-Item "$nativeRoot\router-startup.ps1" "$release\previous-startup.ps1"
 Disable-ScheduledTask Oracova-KhadangStartup|Out-Null;Stop-ScheduledTask Oracova-KhadangStartup
 try{Stop-Service KhadangRouter}catch{};(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 Receipt "$release\fenced.json" @{at=[DateTimeOffset]::UtcNow.ToString('o')};@{phase='fenced'}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'stage'){
 Fenced;Original;if((Test-Path "$hostRoot") -or (Test-Path "$release\staged.json") -or (Get-Service KhadangClaudeHost -ErrorAction SilentlyContinue)){throw 'Host already exists; reconcile'}
 Sql "$nativeRoot\stage-dut-topic.ps1" 'PcbaRegistry'
 $exclusive=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null
 try{
  $db=[PcbaRegistry]::new();if([int]$db.Read("SELECT (SELECT COUNT(*) FROM operations WHERE status IN ('attempting','unknown') AND kind<>'telegram/editMessageText')+(SELECT COUNT(*) FROM updates WHERE status IN ('dispatching','unknown','received'))")[0][0]){throw 'Pending/uncertain effects; preserve'}
  $null=$db.Read("VACUUM INTO '$release\previous-router.db'");Protect "$release\previous-router.db" $false;Copy-Item "$root\bin" "$release\previous-bin" -Recurse
  New-Item -ItemType Directory $hostRoot|Out-Null;Protect $hostRoot $true
  New-Item -ItemType Directory "$hostRoot\state"|Out-Null;Protect "$hostRoot\state" $true
  Copy-Item "$release\candidate" "$hostRoot\bin" -Recurse;Protect "$hostRoot\bin" $true;Get-ChildItem "$hostRoot\bin" -Recurse -Force|ForEach-Object {Protect $_.FullName $_.PSIsContainer}
  Receipt "$hostRoot\installed.json" @{dll=$CodeSha256;exe=(Get-FileHash "$hostRoot\bin\KhadangRouter.exe").Hash;generation=$Generation;at=[DateTimeOffset]::UtcNow.ToString('o')}
  $null=New-Service -Name KhadangClaudeHost -DisplayName 'Khadang persistent native Claude custody' -BinaryPathName $hostPath -StartupType Manual
  $p=Get-Content "$root\config.json" -Raw|ConvertFrom-Json
  if($p.PersistentClaudeWorkers){throw 'Persistent mode already enabled'};$p|Add-Member PersistentClaudeWorkers $true -Force
  Receipt "$release\candidate-config.json" $p;Copy-Item "$release\candidate-config.json" "$root\config.json" -Force;Protect "$root\config.json" $false
  Copy-Item "$release\candidate\*" "$root\bin" -Recurse -Force;Get-ChildItem "$root\bin" -Recurse -Force|ForEach-Object {Protect $_.FullName $_.PSIsContainer}
  Copy-Item "$release\router-startup.ps1" "$nativeRoot\router-startup.ps1" -Force;Protect "$nativeRoot\router-startup.ps1" $false
  Receipt "$release\staged.json" @{code=$CodeSha256;policy=(Get-FileHash "$root\config.json").Hash;startup=(Get-FileHash "$nativeRoot\router-startup.ps1").Hash;at=[DateTimeOffset]::UtcNow.ToString('o')}
 }finally{if($db){$db.Dispose()};$exclusive.Dispose()}
 @{phase='staged';bindingsChanged=$false;nativeInputsSent=0}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'probe'){
 Fenced;$svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --probe-service --config "'+$root+'\config.json"');StartMode='Manual'}
 if($r.ReturnValue){throw 'Probe service path failed'};Start-Service KhadangRouter;@{phase='probe-running';modelInference=$false;telegramPolling=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'accept'){
 Fenced;$stage=Get-Content "$release\staged.json" -Raw|ConvertFrom-Json;$proof=Get-Content "$root\state\probe.json" -Raw|ConvertFrom-Json;$old=Get-Content "$release\previous-probe.json" -Raw|ConvertFrom-Json
 if($proof.routerSha256 -ne $CodeSha256 -or $proof.policySha256 -ne $stage.policy -or -not $proof.verified -or -not $proof.credentialAndCodeDenied -or -not $proof.aclProbeWithoutProviderSandbox -or -not $proof.nativeWindowsSandboxVerified -or -not $proof.nativeLinuxCodexVerified -or -not $proof.nativeLinuxCommandOwnerVerified -or -not $proof.nativePersistentClaudeHostAclDenied -or $proof.modelInference -or $proof.telegramPolling -or [DateTimeOffset]$proof.testedAt -le [DateTimeOffset]$stage.at -or $old.routerSha256 -ne $oldCode -or $old.policySha256 -ne $oldPolicy -or -not $old.nativeLinuxClaudeLaunchVerified -or -not $old.nativeLinuxClaudeToolOwnerVerified -or -not $old.nativeLinuxClaudeContinuityVerified){throw 'Fresh OS isolation proof and prior native Claude acceptance required'}
 $p=Get-Content "$root\config.json" -Raw|ConvertFrom-Json;$previous=Get-Content "$release\previous-config.json" -Raw|ConvertFrom-Json
 foreach($field in @('LinuxClaude','LinuxCodex','OwnerFullAccess','OwnerId','OwnerSid','ParticipantIds','AdditionalChats','CodexExecutable','CodexSha256','LinuxWorkspaceRoot')){if(($previous.$field|ConvertTo-Json -Depth 100 -Compress) -cne ($p.$field|ConvertTo-Json -Depth 100 -Compress)){throw 'Native launcher/identity/admission changed; prior acceptance cannot be reused'}}
 foreach($file in $p.LinuxClaude.FileSha256.PSObject.Properties){if((Get-FileHash (Join-Path $p.LinuxClaude.PackageRoot $file.Name)).Hash -ne $file.Value){throw 'Native Claude connector changed'}}
 Copy-Item "$root\state\probe.json" "$release\generic-proof.json"
 $proof.nativeLinuxClaudeLaunchVerified=$true;$proof.nativeLinuxClaudeToolOwnerVerified=$true;$proof.nativeLinuxClaudeContinuityVerified=$true
 $proof|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Attested limited-owner launcher, pinned Claude connector/image and native protocol unchanged. Custody moved to independent SYSTEM host; fresh host/worker generation restart proof required separately.';priorCode=$oldCode;modelTestsRerun=$false} -Force
 Receipt "$root\state\probe.json" $proof;Receipt "$release\accepted.json" @{code=$CodeSha256;policy=$stage.policy;at=[DateTimeOffset]::UtcNow.ToString('o')};@{phase='accepted';freshOsProof=$true;hostRestartProofPending=$true}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'activate'){
 Fenced;$accepted=Get-Content "$release\accepted.json" -Raw|ConvertFrom-Json
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $CodeSha256 -or (Get-FileHash "$hostRoot\bin\KhadangRouter.dll").Hash -ne $CodeSha256 -or (Get-FileHash "$root\config.json").Hash -ne $accepted.policy){throw 'Accepted code/policy changed'}
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=$normal;StartMode='Manual'};if($r.ReturnValue){throw 'Normal service path failed'}
 Start-Service KhadangClaudeHost;(Get-Service KhadangClaudeHost).WaitForStatus('Running',[TimeSpan]::FromSeconds(15));Start-Service KhadangRouter
 @{phase='activated';nativeInputsSent=0}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'capture'){
 $s=Healthy;$ep=EndpointProof
 Receipt "$release\host-before-restart.json" @{endpoints=$ep;routerPid=(Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'").ProcessId;remote=[RouterReceipts]::Read("SELECT key,value FROM meta WHERE key LIKE 'claude/remote/%' ORDER BY key");registrations=[RouterReceipts]::Read("SELECT COUNT(*) FROM operations WHERE kind='claude/control/remote_control'")[0][0];inputs=(Inputs);at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='captured';workers=7;hostPid=$ep.host.Server.Pid}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'restart'){
 $null=Healthy;if(-not (Test-Path "$release\host-before-restart.json") -or (Get-ScheduledTask Oracova-KhadangStartup).State.ToString() -ne 'Disabled'){throw 'Captured generations and startup fence required'}
 try{Stop-Service KhadangRouter}catch{};(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30))
 Receipt "$release\router-only-restart.json" @{host=(EndpointProof);at=[DateTimeOffset]::UtcNow.ToString('o')}
 Start-Service KhadangRouter;@{phase='router-only-restarted';hostStopped=$false}|ConvertTo-Json -Compress;return
}
$s=Healthy;$ep=EndpointProof;$before=Get-Content "$release\before.json" -Raw -Encoding UTF8|ConvertFrom-Json;$live=Get-Content "$release\host-before-restart.json" -Raw -Encoding UTF8|ConvertFrom-Json;$restart=Get-Content "$release\router-only-restart.json" -Raw -Encoding UTF8|ConvertFrom-Json
if([DateTimeOffset]$s.at -le [DateTimeOffset]$restart.at -or (Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'").ProcessId -eq $live.routerPid -or
 ($ep|ConvertTo-Json -Depth 100 -Compress) -cne ($live.endpoints|ConvertTo-Json -Depth 100 -Compress)){throw 'Exact host/native PIDs, epochs and pipes must survive router-only restart'}
if(([RouterReceipts]::Read("SELECT key,value FROM meta WHERE key LIKE 'claude/remote/%' ORDER BY key")|ConvertTo-Json -Compress) -cne ($live.remote|ConvertTo-Json -Compress) -or
 [RouterReceipts]::Read("SELECT COUNT(*) FROM operations WHERE kind='claude/control/remote_control'")[0][0] -ne $live.registrations){throw 'Router restart amended remote enrollment or timestamp'}
if(([RouterReceipts]::Read('SELECT payload FROM bindings ORDER BY chat,topic')|ConvertTo-Json -Compress) -cne ($before.bindings|ConvertTo-Json -Compress) -or
 ((Inputs)|ConvertTo-Json -Compress) -cne ($before.inputs|ConvertTo-Json -Compress)){throw 'Bindings or native input activity changed; inspect before claiming no replay'}
foreach($row in $before.bubbles){$old=$row[1]|ConvertFrom-Json;if($old.held -and -not ([RouterReceipts]::Read("SELECT value FROM meta WHERE key='$($row[0])'")[0][0]|ConvertFrom-Json).held){throw 'Existing safety hold changed'}}
Receipt "$release\verified.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');hostPid=$ep.host.Server.Pid;workers=7;routes=16;routerRestarted=$true;nativeWorkerGenerationsUnchanged=$true;cloudEnrollmentUnchanged=$true;remoteReceiptTimestampsUnchanged=$true;nativeInputsSent=0;existingHoldsPreserved=$true}
if($before.startup -ne 'Disabled'){Enable-ScheduledTask Oracova-KhadangStartup|Out-Null;Start-ScheduledTask Oracova-KhadangStartup}
@{phase='verified';workers=7;routes=16;routerRestartSurvived=$true;registrationsAddedByRouterRestart=0;nativeInputsSent=0;startupRestored=$true}|ConvertTo-Json -Compress
