param([Parameter(Mandatory=$true)][ValidateSet('preflight','stage','probe','activate','verify')][string]$Phase,
 [ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$NativeReceiptSha256)
# One owner-requested ordinary group. Never create a forum, migrate a group,
# impersonate another human, replace existing sessions or replay old input.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote';$temp='C:\Users\pou\AppData\Local\Temp'
$release="$root\datehack-group-759324878";$chat=[long]-5304042088
$code='0E219BC929A8DB6903DDC3F172BC2D14F22E710D7270D48EEB2E33668000E851'
$oldPolicy='20CBA6C69B0463B3AA576B690737C7C9586FEB120501C1C28CE554F2032CF85A'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or -not (Get-Acl $PSScriptRoot).AreAccessRulesProtected){throw 'Protected reviewed controller maintenance required'}
$helper="$temp\deploy-switch-isolation-20261014.ps1"
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Pinned helper required'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Unknown','Bindings','HostIdentity','ExactTask','Fenced','Hex')){
 $d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true);if(-not $d){throw 'Missing reviewed helper'};. ([ScriptBlock]::Create($d.Extent.Text))
}
LoadSql "$native\inspect-state.ps1" 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
function Status{[IO.File]::ReadAllText("$root\state\status.json")|ConvertFrom-Json}
function Artifacts($policy){if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $code -or (Get-FileHash "$root\config.json").Hash -ne $policy){throw 'Pinned code/policy required'}}
function Restore($before){foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){(ExactTask $name).Enabled=[bool]$(if($name -like '*Startup'){$before.startup}else{$before.watchdog})}}
function StartObserver([bool]$Probe=$false){
 $mode=if($Probe){'--probe-service'}else{'--service'};$svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" '+$mode+' --config "'+$root+'\config.json"');StartMode='Manual'}
 if($r.ReturnValue){throw 'Service path update failed'};Start-Service KhadangRouter
}
function OwnerRequest{
 $rows=[RouterReceipts]::Read('SELECT payload FROM updates WHERE id=759324878')
 if($rows.Length -ne 1){throw 'Original owner update required'};$m=($rows[0][0]|ConvertFrom-Json).message
 if($m.from.id -ne 110123423 -or $m.from.is_bot -or $m.chat.id -ne -1003550185469 -or $m.message_thread_id -ne 816 -or $m.forward_origin -or $m.sender_chat -or $m.via_bot -or $m.text -cne 'Create a new project for datehack group'){throw 'Original authenticated owner scope differs'}
 $b=[RouterReceipts]::Read('SELECT payload FROM bindings WHERE chat=-1003550185469 AND topic=816')[0][0]|ConvertFrom-Json
 if($b.ThreadId -ne '01a0facd-1bc0-7d23-95d6-c32fde0c62db' -or $b.Workspace -cne '/Users/pouya/.openclaw/workspace/claude-code-relay'){throw 'Controller binding differs'}
}
function NoInflight{
 if([RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('received','dispatching','unknown')").Length -or [RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'In-flight or unsettled mutation: stop before changes'}
}
OwnerRequest
if($Phase -eq 'preflight'){
 Artifacts $oldPolicy;NoInflight
 if(Test-Path $release){throw 'Existing enrollment: inspect retained receipts, never recreate'}
 $s=Status;if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or -not $s.nativeTransportHealthy -or -not $s.backgroundHealthy -or @($s.bindings|Where-Object {$_.Chat -eq $chat -or $_.Workspace -eq '/Users/pouya/.openclaw/workspace/datehack'}).Count){throw 'Fresh unique healthy target required'}
 $p=[IO.File]::ReadAllText("$root\config.json")|ConvertFrom-Json
 if(@($p.AdditionalChats|Where-Object Chat -eq $chat).Count){throw 'Existing group admission needs reconciliation'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 $plain=$null;$token=$null
 try{
  Add-Type -AssemblyName System.Security
  $plain=[Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($p.CredentialFile),[Text.Encoding]::UTF8.GetBytes('khadang-pc-router-v1'),[Security.Cryptography.DataProtectionScope]::LocalMachine)
  $token=[Text.Encoding]::UTF8.GetString($plain).Trim();if($token -notmatch '^8735489806:[A-Za-z0-9_-]{20,100}$'){throw 'Exact Khadang credential required'}
  function ReadBot($method,$body){
   if($method -notin @('getChat','getChatMember')){throw 'Read-only group inspection required'}
   $raw=Invoke-WebRequest -Uri ('https://api.telegram.org/bot'+$token+'/'+$method) -Method Post -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes(($body|ConvertTo-Json -Compress))) -UseBasicParsing -MaximumRedirection 0 -TimeoutSec 20
   $v=$raw.Content|ConvertFrom-Json;if(-not $v.ok){throw 'Group inspection rejected'};return $v.result
  }
  $g=ReadBot 'getChat' @{chat_id=$chat};$member=ReadBot 'getChatMember' @{chat_id=$chat;user_id=$p.BotId}
  if($g.id -ne $chat -or $g.title -cne 'DateHack' -or $g.type -ne 'group' -or $g.is_forum -or $member.status -notin @('member','administrator','creator')){throw 'Exact existing DateHack group and bot membership required'}
  Save "$release\group-proof.json" @{chat=$g.id;title=$g.title;type=$g.type;botStatus=$member.status;at=[DateTimeOffset]::UtcNow}
 }catch{throw 'DateHack read-only group verification failed; no admission or native allocation'}finally{if($plain){[Array]::Clear($plain,0,$plain.Length)};$token=$null}
 Save "$release\preflight.json" @{at=[DateTimeOffset]::UtcNow;sourceUpdate=759324878;code=$code;policy=$oldPolicy;chat=$chat;effects=0}
 @{phase='preflight-ready';chat=$chat;regularGroup=$true;nativeAllocated=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'stage'){
 Artifacts $oldPolicy;NoInflight
 if(-not (Test-Path "$release\preflight.json") -or (Test-Path "$release\before.json")){throw 'Fresh verified enrollment required'}
 $file="$temp\datehack-native-759324878.json"
 if(-not $NativeReceiptSha256 -or (Get-FileHash $file).Hash -ne $NativeReceiptSha256){throw 'Pinned native owner receipt required'}
 $n=[IO.File]::ReadAllText($file)|ConvertFrom-Json
 if(-not $n.complete -or $n.unknownEffects -ne 0 -or $n.modelsStarted -ne 0 -or $n.nativeOwnerUid -ne 1000 -or $n.chat -ne $chat -or $n.topic -ne 0 -or $n.name -cne 'DateHack' -or $n.sourceUpdate -ne 759324878 -or $n.workspace -cne '/Users/pouya/.openclaw/workspace/datehack' -or -not $n.checkpointPersisted -or $n.backend -ne 'codex' -or $n.runtime -ne 'linux' -or $n.thread -cnotmatch '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'){throw 'Exact fresh ordinary-owner native allocation required'}
 $s=Status
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or @($s.nativeSessions|Where-Object {$_.binding.Runtime -eq 'windows' -and $_.busy}).Count){throw 'Fresh idle Windows custody required'}
 $before=@{bindings=(Bindings);unknown=(Unknown);host=(HostIdentity);nativePid=$s.nativeLinuxPid;claudePids=@($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude'}|ForEach-Object {@{thread=$_.binding.ThreadId;pid=$_.pid}});held=@($s.nativeSessions|Where-Object held|ForEach-Object {$_.binding.ThreadId});startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled;at=[DateTimeOffset]::UtcNow}
 Save "$release\before.json" $before;Copy-Item "$root\config.json" "$release\previous-config.json";Copy-Item "$root\state\probe.json" "$release\previous-probe.json";Copy-Item $file "$release\native.json"
 try{
  foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $name;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
  $svc=Get-Service KhadangRouter;$svc.Stop();$svc.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(40));Fenced;NoInflight
  if((Unknown) -cne $before.unknown -or (Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host){throw 'Uncertainty, routes or host changed during stop'}
 }catch{try{if((Get-Service KhadangRouter).Status -eq 'Stopped'){StartObserver}}finally{Restore $before};throw}
 LoadSql "$native\stage-dut-topic.ps1" '0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF' 'PcbaRegistry'
 $binding=@{Chat=$chat;Topic=0;Name='DateHack';Workspace=$n.workspace;ThreadId=$n.thread;Backend='codex';Runtime='linux'}
 $lease=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null;$transaction=$false
 try{
  $db=[PcbaRegistry]::new();NoInflight;Artifacts $oldPolicy
  if($db.Read("SELECT payload FROM bindings WHERE chat=$chat OR json_extract(payload,'$.ThreadId')='$($n.thread)' OR json_extract(payload,'$.Workspace')='$($n.workspace)'").Length){throw 'Duplicate group, native ID or workspace'}
  $null=$db.Read("VACUUM INTO '$release\previous-router.db'");Protect "$release\previous-router.db"
  $p=[IO.File]::ReadAllText("$root\config.json")|ConvertFrom-Json
  $p.AdditionalChats=@($p.AdditionalChats)+@(@{Chat=$chat;IsForum=$false})
  Save "$release\candidate-config.json" $p;Save "$release\binding.json" $binding
  $null=$db.Read('BEGIN IMMEDIATE');$transaction=$true
  $null=$db.Read("INSERT INTO bindings(chat,topic,payload) VALUES($chat,0,CAST(X'$(Hex $binding)' AS TEXT))")
  $retained=$db.Read("SELECT payload FROM bindings WHERE chat<>$chat ORDER BY chat,topic")|ConvertTo-Json -Compress
  if($retained -cne $before.bindings){throw 'Original binding bytes changed'}
  if((Unknown) -cne $before.unknown){throw 'Unknown effects changed'}
  Copy-Item "$release\candidate-config.json" "$root\config.json" -Force;Protect "$root\config.json"
  $null=$db.Read('COMMIT');$transaction=$false
  Save "$release\staged.json" @{at=[DateTimeOffset]::UtcNow;binding=$binding;code=$code;policy=(Get-FileHash "$root\config.json").Hash;nativeInputsReplayed=0}
 }catch{if($transaction){$null=$db.Read('ROLLBACK')};throw}finally{if($db){$db.Dispose()};$lease.Dispose()}
 @{phase='staged';chat=$chat;topic=0;nativeDaemonsStopped=0}|ConvertTo-Json -Compress;return
}
$stage=[IO.File]::ReadAllText("$release\staged.json")|ConvertFrom-Json;$before=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json
Artifacts $stage.policy
if($Phase -eq 'probe'){
 Fenced;StartObserver $true;$end=[DateTimeOffset]::UtcNow.AddSeconds(55)
 do{$proof=[IO.File]::ReadAllText("$root\state\probe.json")|ConvertFrom-Json;if($proof.policySha256 -eq $stage.policy -and [DateTimeOffset]$proof.testedAt -gt [DateTimeOffset]$stage.at){break};Start-Sleep -Milliseconds 500}while([DateTimeOffset]::UtcNow -lt $end)
 $svc=Get-Service KhadangRouter;$svc.Stop();$svc.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 if($proof.routerSha256 -ne $code -or $proof.policySha256 -ne $stage.policy -or -not $proof.verified -or -not $proof.credentialAndCodeDenied -or -not $proof.nativeWindowsSandboxVerified -or -not $proof.nativeLinuxCommandOwnerVerified -or $proof.modelInference -or $proof.telegramPolling -or [DateTimeOffset]$proof.testedAt -le [DateTimeOffset]$stage.at){throw 'Fresh matching SYSTEM security proof required'}
 Save "$release\generic-proof.json" $proof
 $old=[IO.File]::ReadAllText("$release\previous-probe.json")|ConvertFrom-Json;$previous=[IO.File]::ReadAllText("$release\previous-config.json")|ConvertFrom-Json;$current=[IO.File]::ReadAllText("$root\config.json")|ConvertFrom-Json
 if(-not $old.nativeLinuxClaudeContinuityVerified -or (HostIdentity) -cne $before.host){throw 'Unchanged native host acceptance required'}
 $newChat=@($current.AdditionalChats|Where-Object Chat -eq $chat)
 if($newChat.Count -ne 1 -or $newChat[0].IsForum -ne $false -or @($newChat[0].PSObject.Properties).Count -ne 2 -or @($current.AdditionalChats).Count -ne @($previous.AdditionalChats).Count+1){throw 'Exact group admission only'}
 $current.AdditionalChats=@($current.AdditionalChats|Where-Object Chat -ne $chat)
 if(($previous|ConvertTo-Json -Depth 100 -Compress) -cne ($current|ConvertTo-Json -Depth 100 -Compress)){throw 'Only exact DateHack chat admission may change'}
 foreach($field in @('nativeLinuxClaudeLaunchVerified','nativeLinuxClaudeToolOwnerVerified','nativeLinuxClaudeContinuityVerified','nativeLinuxClaudeAcceptance')){if($old.PSObject.Properties[$field]){$proof|Add-Member $field $old.$field -Force}}
 $proof|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Only DateHack regular-group admission added; native binaries, connectors, permissions and existing identities unchanged';liveNewClaudeTestClaimed=$false} -Force
 Save "$root\state\probe.json" $proof;Save "$release\accepted.json" @{at=[DateTimeOffset]::UtcNow;policy=$stage.policy}
 @{phase='accepted';credentialBoundaryVerified=$true}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'activate'){
 Fenced;$null=[IO.File]::ReadAllText("$release\accepted.json")
 Save "$release\activated.json" @{at=[DateTimeOffset]::UtcNow};try{StartObserver}finally{Restore $before}
 @{phase='activated';nativeDaemonsStopped=0}|ConvertTo-Json -Compress;return
}
$activation=[IO.File]::ReadAllText("$release\activated.json")|ConvertFrom-Json;$end=[DateTimeOffset]::UtcNow.AddSeconds(55)
do{
 $s=Status;$route=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $stage.binding.ThreadId})
 if([DateTimeOffset]$s.at -gt [DateTimeOffset]$activation.at -and $route.Count -eq 1 -and $route[0].ready -and $route[0].nativeConnected -and -not $route[0].held -and $s.backgroundHealthy -and $s.nativeTransportHealthy){break};Start-Sleep -Milliseconds 500
}while([DateTimeOffset]::UtcNow -lt $end)
if($route.Count -ne 1 -or -not $route[0].ready -or -not $route[0].nativeConnected -or $route[0].held -or [DateTimeOffset]$s.at -le [DateTimeOffset]$activation.at -or $s.nativeLinuxPid -ne $before.nativePid -or @($s.bindings).Count -ne 19){throw 'Fresh exact new group readiness and unchanged native daemon required'}
$all=[RouterReceipts]::Read("SELECT payload FROM bindings WHERE chat<>$chat ORDER BY chat,topic")|ConvertTo-Json -Compress
if($all -cne $before.bindings -or (Unknown) -cne $before.unknown -or (HostIdentity) -cne $before.host){throw 'Existing bindings, unknown receipts or host changed'}
foreach($id in $before.held){if(@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $id -and $_.held}).Count -ne 1){throw 'Existing unrelated hold changed'}}
foreach($old in $before.claudePids){if(@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $old.thread -and $_.pid -eq $old.pid}).Count -ne 1){throw 'Independent Claude generation changed'}}
Restore $before
$result=@{phase='ready';binding=$route[0].binding;routes=19;nativeDaemonUnchanged=$true;unknownReceiptsPreserved=$true;existingBindingsPreserved=$true;phoneRoundTripVerified=$false;at=[DateTimeOffset]::UtcNow}
Save "$release\verified.json" $result;$result|ConvertTo-Json -Depth 6 -Compress
