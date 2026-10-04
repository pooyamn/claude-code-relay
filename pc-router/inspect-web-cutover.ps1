$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
# Reuse the reviewed, read-only receipt reader. Capture its broad report instead
# of printing unrelated messages; never open credentials or submit RPCs.
$raw=(. (Join-Path $PSScriptRoot 'inspect-state.ps1')) -join "`n"
$state=$raw|ConvertFrom-Json
$thread='01a104a6-9fce-74a3-bdb0-e6dc04237ce7'
$updates=@()
foreach($row in [RouterReceipts]::Read('SELECT id,status,payload FROM updates ORDER BY id DESC LIMIT 30')){
 $u=$row[2]|ConvertFrom-Json;$m=$u.message
 if($m.chat.id -ne -1003550185469 -or $m.message_thread_id -ne 8660){continue}
 $updates+=@{updateId=[long]$row[0];status=$row[1];messageId=$m.message_id;owner=($m.from.id -eq 110123423 -and -not $m.from.is_bot);
  hi=($m.text -eq 'Hi');control=($m.text -like '/status*')}
}
$operations=@()
foreach($row in [RouterReceipts]::Read("SELECT kind,status,payload,result FROM operations WHERE kind LIKE 'native/turn/%' OR kind IN ('telegram/sendMessage','telegram/editMessageText') ORDER BY rowid")){
 $p=$row[2]|ConvertFrom-Json;$r=if($row[3]){$row[3]|ConvertFrom-Json}else{$null}
 if($p.parameters.threadId -eq $thread){
  $operations+=@{kind=$row[0];status=$row[1];nativeTurn=$r.turn.id;expectedTurn=$p.parameters.expectedTurnId;thread=$p.parameters.threadId}
 }elseif(($p.chat_id -eq -1003550185469 -and $p.message_thread_id -eq 8660) -or
  ($r.chat.id -eq -1003550185469 -and $r.message_thread_id -eq 8660)){
  $operations+=@{kind=$row[0];status=$row[1];messageId=$r.message_id;requestedMessage=$p.message_id;
   requestedCharacters=([string]$p.text).Length;returnedChat=$r.chat.id;returnedTopic=$r.message_thread_id;
   hiReply=([string]$r.text -like '*Hi Pouya!*')}
 }
}
$bubble=($state.metadata|Where-Object key -eq ('bubble/'+$thread)).value
[ordered]@{host=$state.host;service=$state.service;status=$state.status;updates=$updates;operations=$operations;
 bubble=@{chat=$bubble.chat;topic=$bubble.topic;message=$bubble.message;busy=$bubble.busy;held=$bubble.held;sendUnknown=$bubble.sendUnknown;
  status=$bubble.status;pendingCount=@($bubble.pendingResponses).Count;hiReply=($bubble.tail -like '*Hi Pouya!*')};
 existingLg=($state.bindings|Where-Object ThreadId -eq '01a10114-cbad-7a80-ae57-b9af8f8478c7');
 at=[DateTimeOffset]::UtcNow.ToString('o')}|ConvertTo-Json -Depth 12 -Compress
