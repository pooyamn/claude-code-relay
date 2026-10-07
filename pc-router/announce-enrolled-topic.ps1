param([Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$')][string]$ThreadId)
# Fixed verified-topic result to the newly enrolled existing topic. No arbitrary bot messages,
# credentials in output, native inputs, polling or replay after an unknown send.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Controller elevated maintenance lane required'}
$release=Join-Path $root ('topic-enrollment-'+$ThreadId)
if((Get-Item $release).Attributes -band [IO.FileAttributes]::ReparsePoint -or -not (Get-Acl $release).AreAccessRulesProtected){throw 'Protected literal enrollment evidence required'}
$plan=Get-Content "$release\plan.json" -Raw -Encoding UTF8|ConvertFrom-Json
$live=Get-Content "$release\live-verified.json" -Raw -Encoding UTF8|ConvertFrom-Json
$s=Get-Content "$root\state\status.json" -Raw -Encoding UTF8|ConvertFrom-Json
$p=Get-Content "$root\config.json" -Raw -Encoding UTF8|ConvertFrom-Json
if($live.initialBinding.ThreadId -ne $ThreadId -or $plan.binding.ThreadId -ne $ThreadId -or
 $plan.binding.Chat -ne $live.binding.Chat -or $plan.binding.Topic -ne $live.binding.Topic -or
 (Get-Service KhadangRouter).Status.ToString() -ne 'Running' -or [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-2) -or
 @($s.bindings|Where-Object {$_.ThreadId -eq $live.binding.ThreadId -and $_.Chat -eq $live.binding.Chat -and $_.Topic -eq $live.binding.Topic}).Count -ne 1 -or
 @($s.bindings|Where-Object {$_.ThreadId -eq $plan.source.ThreadId -and $_.Chat -eq $plan.source.Chat -and $_.Topic -eq $plan.source.Topic}).Count -ne 1 -or
 $p.BotUsername -ne 'TheKhadangBot' -or $p.BotId -ne 8735489806){throw 'Verified result and original source route required'}
if(Test-Path "$release\announcement-result.json"){Get-Content "$release\announcement-result.json" -Raw;return}
if(Test-Path "$release\announcement-attempt.json"){throw 'Unconfirmed announcement; reconcile, never resend automatically'}
function SaveNew([string]$Path,$Value){
 $bytes=[Text.Encoding]::UTF8.GetBytes(($Value|ConvertTo-Json -Depth 8 -Compress))
 $f=[IO.File]::Open($Path,'CreateNew','Write','None');try{$f.Write($bytes,0,$bytes.Length);$f.Flush($true)}finally{$f.Dispose()}
}
$plain=$null;$token=$null
try{
 Add-Type -AssemblyName System.Security
 $plain=[Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($p.CredentialFile),[Text.Encoding]::UTF8.GetBytes('khadang-pc-router-v1'),[Security.Cryptography.DataProtectionScope]::LocalMachine)
 $token=[Text.Encoding]::UTF8.GetString($plain).Trim()
 if($token -notmatch '^8735489806:[A-Za-z0-9_-]{20,100}$'){throw 'Wrong protected bot credential'}
 $link='https://t.me/c/'+([string]$live.binding.Chat).Substring(4)+'/'+$live.binding.Topic
 $body=@{chat_id=$live.binding.Chat;message_thread_id=$live.binding.Topic;disable_web_page_preview=$true;disable_notification=$true;
  text=('Ready: '+$live.binding.Name+' is connected to a fresh '+$live.binding.Backend+' session on the PC.'+"`n"+
   'Project folder: '+$live.binding.Workspace+"`n"+'Send your project instructions or files here to begin.')}
 SaveNew "$release\announcement-attempt.json" @{chat=$body.chat_id;topic=$body.message_thread_id;thread=$ThreadId;at=[DateTimeOffset]::UtcNow.ToString('o')}
 $raw=Invoke-WebRequest -Uri ('https://api.telegram.org/bot'+$token+'/sendMessage') -Method Post -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes(($body|ConvertTo-Json -Compress))) -UseBasicParsing -MaximumRedirection 0 -TimeoutSec 30
 $r=$raw.Content|ConvertFrom-Json
 if(-not $r.ok -or $r.result.chat.id -ne $body.chat_id -or $r.result.message_thread_id -ne $body.message_thread_id -or $r.result.message_id -le 0){throw 'Announcement receipt differs'}
 $receipt=@{chat=$body.chat_id;topic=$body.message_thread_id;message=$r.result.message_id;newTopicLink=$link;at=[DateTimeOffset]::UtcNow.ToString('o')}
 SaveNew "$release\announcement-result.json" $receipt;$receipt|ConvertTo-Json -Compress
}catch{Write-Output 'Announcement not confirmed; inspect protected receipts. No automatic retry.';exit 1}
finally{if($plain){[Array]::Clear($plain,0,$plain.Length)};$token=$null}
