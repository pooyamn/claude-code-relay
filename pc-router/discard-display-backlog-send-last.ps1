# Exact owner request: discard Display's old outgoing queue and send only the
# final native attachment. Manual owner delivery does not reset automatic quota.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$OutputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$root='C:\ProgramData\KhadangRouter';$release="$root\owner-discard-display-last-file-20261015"
$pin='01a11701-137a-76c2-b997-5f5d0a9c96e0';$key='bubble/'+$pin
$filename='Vayo-LCD-V1.11-revision481-Keil5-external-build.zip'
$digest='88cd59f210562b0ab963909213351b80cd978b3700289e740c5d16a00d3e9ae7';$size=3767621
$request='owner-discard-display-last-file/20261015/revision481'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne '20890485D499759E6BE4E0120F761EB87DA34C4CC0166C64D65C3BE183159EC6' -or
 (Get-FileHash "$root\config.json").Hash -ne '70AB674B2B297489C6C5D78965335B3E5B738E15C7F9FBCAB9D51D1A78D8A205' -or (Test-Path $release)){throw 'Exact fresh owner action required; never repeat an uncertain upload'}
$helper='C:\Users\pou\AppData\Local\Temp\deploy-switch-isolation-20261014.ps1'
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helpers changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Unknown','Bindings','HostIdentity','Hex','ExactTask','Fenced')){
 $d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true)
 if(-not $d){throw 'Missing helper'};. ([ScriptBlock]::Create($d.Extent.Text))
}
LoadSql 'C:\ProgramData\OracovaNativeRemote\inspect-state.ps1' 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$s=Get-Content "$root\state\status.json" -Raw -Encoding UTF8|ConvertFrom-Json
$route=@($s.nativeSessions|Where-Object {$_.binding.Chat -eq -1004393585932 -and $_.binding.Topic -eq 2})
if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or $route.Count -ne 1 -or $route[0].held -or $route[0].busy -or $route[0].binding.ThreadId -ne $pin){throw 'Exact idle, healthy Display route required'}
New-Item -ItemType Directory $release|Out-Null;Protect $release $true
Copy-Item "C:\Users\pou\AppData\Local\Temp\$filename" "$release\$filename";Protect "$release\$filename"
if((Get-FileHash "$release\$filename").Hash.ToLowerInvariant() -cne $digest -or (Get-Item "$release\$filename").Length -ne $size){throw 'Latest native attachment snapshot changed'}
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
$before=@{unknown=(Unknown);bindings=(Bindings);host=(HostIdentity);startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled}
Save "$release\before.json" $before
$db=$null;$lease=$null;$attempt=$null;$rawToken=$null;$client=$null;$content=$null
try{
 foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $name;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 LoadSql 'C:\ProgramData\OracovaNativeRemote\stage-dut-topic.ps1' '0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF' 'PcbaRegistry'
 $lease=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=[PcbaRegistry]::new()
 if($db.Read("SELECT id FROM updates WHERE status IN ('received','dispatching','unknown')").Length -or
  $db.Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length -or
  $db.Read("SELECT key FROM meta WHERE key='$request'").Length){throw 'Unsettled intake/effect or repeated owner request; preserve'}
 $binding=$db.Read('SELECT payload FROM bindings WHERE chat=-1004393585932 AND topic=2')[0][0]|ConvertFrom-Json
 if($binding.ThreadId -ne $pin -or $binding.Workspace -cne '/Users/pouya/.openclaw/workspace/futek-ai/display-source-code-recovery'){throw 'Existing exact binding changed'}
 if($db.Read("SELECT id FROM operations WHERE kind='telegram/sendDocument' AND json_extract(payload,'$.chat_id')=-1004393585932 AND json_extract(payload,'$.message_thread_id')=2 AND json_extract(payload,'$.filename')='$filename'").Length){throw 'Latest file has an earlier attempt; do not resend'}
 $b=$db.Read("SELECT value FROM meta WHERE key='$key'")[0][0]|ConvertFrom-Json
 if($b.held -or $b.busy -or $b.sendUnknown -or $null -eq $b.message){throw 'Confirmed current idle bubble required'}
 $answers=@($b.finalAnswer)+@($b.pendingAnswers)+@($b.pendingResponses|ForEach-Object finalAnswer)
 if(@($answers|ForEach-Object Parts|Where-Object SendUnknown).Count -or @($answers|ForEach-Object Files|Where-Object SendUnknown).Count -or
  @($b.pendingResponses|Where-Object {$_.sendUnknown -and $null -eq $_.message}).Count){throw 'Uncertain current outbox; do not discard receipts'}
 Save "$release\discarded-outbox.json" $b
 $counts=@{pendingAnswers=@($b.pendingAnswers).Count;pendingResponses=@($b.pendingResponses).Count;finalParts=@($b.finalAnswer.Parts).Count;finalFiles=@($b.finalAnswer.Files).Count}
 $budgetBefore=($db.Read("SELECT key,value FROM meta WHERE key LIKE 'telegram/daily-output/-1004393585932/2/%'")|ConvertTo-Json -Compress)
 $b.pendingAnswers=@();$b.pendingResponses=@()
 $b.finalAnswer=@{Candidate='';Explicit=$false;Completed=$true;Parts=@();Files=@()}
 $b.goalReplyPending=$false;$b.goalReplyExcludedItems=@();$b.lastAnswer='';$b.tail=''
 $b.status='Ready';$b.nativeStatus='Ready';$b.outputRateLimited=$false
 $v=(@{binding=$binding;bubble=$b}|ConvertTo-Json -Depth 100 -Compress|& "$root\bin\KhadangRouter.exe" --validate-outbox) -join "`n"
 if($LASTEXITCODE){throw 'Cleared outbox failed validation'};$valid=$v|ConvertFrom-Json
 if(-not $valid.valid -or $valid.uncertain -or $valid.pendingAnswers -or $valid.pendingBubbles){throw 'Outbox not empty'}
 $audit=@{schema='ccrelay.owner_discard_outbox.v1';binding=$binding;discarded=$counts;file=$filename;sha256=$digest;size=$size;automaticQuotaChanged=$false;inputReplay=$false;at=[DateTimeOffset]::UtcNow.ToString('o')}
 Save "$release\request.json" $audit
 $db.Read('BEGIN IMMEDIATE')|Out-Null
 try{
  $db.Read("UPDATE meta SET value=CAST(X'$(Hex $b)' AS TEXT) WHERE key='$key'")|Out-Null
  $db.Read("INSERT INTO meta VALUES('$request',CAST(X'$(Hex $audit)' AS TEXT))")|Out-Null
  $db.Read('COMMIT')|Out-Null
 }catch{$db.Read('ROLLBACK')|Out-Null;throw}
 if((Unknown) -cne $before.unknown -or (Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host){throw 'Unrelated custody changed'}
 # Explicit owner send only. Credential stays in this reviewed administrator
 # process; it is never printed, exported to the agent, or placed on a CLI.
 Add-Type -AssemblyName System.Security;Add-Type -AssemblyName System.Net.Http
 $policy=Get-Content "$root\config.json" -Raw -Encoding UTF8|ConvertFrom-Json
 $rawToken=[Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($policy.CredentialFile),[Text.Encoding]::UTF8.GetBytes('khadang-pc-router-v1'),[Security.Cryptography.DataProtectionScope]::LocalMachine)
 $token=[Text.Encoding]::UTF8.GetString($rawToken)
 $handler=[Net.Http.HttpClientHandler]::new();$handler.AllowAutoRedirect=$false
 $client=[Net.Http.HttpClient]::new($handler);$client.Timeout=[TimeSpan]::FromSeconds(180)
 $content=[Net.Http.MultipartFormDataContent]::new()
 $content.Add([Net.Http.StringContent]::new('-1004393585932'),'chat_id')
 $content.Add([Net.Http.StringContent]::new('2'),'message_thread_id')
 $content.Add([Net.Http.StringContent]::new($filename),'caption')
 $media=[Net.Http.ByteArrayContent]::new([IO.File]::ReadAllBytes("$release\$filename"))
 $media.Headers.ContentType=[Net.Http.Headers.MediaTypeHeaderValue]::new('application/zip');$content.Add($media,'document',$filename)
 $attempt=[Guid]::NewGuid().ToString('N')
 $payload=@{chat_id=[long]-1004393585932;message_thread_id=2;filename=$filename;size=$size;sha256=$digest;explicitOwnerRequest=$request}
 $db.Read("INSERT INTO operations VALUES('$attempt','telegram/sendDocument',CAST(X'$(Hex $payload)' AS TEXT),'attempting',NULL)")|Out-Null
 Save "$release\upload-intent.json" @{operation=$attempt;payload=$payload;automaticRetry=$false}
 try{
  $response=$client.PostAsync(('https://api.telegram.org/bot'+$token+'/sendDocument'),$content).GetAwaiter().GetResult()
  $raw=$response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
  if($raw.Length -gt 2097152){throw 'Oversize receipt'}
  $reply=$raw|ConvertFrom-Json
  if(-not $reply.ok){$db.Read("UPDATE operations SET status='rejected' WHERE id='$attempt' AND status='attempting'")|Out-Null;throw 'Telegram explicitly rejected owner upload'}
  $r=$reply.result
  if(-not $response.IsSuccessStatusCode -or $r.chat.id -ne -1004393585932 -or $r.message_thread_id -ne 2 -or $r.message_id -le 0 -or
   $r.document.file_name -cne $filename -or $r.document.file_size -ne $size){throw 'Owner upload receipt target/file mismatch'}
  $db.Read("UPDATE operations SET status='confirmed',result=CAST(X'$(Hex $r)' AS TEXT) WHERE id='$attempt' AND status='attempting'")|Out-Null
  Save "$release\upload-confirmed.json" @{operation=$attempt;message=$r.message_id;chat=$r.chat.id;topic=$r.message_thread_id;filename=$filename;size=$size;sha256=$digest;at=[DateTimeOffset]::UtcNow.ToString('o')}
 }catch{
  $db.Read("UPDATE operations SET status='unknown' WHERE id='$attempt' AND status='attempting'")|Out-Null
  throw 'Owner upload did not produce a verified receipt; no automatic retry'
 }
 if(($db.Read("SELECT key,value FROM meta WHERE key LIKE 'telegram/daily-output/-1004393585932/2/%'")|ConvertTo-Json -Compress) -cne $budgetBefore){throw 'Automatic quota changed unexpectedly'}
 Save "$release\verified.json" @{discarded=$counts;sentFile=$filename;message=$r.message_id;sameNativeThread=$pin;automaticQuotaChanged=$false;inputsReplayed=0;at=[DateTimeOffset]::UtcNow.ToString('o')}
}finally{
 if($rawToken){[Array]::Clear($rawToken,0,$rawToken.Length)};$token=$null
 if($content){$content.Dispose()};if($client){$client.Dispose()}
 if($db){$db.Dispose()};if($lease){$lease.Dispose()}
 if((Get-Service KhadangRouter).Status -eq 'Stopped'){Start-Service KhadangRouter}
 foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$enabled=if($name -like '*Startup'){$before.startup}else{$before.watchdog};if($enabled){(ExactTask $name).Enabled=$true}}
}
[IO.File]::ReadAllText("$release\verified.json")
