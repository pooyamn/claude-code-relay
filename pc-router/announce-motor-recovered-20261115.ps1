# Exact owner-requested recovery notice. No model input, polling or send retry.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$release="$root\release-motor-history-recovery-20261115"
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$v=[IO.File]::ReadAllText("$release\verified.json")|ConvertFrom-Json
$s=[IO.File]::ReadAllText("$root\state\status.json")|ConvertFrom-Json
$p=[IO.File]::ReadAllText("$root\config.json")|ConvertFrom-Json
$b=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq '8cd2d34c-0805-4705-8197-d11de0728499'})
if((-not $v.motor.nativeConnected -or $v.motor.held) -or (Get-Service KhadangRouter).Status -ne 'Running' -or
 (Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne 'C6BAB770BDC160B62CE36A279E8EBF4039852CF7314A088D15CA5EB6F1DC6B45' -or
 [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $b.Count -ne 1 -or $b[0].held -or -not $b[0].nativeConnected -or
 $b[0].binding.Chat -ne -1003550185469 -or $b[0].binding.Topic -ne 14439 -or $b[0].binding.Workspace -cne '/Users/pouya/.openclaw/workspace/motorcontrol-plant' -or
 $p.BotUsername -ne 'TheKhadangBot' -or $p.BotId -ne 8735489806){throw 'Fresh exact verified Motorcontrol recovery required'}
if(Test-Path "$release\notice-result.json"){[IO.File]::ReadAllText("$release\notice-result.json");return}
if(Test-Path "$release\notice-attempt.json"){throw 'Unconfirmed notice; reconcile, never retry'}
function SaveNew([string]$Path,$Value){$bytes=[Text.Encoding]::UTF8.GetBytes(($Value|ConvertTo-Json -Depth 6 -Compress));$f=[IO.File]::Open($Path,'CreateNew','Write','None');try{$f.Write($bytes,0,$bytes.Length);$f.Flush($true)}finally{$f.Dispose()}}
$body=@{chat_id=-1003550185469;message_thread_id=14439;disable_web_page_preview=$true;disable_notification=$true;text=(
 'Motorcontrol Plant is back online in the same Claude session. The recovery reader now handles native task run IDs, structured queue receipts and completed background agents. Regression tests passed.'+"`n`n"+
 'Your history and project files are unchanged. Messages received while held were retained, not replayed. Please send your current instruction again.')}
$plain=$null;$token=$null
try{
 Add-Type -AssemblyName System.Security
 $plain=[Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($p.CredentialFile),[Text.Encoding]::UTF8.GetBytes('khadang-pc-router-v1'),[Security.Cryptography.DataProtectionScope]::LocalMachine)
 $token=[Text.Encoding]::UTF8.GetString($plain).Trim()
 if($token -notmatch '^8735489806:[A-Za-z0-9_-]{20,100}$'){throw 'Wrong protected bot credential'}
 SaveNew "$release\notice-attempt.json" @{chat=$body.chat_id;topic=$body.message_thread_id;thread=$b[0].binding.ThreadId;at=[DateTimeOffset]::UtcNow.ToString('o')}
 $raw=Invoke-WebRequest -Uri ('https://api.telegram.org/bot'+$token+'/sendMessage') -Method Post -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes(($body|ConvertTo-Json -Compress))) -UseBasicParsing -MaximumRedirection 0 -TimeoutSec 30
 $r=$raw.Content|ConvertFrom-Json
 if(-not $r.ok -or $r.result.chat.id -ne $body.chat_id -or $r.result.message_thread_id -ne $body.message_thread_id -or $r.result.message_id -le 0){throw 'Notice receipt differs'}
 $receipt=@{chat=$body.chat_id;topic=$body.message_thread_id;message=$r.result.message_id;telegramConfirmed=$true;nativeOwnerRoundTripVerified=$false;at=[DateTimeOffset]::UtcNow.ToString('o')}
 SaveNew "$release\notice-result.json" $receipt;$receipt|ConvertTo-Json -Compress
}catch{[Console]::WriteLine('Notice delivery unconfirmed; inspect protected evidence, never resend automatically.');exit 1}
finally{if($plain){[Array]::Clear($plain,0,$plain.Length)};$token=$null}
