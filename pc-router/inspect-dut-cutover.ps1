$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
# Read only safe migration metadata; never print unrelated owner messages.
$raw=(. (Join-Path $PSScriptRoot 'inspect-state.ps1')) -join "`n"
$s=$raw|ConvertFrom-Json
$operations=@();$updates=@()
foreach($row in [RouterReceipts]::Read("SELECT kind,status,payload,result FROM operations ORDER BY rowid")){
 $p=$row[2]|ConvertFrom-Json;$r=if($row[3]){$row[3]|ConvertFrom-Json}else{$null}
 if($p.parameters.threadId -in @('7dc840b0-402f-451e-bc79-dadfb706d363')){
  $operations+=@{kind=$row[0];status=$row[1];thread=$p.parameters.threadId;turn=$r.turn.id}
 }elseif(($p.chat_id -eq -1004395661179 -and $p.message_thread_id -eq 53) -or
  ($r.chat.id -eq -1004395661179 -and $r.message_thread_id -eq 53)){
  $operations+=@{kind=$row[0];status=$row[1];message=$r.message_id;returnedChat=$r.chat.id;returnedTopic=$r.message_thread_id;
   requestedTopic=$p.message_thread_id;requestedCharacters=([string]$p.text).Length;
   connectedNotice=([string]$r.text -like '*Connected to the PC session.*')}
 }
}
foreach($row in [RouterReceipts]::Read('SELECT id,status,payload FROM updates ORDER BY id DESC LIMIT 50')){
 $m=($row[2]|ConvertFrom-Json).message
 if($m.chat.id -ne -1004395661179 -or $m.message_thread_id -ne 53){continue}
 $updates+=@{update=[long]$row[0];status=$row[1];message=$m.message_id;topic=$m.message_thread_id;
  owner=($m.from.id -eq 110123423 -and -not $m.from.is_bot)}
}
$root='C:\ProgramData\KhadangRouter'
$resultRows=[RouterReceipts]::Read("SELECT value FROM meta WHERE key='claude/result/7dc840b0-402f-451e-bc79-dadfb706d363'")
$lastResult=if($resultRows.Count){$resultRows[0][0]|ConvertFrom-Json}else{$null}
[ordered]@{service=$s.service;startup=(Get-ScheduledTask -TaskName 'Oracova-KhadangStartup').State.ToString();
 unknown=$s.status.unknown;nativePid=$s.status.nativePid;nativeLinuxPid=$s.status.nativeLinuxPid;
 policy=(Get-FileHash "$root\config.json").Hash;router=(Get-FileHash "$root\bin\KhadangRouter.dll").Hash;
 proof=@{at=$s.probe.testedAt;verified=$s.probe.verified;policy=$s.probe.policySha256;code=$s.probe.routerSha256;
  credentialDenied=$s.probe.credentialAndCodeDenied;linuxOwner=$s.probe.nativeLinuxCommandOwnerVerified;
  linuxVerified=$s.probe.nativeLinuxCodexVerified;windowsSandbox=$s.probe.nativeWindowsSandboxVerified;
  claudeLaunch=$s.probe.nativeLinuxClaudeLaunchVerified;claudeTools=$s.probe.nativeLinuxClaudeToolOwnerVerified;
  claudeContinuity=$s.probe.nativeLinuxClaudeContinuityVerified;claudeAcceptance=$s.probe.nativeLinuxClaudeAcceptance};
 bindings=$s.bindings;updates=$updates;operations=$operations;nativeSessions=$s.status.nativeSessions;statusAt=$s.status.at;
 lastNativeResult=@{session=$lastResult.session_id;subtype=$lastResult.subtype;isError=$lastResult.is_error;
  replyCharacters=([string]$lastResult.result).Length};
 bubbles=@($s.metadata|Where-Object key -like 'bubble/*'|ForEach-Object {@{thread=$_.key;chat=$_.value.chat;topic=$_.value.topic;
  message=$_.value.message;busy=$_.value.busy;held=$_.value.held;sendUnknown=$_.value.sendUnknown;pending=@($_.value.pendingResponses).Count}});
 at=[DateTimeOffset]::UtcNow.ToString('o')}|ConvertTo-Json -Depth 10 -Compress
