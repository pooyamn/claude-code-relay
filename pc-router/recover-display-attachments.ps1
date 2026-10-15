# One-shot owner-requested recovery after another historical 20 MiB upload timed
# out. Retain old attachments outside active delivery; never replay unknown sends.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$OutputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$root='C:\ProgramData\KhadangRouter';$release="$root\release-daily-output-20261015"
$pin='01a11701-137a-76c2-b997-5f5d0a9c96e0';$key='bubble/'+$pin
$op='d718435264094f869e0240a49334830d';$archive="$release\retained-historical-attachments"
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne '20890485D499759E6BE4E0120F761EB87DA34C4CC0166C64D65C3BE183159EC6' -or
 (Get-FileHash "$root\config.json").Hash -ne '70AB674B2B297489C6C5D78965335B3E5B738E15C7F9FBCAB9D51D1A78D8A205' -or (Test-Path $archive)){throw 'Exact fresh recovery required'}
$helper='C:\Users\pou\AppData\Local\Temp\deploy-switch-isolation-20261014.ps1'
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helpers changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Unknown','Bindings','HostIdentity','Hex','ExactTask','Fenced')){
 $d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true)
 if(-not $d){throw 'Missing helper'};. ([ScriptBlock]::Create($d.Extent.Text))
}
LoadSql 'C:\ProgramData\OracovaNativeRemote\inspect-state.ps1' 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
$before=@{unknown=(Unknown);bindings=(Bindings);host=(HostIdentity);startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled}
New-Item -ItemType Directory $archive|Out-Null;Protect $archive $true;Save "$archive\before.json" $before
try{
 foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $name;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
 Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 LoadSql 'C:\ProgramData\OracovaNativeRemote\stage-dut-topic.ps1' '0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF' 'PcbaRegistry'
 $lease=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null
 try{
  $db=[PcbaRegistry]::new()
  if($db.Read("SELECT id FROM updates WHERE status IN ('received','dispatching','unknown')").Length -or
   $db.Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Unsettled intake/effect; preserve'}
  $binding=$db.Read('SELECT payload FROM bindings WHERE chat=-1004393585932 AND topic=2')[0][0]|ConvertFrom-Json
  if($binding.ThreadId -ne $pin -or $binding.Workspace -cne '/Users/pouya/.openclaw/workspace/futek-ai/display-source-code-recovery'){throw 'Exact existing binding required'}
  $raw=$db.Read("SELECT value FROM meta WHERE key='$key'")[0][0];$b=$raw|ConvertFrom-Json
  $effect=$db.Read("SELECT payload,status FROM operations WHERE id='$op'")[0];$p=$effect[0]|ConvertFrom-Json
  if(-not $b.held -or $b.busy -or $b.sendUnknown -or $effect[1] -ne 'unknown' -or $p.chat_id -ne $binding.Chat -or $p.message_thread_id -ne $binding.Topic -or
   $p.sha256 -ne 'b38ac088fe5a8fa7693cc45901b421907033469970b0c382edf1c24b9483de27' -or $p.size -ne 20910669){throw 'Exact second historical timeout required'}
  foreach($row in $db.Read("SELECT id,kind FROM operations WHERE status='unknown' AND kind<>'telegram/editMessageText'")){
   if($row[1] -ne 'telegram/sendDocument' -or $row[0] -notin @($op,'a1271f1d97834aa2a9637031094c2198')){throw 'Unexpected uncertain effect; preserve'}
  }
  $answers=@($b.finalAnswer)+@($b.pendingAnswers)+@($b.pendingResponses|ForEach-Object finalAnswer)
  if(@($answers|ForEach-Object Parts|Where-Object SendUnknown).Count -or @($b.pendingResponses|Where-Object {$_.sendUnknown -and $null -eq $_.message}).Count){throw 'Uncertain text; preserve'}
  $unknown=@($answers|ForEach-Object Files|Where-Object SendUnknown)
  if($unknown.Count -ne 1 -or $unknown[0].Sha256 -ne $p.sha256 -or $unknown[0].Size -ne $p.size -or $unknown[0].Message){throw 'Exact upload/outbox match required'}
  $retained=@();$index=0
  foreach($a in $answers){
   if($null -ne $a){
    foreach($file in @($a.Files|Where-Object {$null -eq $_.Message -and $null -eq $_.Failure})){$retained+=@{answerIndex=$index;file=$file}}
    $a.Files=@($a.Files|Where-Object {$null -ne $_.Message -or $null -ne $_.Failure})
   };$index++
  }
  if(-not $retained.Count){throw 'Historical files must be retained'}
  $b.held=$false;$b.busy=$false;$b.turn=$null;$b.status='Ready';$b.nativeStatus='Ready'
  $envelope=@{binding=$binding;bubble=$b}|ConvertTo-Json -Depth 100 -Compress
  $validation=($envelope|& "$root\bin\KhadangRouter.exe" --validate-outbox) -join "`n"
  if($LASTEXITCODE){throw 'Recovered historical outbox invalid'}
  $v=$validation|ConvertFrom-Json;if(-not $v.valid -or $v.uncertain){throw 'Other uncertainty remains'}
  Save "$archive\original-bubble.json" ($raw|ConvertFrom-Json)
  $digest=[BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($effect[0]))).Replace('-','').ToLowerInvariant()
  $quarantine=@{schema='ccrelay.owner_output_quarantine.v1';operation=$op;chat=$binding.Chat;topic=$binding.Topic;workspace=$binding.Workspace;payloadSha256=$digest;action='retain-no-resend';file=$unknown[0];reason='Owner recovery: historical upload timed out; never replay';at=[DateTimeOffset]::UtcNow.ToString('o')}
  $retainedState=@{schema='ccrelay.owner_retained_attachments.v1';binding=$binding;files=$retained;automaticSend=$false;reason='Historical attachments parked during owner-requested recovery; files and original receipts retained';at=[DateTimeOffset]::UtcNow.ToString('o')}
  Save "$archive\quarantined-upload.json" $quarantine;Save "$archive\attachments.json" $retainedState
  $db.Read('BEGIN IMMEDIATE')|Out-Null
  try{
   $db.Read("INSERT INTO meta VALUES('owner-output-quarantine/$op',CAST(X'$(Hex $quarantine)' AS TEXT))")|Out-Null
   $db.Read("INSERT INTO meta VALUES('owner-retained-attachments/$pin/20261015',CAST(X'$(Hex $retainedState)' AS TEXT))")|Out-Null
   $db.Read("UPDATE meta SET value=CAST(X'$(Hex $b)' AS TEXT) WHERE key='$key'")|Out-Null
   $db.Read('COMMIT')|Out-Null
  }catch{$db.Read('ROLLBACK')|Out-Null;throw}
  Save "$archive\recovered.json" @{pendingAnswers=$v.pendingAnswers;retainedHistoricalFiles=$retained.Count;inputsReplayed=0;unknownUploadsReplayed=0}
 }finally{if($db){$db.Dispose()};$lease.Dispose()}
 if((Unknown) -cne $before.unknown -or (Bindings) -cne $before.bindings -or (HostIdentity) -cne $before.host){throw 'Unrelated custody changed'}
}finally{
 if((Get-Service KhadangRouter).Status -eq 'Stopped'){Start-Service KhadangRouter}
 foreach($name in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$enabled=if($name -like '*Startup'){$before.startup}else{$before.watchdog};if($enabled){(ExactTask $name).Enabled=$true}}
}
[IO.File]::ReadAllText("$archive\recovered.json")
