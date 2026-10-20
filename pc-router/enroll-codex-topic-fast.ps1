param(
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$')][string]$ThreadId,
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$')][string]$SourceThreadId,
 [Parameter(Mandatory=$true)][ValidatePattern('^/Users/pouya/\.openclaw/workspace/[A-Za-z0-9_./-]+$')][string]$Workspace,
 [Parameter(Mandatory=$true)][long]$SourceUpdate,
 [Parameter(Mandatory=$true)][ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$ExpectedCode,
 [Parameter(Mandatory=$true)][ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$ExpectedPolicy
)
# Enrollment-only controller lane: no configuration changes, model prompts,
# daemon restart, uncertain-effect replay, or edits of existing registry rows.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$nativeRoot='C:\ProgramData\OracovaNativeRemote'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or $ThreadId -eq $SourceThreadId -or $Workspace -match '(^|/)\.\.?(/|$)'){throw 'Controller administrator and distinct literal session required'}
$release=Join-Path $root ('topic-enrollment-'+$ThreadId)
function Save([string]$Name,$Value){
 $bytes=[Text.Encoding]::UTF8.GetBytes(($Value|ConvertTo-Json -Depth 100 -Compress))
 $f=[IO.File]::Open((Join-Path $release $Name),'CreateNew','Write','None')
 try{$f.Write($bytes,0,$bytes.Length);$f.Flush($true)}finally{$f.Dispose()}
}
function LoadType([string]$Path,[string]$Hash,[string]$Class){
 if((Get-FileHash $Path).Hash -ne $Hash){throw 'Protected helper changed'}
 $tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
 $def=$ast.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type' -and $n.Extent.Text -like ('*class '+$Class+'*')},$true)
 if($errors.Count -or -not $def){throw 'Protected database helper missing'}
 if(-not ($Class -as [type])){& ([ScriptBlock]::Create($def.Extent.Text))}
}
LoadType "$nativeRoot\inspect-state.ps1" 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
LoadType "$nativeRoot\stage-dut-topic.ps1" '0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF' 'PcbaRegistry'
function Original {
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $ExpectedCode -or (Get-FileHash "$root\config.json").Hash -ne $ExpectedPolicy){throw 'Live code or policy changed'}
}
Original
if(Test-Path "$release\live-verified.json"){Get-Content "$release\live-verified.json" -Raw;return}
if(Test-Path $release){throw 'Interrupted enrollment exists; reconcile retained receipts, do not rerun'}
$policy=Get-Content "$root\config.json" -Raw -Encoding UTF8|ConvertFrom-Json
$proof=Get-Content "$root\state\probe.json" -Raw|ConvertFrom-Json
if($policy.OwnerId -ne 110123423 -or $policy.BotUsername -ne 'TheKhadangBot' -or -not $proof.verified -or $proof.policySha256 -ne $ExpectedPolicy -or $proof.routerSha256 -ne $ExpectedCode){throw 'Matching native code/policy proof required'}
$created=Get-Content "$nativeRoot\codex-topic-$ThreadId\result.json" -Raw -Encoding UTF8|ConvertFrom-Json
if($created.phase -ne 'created-not-bound' -or $created.thread -ne $ThreadId){throw 'Exact confirmed Telegram creation required'}
$rows=[RouterReceipts]::Read("SELECT payload FROM bindings WHERE json_extract(payload,'$.ThreadId')='$SourceThreadId'")
if($rows.Length -ne 1){throw 'Exact source binding required'};$source=$rows[0][0]|ConvertFrom-Json
if($source.Chat -ne $created.chat -or $source.Backend -notin @('codex','claude') -or $source.Runtime -ne 'linux'){throw 'Same-forum admitted native source required'}
$rows=[RouterReceipts]::Read("SELECT payload FROM updates WHERE id=$SourceUpdate")
if($rows.Length -ne 1){throw 'Original owner request missing'};$request=($rows[0][0]|ConvertFrom-Json).message
if($request.from.id -ne $policy.OwnerId -or $request.from.is_bot -or $request.chat.id -ne $source.Chat -or $request.message_thread_id -ne $source.Topic -or $request.forward_origin -or $request.sender_chat -or $request.via_bot -or $request.text -notmatch [regex]::Escape($created.name)){throw 'Original authenticated owner request differs'}
$before=Get-Content "$root\state\status.json" -Raw|ConvertFrom-Json
function DisconnectedActiveClaude($Sessions,$PreviouslyHeldIds){
 @($Sessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected -and $_.binding.ThreadId -notin $PreviouslyHeldIds})
}
# An existing scoped hold is intentionally disconnected. Preserve it, without
# making unrelated topic creation depend on recovering that native history.
# Freeze the allowlist before restart: a NEW hold must still fail verification.
$heldClaudeIds=@($before.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and $_.held}|ForEach-Object {$_.binding.ThreadId})
if((Get-Service KhadangRouter).Status -ne 'Running' -or [DateTimeOffset]$before.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-2) -or @(DisconnectedActiveClaude $before.nativeSessions $heldClaudeIds).Count){throw 'Fresh live router and connected non-held native Claude required'}
$binding=[ordered]@{Chat=$created.chat;Topic=$created.topic;Name=$created.name;Workspace=$Workspace;ThreadId=$ThreadId;Backend='codex';Runtime='linux'}
function SafeDb($Db){
 if([int]$Db.Read("SELECT COUNT(*) FROM updates WHERE status IN ('received','dispatching','unknown')")[0][0]){throw 'Unsettled incoming delivery; no enrollment'}
 foreach($row in $Db.Read("SELECT kind,payload,status FROM operations WHERE status IN ('attempting','unknown')")){
  if($row[0] -eq 'telegram/editMessageText'){continue}
  if($row[2] -ne 'unknown' -or $row[0] -notin @('telegram/sendMessage','telegram/sendRichMessage','telegram/sendPhoto','telegram/sendDocument')){throw 'Uncertain native or unclassified operation; no enrollment'}
  $effect=$row[1]|ConvertFrom-Json
  if($effect.chat_id -ge 0 -or $effect.message_thread_id -le 0 -or ($effect.chat_id -eq $binding.Chat -and $effect.message_thread_id -eq $binding.Topic) -or $Db.Read("SELECT payload FROM bindings WHERE chat=$([long]$effect.chat_id) AND topic=$([int]$effect.message_thread_id)").Length -ne 1){throw 'Unscoped or target delivery uncertainty; preserve'}
  # Preserve this unrelated output's full ledger/bubble bytes. Never clear,
  # replay, infer success or allow an uncertain native operation through here.
 }
 foreach($row in $Db.Read("SELECT key,value FROM meta WHERE key LIKE 'bubble/%'")){
  $bubble=$row[1]|ConvertFrom-Json;$id=$row[0].Substring(7)
  if(-not $bubble.busy){continue}
  $routes=$Db.Read("SELECT payload FROM bindings WHERE json_extract(payload,'$.ThreadId')='$id'")
  if($routes.Length -ne 1){throw 'Unbound active session; preserve'};$route=$routes[0][0]|ConvertFrom-Json
  if($route.Backend -ne 'codex' -or $route.Runtime -ne 'linux' -or (-not $bubble.held -and -not $bubble.turn)){throw 'Router-owned native work or missing durable turn; preserve'}
 }
}
$db=[PcbaRegistry]::new();try{SafeDb $db}finally{$db.Dispose()}
if([RouterReceipts]::Read("SELECT key FROM meta WHERE key LIKE 'bubble/%' AND json_array_length(value,'$.pendingAnswers')>256").Length){throw 'Oversized persisted outbox would block restart; no changes made'}
$watchdog=(Get-ScheduledTask Oracova-KhadangStartup).State.ToString() -ne 'Disabled'
New-Item -ItemType Directory $release|Out-Null
$acl=[Security.AccessControl.DirectorySecurity]::new();$acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'));$acl.SetAccessRuleProtection($true,$false)
foreach($sid in @('S-1-5-32-544','S-1-5-18')){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','ContainerInherit,ObjectInherit','None','Allow'))};Set-Acl $release $acl
Save 'plan.json' @{binding=$binding;source=$source;code=$ExpectedCode;policy=$ExpectedPolicy;sourceUpdate=$SourceUpdate;count=$before.bindings.Count;nativeLinuxPid=$before.nativeLinuxPid;watchdogEnabled=$watchdog;at=[DateTimeOffset]::UtcNow.ToString('o')}
Copy-Item "$root\config.json" "$release\previous-config.json";Copy-Item "$root\state\probe.json" "$release\previous-probe.json"
$locked=$null;$db=$null;$transaction=$false;$committed=$false
try{
 Disable-ScheduledTask Oracova-KhadangStartup|Out-Null;Stop-ScheduledTask Oracova-KhadangStartup
 try{Stop-Service KhadangRouter}catch{if((Get-Service KhadangRouter).Status -ne 'Stopped'){throw}}
 (Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(20))
 $locked=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=[PcbaRegistry]::new();SafeDb $db;Original
 $prior=$db.Read('SELECT payload FROM bindings ORDER BY chat,topic')
 if($prior.Length -ne $before.bindings.Count -or $db.Read("SELECT payload FROM bindings WHERE json_extract(payload,'$.ThreadId')='$ThreadId' OR (chat=$($binding.Chat) AND topic=$($binding.Topic))").Length){throw 'Duplicate or changed registry; preserve'}
 Save 'previous-bindings.json' $prior
 $held=$db.Read("SELECT key,value FROM meta WHERE key LIKE 'bubble/%' AND json_extract(value,'$.held')=1");Save 'previous-held.json' $held
 $uncertain=$db.Read("SELECT id,kind,payload,status,result FROM operations WHERE status='unknown' AND kind<>'telegram/editMessageText' ORDER BY id");Save 'previous-uncertain.json' $uncertain
 $digest=$db.UnrelatedDigest();$null=$db.Read("VACUUM INTO '$release\previous-router.db'")
 $null=$db.Read('BEGIN IMMEDIATE');$transaction=$true
 $payload=$binding|ConvertTo-Json -Compress;$hex=([BitConverter]::ToString([Text.Encoding]::UTF8.GetBytes($payload))).Replace('-','')
 $null=$db.Read("INSERT INTO bindings(chat,topic,payload) VALUES($($binding.Chat),$($binding.Topic),CAST(X'$hex' AS TEXT))")
 $retained=$db.Read("SELECT payload FROM bindings WHERE NOT(chat=$($binding.Chat) AND topic=$($binding.Topic)) ORDER BY chat,topic")
 if($db.UnrelatedDigest() -ne $digest -or ($retained|ConvertTo-Json -Compress) -cne ($prior|ConvertTo-Json -Compress)){throw 'Existing registry or ledger changed'}
 Original;$null=$db.Read('COMMIT');$transaction=$false;$committed=$true
 Save 'staged.json' @{binding=$binding;policyUnchanged=$true;ledgerPreserved=$true;at=[DateTimeOffset]::UtcNow.ToString('o')}
}catch{
 if($transaction){$null=$db.Read('ROLLBACK')}
 throw
}finally{
 if($db){$db.Dispose()};if($locked){$locked.Dispose()}
 if((Get-Service KhadangRouter).Status -eq 'Stopped'){Start-Service KhadangRouter}
 if(-not $committed -and $watchdog){Enable-ScheduledTask Oracova-KhadangStartup|Out-Null}
}
$deadline=[DateTimeOffset]::UtcNow.AddSeconds(55);$verified=$false
while([DateTimeOffset]::UtcNow -lt $deadline){
 $status=Get-Content "$root\state\status.json" -Raw|ConvertFrom-Json
 $bubbleRows=[RouterReceipts]::Read("SELECT value FROM meta WHERE key='bubble/$ThreadId'")
 if([DateTimeOffset]$status.at -gt [DateTimeOffset]$before.at -and $status.bindings.Count -eq ($before.bindings.Count+1) -and $status.nativeLinuxPid -eq $before.nativeLinuxPid -and $bubbleRows.Length -eq 1){
  $bubble=$bubbleRows[0][0]|ConvertFrom-Json
  if(-not $bubble.held -and -not $bubble.sendUnknown -and (($bubble.status -eq 'Ready' -and -not $bubble.busy) -or ($bubble.busy -and $bubble.turn))){$verified=$true;break}
 };Start-Sleep -Milliseconds 500
}
if(-not $verified){throw 'Binding retained but live readiness unconfirmed; inspect without recreation'}
Original
$retained=[RouterReceipts]::Read("SELECT payload FROM bindings WHERE NOT(chat=$($binding.Chat) AND topic=$($binding.Topic)) ORDER BY chat,topic")
if(($retained|ConvertTo-Json -Compress) -cne ($prior|ConvertTo-Json -Compress)){throw 'Old bindings changed after restart'}
$nowUncertain=[RouterReceipts]::Read("SELECT id,kind,payload,status,result FROM operations WHERE status='unknown' AND kind<>'telegram/editMessageText' ORDER BY id")
if(($nowUncertain|ConvertTo-Json -Compress) -cne ($uncertain|ConvertTo-Json -Compress)){throw 'Uncertain effects changed; inspect'}
foreach($row in $held){$current=[RouterReceipts]::Read("SELECT value FROM meta WHERE key='$($row[0])'");if($current.Length -ne 1 -or -not ($current[0][0]|ConvertFrom-Json).held){throw 'Existing hold cleared; inspect'}}
if(@(DisconnectedActiveClaude $status.nativeSessions $heldClaudeIds).Count){throw 'Old Claude connection lost; inspect'}
if($watchdog){Enable-ScheduledTask Oracova-KhadangStartup|Out-Null}
$link='https://t.me/c/'+([string]$binding.Chat).Substring(4)+'/'+$binding.Topic
$result=@{binding=$binding;initialBinding=$binding;link=$link;source=$source;existingRoutesPreserved=$true;sharedDaemonUnchanged=$true;policyUnchanged=$true;existingUnknownsPreserved=$true;startupRestored=$true;phoneRoundTripVerified=$false;at=[DateTimeOffset]::UtcNow.ToString('o')}
Save 'live-verified.json' $result;$result|ConvertTo-Json -Depth 8 -Compress
