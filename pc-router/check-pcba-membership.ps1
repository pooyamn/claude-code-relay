$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed administrator membership check only'}
Add-Type -AssemblyName System.Security
Add-Type -AssemblyName System.Net.Http
$raw=$null;$client=$null
try{
 $raw=[Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes('C:\ProgramData\KhadangRouter\khadang-token.dpapi'),[Text.Encoding]::UTF8.GetBytes('khadang-pc-router-v1'),[Security.Cryptography.DataProtectionScope]::LocalMachine)
 $endpoint='https://api.telegram.org/bot'+[Text.Encoding]::UTF8.GetString($raw).Trim()+'/'
 $handler=[Net.Http.HttpClientHandler]::new();$handler.AllowAutoRedirect=$false
 $client=[Net.Http.HttpClient]::new($handler);$client.Timeout=[TimeSpan]::FromSeconds(20)
 function ReadBot([string]$Method,[string]$Body){
  $content=[Net.Http.StringContent]::new($Body,[Text.Encoding]::UTF8,'application/json')
  $response=$client.PostAsync($endpoint+$Method,$content).GetAwaiter().GetResult()
  try{
   if(-not $response.IsSuccessStatusCode -or $response.Content.Headers.ContentLength -gt 1000000){throw 'Bot metadata read rejected'}
   $value=$response.Content.ReadAsStringAsync().GetAwaiter().GetResult()|ConvertFrom-Json
   if(-not $value.ok){throw 'Bot metadata read rejected'}
   return $value.result
  }finally{$response.Dispose();$content.Dispose()}
 }
 $me=ReadBot 'getMe' '{}'
 if($me.id -ne 8735489806 -or $me.username -ne 'TheKhadangBot'){throw 'Unexpected bot identity'}
 $chat=ReadBot 'getChat' '{"chat_id":-1004395661179}'
 $member=ReadBot 'getChatMember' '{"chat_id":-1004395661179,"user_id":8735489806}'
 if($chat.id -ne -1004395661179 -or -not $chat.is_forum -or $member.status -notin @('member','administrator','creator') -or
  ($member.status -eq 'member' -and $chat.permissions.can_send_messages -eq $false)){throw 'Original PCBA forum is not writable by this bot'}
 [ordered]@{verified=$true;bot=$me.username;chat=$chat.id;isForum=$chat.is_forum;membership=$member.status;
  readsAllGroupMessages=$me.can_read_all_group_messages;telegramWrites=$false;at=[DateTimeOffset]::UtcNow.ToString('o')}|ConvertTo-Json -Compress
}catch{
 # Never print an HTTP exception, request URI, raw response or credential.
 throw 'PCBA bot membership verification failed; no topic/router change'
}finally{if($raw){[Array]::Clear($raw,0,$raw.Length)};if($client){$client.Dispose()};$endpoint=$null}
