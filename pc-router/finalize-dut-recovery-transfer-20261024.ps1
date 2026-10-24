# Owner-approved, exact existing-session recovery coordination assignment.
# Administrative audit and one direct source-topic notice; no native input/replay.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote'
$release="$root\release-claude-handoff-20261024"
$id='augur-1-transfer-native-recovery-to-mimic-fast-pcb-20261024-01'
$dut='7dc840b0-402f-451e-bc79-dadfb706d363';$mimic='10ab0d8a-f31c-49ca-ab99-1a6152ae4ee2'
$source='01a104cc-9a63-7901-8897-abf8aff3dfb3';$chat=-1004395661179L
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$helper='C:\Users\pou\AppData\Local\Temp\deploy-switch-isolation-20261014.ps1'
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helper changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','LoadSql')){$d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true);if(-not $d){throw 'Reviewed helper missing'};. ([ScriptBlock]::Create($d.Extent.Text))}
LoadSql "$native\inspect-state.ps1" 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
function SaveNew($path,$value){$bytes=[Text.Encoding]::UTF8.GetBytes(($value|ConvertTo-Json -Depth 10 -Compress));$f=[IO.File]::Open($path,'CreateNew','Write','None');try{$f.Write($bytes,0,$bytes.Length);$f.Flush($true)}finally{$f.Dispose()};Protect $path}
function Route($thread,$topic){
 $r=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -ceq $thread -and $_.binding.Chat -eq $chat -and $_.binding.Topic -eq $topic})
 if($r.Count -ne 1 -or $r[0].binding.Runtime -ne 'linux' -or -not $r[0].ready -or $r[0].held -or -not $r[0].nativeConnected -or $r[0].admission.Blocking -ne 0){throw 'Fresh exact unheld native route required'}
 return $r[0].binding
}
$v=[IO.File]::ReadAllText("$release\verified.json")|ConvertFrom-Json
$s=[IO.File]::ReadAllText("$root\state\status.json")|ConvertFrom-Json
$p=[IO.File]::ReadAllText("$root\config.json")|ConvertFrom-Json
if(-not $v.dutAndMimicReady -or -not $v.claudeNativePidsPreserved -or (Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne '2FF3072D7599A11A76ACE6CCAD23184AE85C207EAEE63B906BC56804DD58B7F5' -or
 (Get-FileHash "$root\config.json").Hash -ne '6271B521E9C069618384FD6632088C7FAF06FDD1CBCB8A7CBCDC36E77215192C' -or (Get-Service KhadangRouter).Status -ne 'Running' -or
 [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or -not $s.backgroundHealthy -or -not $s.nativeTransportHealthy -or
 $p.BotUsername -ne 'TheKhadangBot' -or $p.BotId -ne 8735489806){throw 'Fresh verified deployment required'}
$affected=Route $dut 53;$owner=Route $mimic 3315;$origin=Route $source 18
if($affected.Backend -ne 'claude' -or $owner.Backend -ne 'claude' -or $origin.Backend -ne 'codex'){throw 'Existing provider bindings required'}
$job=[IO.File]::ReadAllText("$root\state\controller-handoffs\$id.json")|ConvertFrom-Json
$receipt=[IO.File]::ReadAllText("$root\state\controller-handoffs\$id.result")|ConvertFrom-Json
$rows=[RouterReceipts]::Read("SELECT value FROM meta WHERE key='controller-handoff/$id'")
if($rows.Length -ne 1){throw 'Single authoritative handoff receipt required'}
$journal=$rows[0][0]|ConvertFrom-Json
foreach($r in @($receipt,$journal)){
 if($r.requestId -cne $id -or $r.state -ne 'accepted' -or $r.mode -ne 'now' -or $r.provider -ne 'claude' -or $null -ne $r.turnId -or $r.uuid -notmatch '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$' -or
  $r.target.ThreadId -cne $mimic -or $r.target.Chat -ne $chat -or $r.target.Topic -ne 3315 -or $r.source.ThreadId -cne $source -or $r.source.Chat -ne $chat -or $r.source.Topic -ne 18){throw 'Exact accepted Claude native UUID receipt required'}
}
if($receipt.uuid -cne $journal.uuid -or $receipt.fingerprint -cne $journal.fingerprint -or $job.RequestId -cne $id -or $job.TextSha256 -cne '3C8443A8F68D838F09CA1B8BF5195F48DCA5BC824A3463692F2851EBF67C0B43' -or
 $job.Source.ThreadId -cne $source -or $job.Target.ThreadId -cne $mimic -or $job.Approval -notlike '*msg_01a16d84-6507-75a2-afd4-e83b81ad9e9e*'){throw 'Owner-approved exact task required'}
$folder="$root\state\recovery-ownership"
if(-not (Test-Path $folder)){New-Item -ItemType Directory $folder|Out-Null;Protect $folder $true}
if((Get-Item $folder).Attributes -band [IO.FileAttributes]::ReparsePoint -or -not (Get-Acl $folder).AreAccessRulesProtected){throw 'Protected literal audit directory required'}
$path="$folder\$dut.json"
if(Test-Path $path){
 $old=[IO.File]::ReadAllText($path)|ConvertFrom-Json
 if($old.requestId -cne $id -or $old.owner.ThreadId -cne $mimic -or $old.nativeReceiptUuid -cne $receipt.uuid){throw 'Different ownership evidence exists; never overwrite'}
}else{
 SaveNew $path @{schema='ccrelay.recovery_coordination.v1';requestId=$id;state='assigned';affected=$affected;owner=$owner;source=$origin;approval=$job.Approval;nativeReceiptUuid=$receipt.uuid;nativeAcceptedAt=$receipt.at;at=[DateTimeOffset]::UtcNow.ToString('o');permissionsGranted=$false;inputReplay=$false;runtimeAuthorizationClaimed=$false;evidence=@("$release\verified.json","$root\repair-claude-host-20261024\verified.json");scope='Recovery coordination/tracking; native safety holds remain session-local and cannot be transferred'}
}
$attempt="$release\recovery-transfer-notice-attempt.json";$result="$release\recovery-transfer-notice-result.json"
if(Test-Path $result){[IO.File]::ReadAllText($result);return}
if(Test-Path $attempt){throw 'Unconfirmed notice: preserve, never resend automatically'}
$body=@{chat_id=$chat;message_thread_id=18;disable_notification=$true;link_preview_options=@{is_disabled=$true};text=(
 'Done: DUT Board Design is back online in its original session and its recovery hold is cleared. Mimic Fast PCB has received the recovery-coordination assignment, confirmed by Claude''s native input receipt.'+"`n`n"+
 'Cause: the shared Claude host was running an older build and its native workers had disconnected. The host is repaired, and the protected handoff path now supports Claude as well as Codex.'+"`n`n"+
 'Both topic histories and bindings are unchanged. No old messages or uncertain actions were replayed. Windows validation passed all 1,875 checks. Request: '+$id)}
$plain=$null;$token=$null
try{
 Add-Type -AssemblyName System.Security
 $plain=[Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($p.CredentialFile),[Text.Encoding]::UTF8.GetBytes('khadang-pc-router-v1'),[Security.Cryptography.DataProtectionScope]::LocalMachine)
 $token=[Text.Encoding]::UTF8.GetString($plain).Trim()
 if($token -notmatch '^8735489806:[A-Za-z0-9_-]{20,100}$'){throw 'Wrong protected bot credential'}
 SaveNew $attempt @{requestId=$id;chat=$chat;topic=18;at=[DateTimeOffset]::UtcNow.ToString('o')}
 $raw=Invoke-WebRequest -Uri ('https://api.telegram.org/bot'+$token+'/sendMessage') -Method Post -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes(($body|ConvertTo-Json -Depth 5 -Compress))) -UseBasicParsing -MaximumRedirection 0 -TimeoutSec 30
 $r=$raw.Content|ConvertFrom-Json
 if(-not $r.ok -or $r.result.chat.id -ne $chat -or $r.result.message_thread_id -ne 18 -or $r.result.message_id -le 0){throw 'Notice receipt differs'}
 $resultValue=@{requestId=$id;chat=$chat;topic=18;message=$r.result.message_id;telegramConfirmed=$true;nativeAssignmentAccepted=$true;nativeReceiptUuid=$receipt.uuid;dutHoldReleased=$true;ownerRoundTripClaimed=$false;at=[DateTimeOffset]::UtcNow.ToString('o')}
 SaveNew $result $resultValue;$resultValue|ConvertTo-Json -Compress
}catch{[Console]::WriteLine('Notice unconfirmed: inspect protected evidence; no automatic resend.');exit 1}
finally{if($plain){[Array]::Clear($plain,0,$plain.Length)};$token=$null}
