param(
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$')][string]$ThreadId,
 [Parameter(Mandatory=$true)][ValidateLength(1,128)][string]$Name,
 [Parameter(Mandatory=$true)][long]$ChatId,
 [switch]$RetryPreflight
)
# Creates one owner-requested topic, not a session, binding or competing poller.
# ChatId is the requesting topic's forum unless the owner chooses another.
# Require the caller to resolve it; never silently fall back to Ai Dispatch.
# A durable attempted effect without its successful result is never replayed.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote'
$state=Join-Path $native ('codex-topic-'+$ThreadId)
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or $Name -match '[\x00-\x1f\x7f]'){throw 'Exact owner deployment and topic name required'}
foreach($path in @($root,$native)){
 $item=Get-Item -LiteralPath $path;$acl=Get-Acl -LiteralPath $path
 if($item.Attributes -band [IO.FileAttributes]::ReparsePoint -or -not $acl.AreAccessRulesProtected -or $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne 'S-1-5-32-544'){throw 'Protected literal roots required'}
}
if(Test-Path -LiteralPath $state){
 if((Get-Item -LiteralPath $state).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Redirected receipt refused'}
 if(Test-Path -LiteralPath "$state\result.json"){
  $saved=Get-Content -LiteralPath "$state\result.json" -Raw|ConvertFrom-Json
  if($saved.phase -eq 'created-not-bound' -and $saved.thread -eq $ThreadId -and $saved.chat -eq $ChatId -and $saved.name -eq $Name){$saved|ConvertTo-Json -Depth 8 -Compress;return}
 }
 if($RetryPreflight -and -not (Test-Path -LiteralPath "$state\attempt.json") -and -not (Test-Path -LiteralPath "$state\result.json") -and (Test-Path -LiteralPath "$state\failure.json")){
  $failure=Get-Content -LiteralPath "$state\failure.json" -Raw|ConvertFrom-Json
  $acl=Get-Acl -LiteralPath $state
  if($failure.phase -ne 'preflight-failed-no-creation' -or -not $acl.AreAccessRulesProtected -or $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne 'S-1-5-32-544'){throw 'Uncertain or unprotected prior attempt; no replay'}
  # Retain the failed permission check. No create call was attempted, and the
  # operator explicitly requested a fresh preflight after correcting it.
  Move-Item -LiteralPath $state -Destination ($state+'-preflight-'+[Guid]::NewGuid().ToString('N'))
 }else{throw 'Existing creation attempt requires reconciliation; no replay'}
}
$p=Get-Content -LiteralPath "$root\config.json" -Raw|ConvertFrom-Json
if($p.OwnerId -ne 110123423 -or $p.BotId -ne 8735489806 -or $p.BotUsername -ne 'TheKhadangBot' -or
 -not ($p.ChatId -eq $ChatId -or @($p.AdditionalChats|Where-Object {$_.Chat -eq $ChatId -and $_.IsForum}).Count -eq 1)){throw 'Exact owner, Khadang and admitted forum required'}
function PrivateAcl([bool]$Directory){
 $a=$(if($Directory){[Security.AccessControl.DirectorySecurity]::new()}else{[Security.AccessControl.FileSecurity]::new()})
 $a.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'));$a.SetAccessRuleProtection($true,$false)
 foreach($sid in @('S-1-5-32-544','S-1-5-18')){
  if($Directory){$rule=[Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','ContainerInherit,ObjectInherit','None','Allow')}
  else{$rule=[Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','Allow')};$a.AddAccessRule($rule)
 };return $a
}
function SaveNew([string]$Path,$Value){
 $bytes=[Text.Encoding]::UTF8.GetBytes(($Value|ConvertTo-Json -Depth 10 -Compress))
 $f=[IO.FileStream]::new($Path,[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::None,65536,[IO.FileOptions]::None,(PrivateAcl $false))
 try{$f.Write($bytes,0,$bytes.Length);$f.Flush($true)}finally{$f.Dispose()}
}
[IO.Directory]::CreateDirectory($state,(PrivateAcl $true))|Out-Null
$effectStarted=$false;$plain=$null;$token=$null;$stage='credential'
try{
 Add-Type -AssemblyName System.Security
 $plain=[Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($p.CredentialFile),[Text.Encoding]::UTF8.GetBytes('khadang-pc-router-v1'),[Security.Cryptography.DataProtectionScope]::LocalMachine)
 $token=[Text.Encoding]::UTF8.GetString($plain).Trim()
 if($token -notmatch '^8735489806:[A-Za-z0-9_-]{20,100}$'){throw 'Exact Khadang credential required'}
 function Call([string]$Method,$Body){
  if($Method -notin @('getMe','getChat','getChatMember','createForumTopic')){throw 'Unexpected Telegram method'}
  $raw=Invoke-WebRequest -Uri ('https://api.telegram.org/bot'+$token+'/'+$Method) -Method Post -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes(($Body|ConvertTo-Json -Compress))) -UseBasicParsing -MaximumRedirection 0 -TimeoutSec 30
  if($raw.Content.Length -gt 2097152){throw 'Provider response bound'}
  $envelope=$raw.Content|ConvertFrom-Json;if(-not $envelope.ok){throw 'Provider rejected request'};return $envelope.result
 }
 $stage='bot';$me=Call 'getMe' @{};if($me.id -ne $p.BotId -or $me.username -ne $p.BotUsername){throw 'Wrong bot'}
 $stage='forum';$chat=Call 'getChat' @{chat_id=$ChatId};if($chat.id -ne $ChatId -or -not $chat.is_forum){throw 'Wrong forum'}
 $stage='permission';$member=Call 'getChatMember' @{chat_id=$ChatId;user_id=$p.BotId};if($member.status -ne 'administrator' -or -not $member.can_manage_topics){throw 'Topic management missing'}
 $operation=[Guid]::NewGuid().ToString('N')
 SaveNew "$state\attempt.json" @{phase='attempting';operation=$operation;chat=$ChatId;name=$Name;thread=$ThreadId;at=[DateTimeOffset]::UtcNow.ToString('o')}
 $stage='create';$effectStarted=$true;$topic=Call 'createForumTopic' @{chat_id=$ChatId;name=$Name}
 if($topic.message_thread_id -le 0 -or $topic.name -ne $Name){throw 'Topic identity mismatch'}
 $receipt=@{phase='created-not-bound';operation=$operation;chat=$ChatId;topic=$topic.message_thread_id;name=$Name;thread=$ThreadId;at=[DateTimeOffset]::UtcNow.ToString('o')}
 SaveNew "$state\result.json" $receipt;$receipt|ConvertTo-Json -Depth 8 -Compress
}catch{
 SaveNew "$state\failure.json" @{phase=$(if($effectStarted){'unknown-no-replay'}else{'preflight-failed-no-creation'});stage=$stage;failureType=$_.Exception.GetType().Name;at=[DateTimeOffset]::UtcNow.ToString('o')}
 Write-Output 'Creation not accepted; inspect protected receipts. No automatic retry.';exit 1
}finally{if($plain){[Array]::Clear($plain,0,$plain.Length)};$token=$null}
