param([Parameter(Mandatory=$true)][ValidateSet('base','controller')][string]$Topic)
# Owner-requested repair confirmation, not a native/user prompt or replay.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$release="$root\release-reconciliation-20261024-v2"
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$v=[IO.File]::ReadAllText("$release\verified.json")|ConvertFrom-Json
$s=[IO.File]::ReadAllText("$root\state\status.json")|ConvertFrom-Json
$p=[IO.File]::ReadAllText("$root\config.json")|ConvertFrom-Json
$chat=if($Topic -eq 'base'){-1004395661179L}else{-1003550185469L}
$number=if($Topic -eq 'base'){18}else{816}
$thread=if($Topic -eq 'base'){'01a104cc-9a63-7901-8897-abf8aff3dfb3'}else{'01a0facd-1bc0-7d23-95d6-c32fde0c62db'}
$b=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -ceq $thread -and $_.binding.Chat -eq $chat -and $_.binding.Topic -eq $number})
if(-not $v.baseAndControllerReady -or (Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne '32E50A1F4199BF281BDE3BC71B0ACB94731DF0B9BC6981CD82002EF863261C25' -or (Get-Service KhadangRouter).Status -ne 'Running' -or
 [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $b.Count -ne 1 -or $b[0].held -or -not $b[0].ready -or -not $b[0].nativeConnected -or $b[0].admission.Blocking -ne 0 -or
 $p.BotUsername -ne 'TheKhadangBot' -or $p.BotId -ne 8735489806){throw 'Fresh exact verified route required'}
$attempt="$release\notice-$Topic-attempt.json";$result="$release\notice-$Topic-result.json"
if(Test-Path $result){[IO.File]::ReadAllText($result);return}
if(Test-Path $attempt){throw 'Unconfirmed notice: preserve, never retry automatically'}
function SaveNew($path,$value){$bytes=[Text.Encoding]::UTF8.GetBytes(($value|ConvertTo-Json -Depth 6 -Compress));$f=[IO.File]::Open($path,'CreateNew','Write','None');try{$f.Write($bytes,0,$bytes.Length);$f.Flush($true)}finally{$f.Dispose()}}
$body=@{chat_id=$chat;message_thread_id=$number;disable_notification=$true;link_preview_options=@{is_disabled=$true};text=(
 'Telegram bridge restored for this exact session. Recovery now rechecks stale holds against the native session, and command-menu failures no longer block message reception.'+"`n`n"+
 'Your session and history are unchanged. Old retained messages were not replayed. Please resend your current instruction here; this is a bridge notice, not an agent reply.')}
$plain=$null;$token=$null
try{
 Add-Type -AssemblyName System.Security
 $plain=[Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($p.CredentialFile),[Text.Encoding]::UTF8.GetBytes('khadang-pc-router-v1'),[Security.Cryptography.DataProtectionScope]::LocalMachine)
 $token=[Text.Encoding]::UTF8.GetString($plain).Trim()
 if($token -notmatch '^8735489806:[A-Za-z0-9_-]{20,100}$'){throw 'Wrong protected bot credential'}
 SaveNew $attempt @{chat=$chat;topic=$number;thread=$thread;at=[DateTimeOffset]::UtcNow.ToString('o')}
 $raw=Invoke-WebRequest -Uri ('https://api.telegram.org/bot'+$token+'/sendMessage') -Method Post -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes(($body|ConvertTo-Json -Depth 5 -Compress))) -UseBasicParsing -MaximumRedirection 0 -TimeoutSec 30
 $r=$raw.Content|ConvertFrom-Json
 if(-not $r.ok -or $r.result.chat.id -ne $chat -or $r.result.message_thread_id -ne $number -or $r.result.message_id -le 0){throw 'Notice receipt differs'}
 $receipt=@{chat=$chat;topic=$number;message=$r.result.message_id;telegramConfirmed=$true;freshOwnerRoundTripVerified=$false;at=[DateTimeOffset]::UtcNow.ToString('o')}
 SaveNew $result $receipt;$receipt|ConvertTo-Json -Compress
}catch{[Console]::WriteLine('Notice unconfirmed: inspect protected evidence; no automatic resend.');exit 1}
finally{if($plain){[Array]::Clear($plain,0,$plain.Length)};$token=$null}
