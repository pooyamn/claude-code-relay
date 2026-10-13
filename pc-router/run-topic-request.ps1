param(
 [Parameter(Mandatory=$true)][ValidateLength(1,128)][string]$Name,
 [long]$SourceUpdate,
 [ValidatePattern('^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$')][string]$SourceThreadId='01a0facd-1bc0-7d23-95d6-c32fde0c62db',
 [ValidateSet('auto','codex','claude')][string]$Backend='auto',
 [string]$Workspace,
 [ValidateSet('fresh','existing')][string]$Mode='fresh',
 [ValidatePattern('^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$')][string]$ThreadId,
 [switch]$PreflightOnly
)
# Install a reviewed sealed package once. Every normal topic request is ONE
# invocation here: preflight, native allocation, creation, enrollment, catalog.
# No embedded password, new privilege mechanism, model work or automatic replay.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote';$package=$PSScriptRoot
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or $SourceUpdate -lt 0 -or $Name -match '[\x00-\x1f\x7f]'){throw 'Authenticated controller maintenance invocation required'}
if(-not $package.StartsWith($native+'\',[StringComparison]::OrdinalIgnoreCase) -or -not (Get-Acl $package).AreAccessRulesProtected -or (Get-Acl $package).GetOwner([Security.Principal.SecurityIdentifier]).Value -ne 'S-1-5-32-544'){throw 'Reviewed protected package required'}
$manifest=Get-Content "$package\package.json" -Raw -Encoding UTF8|ConvertFrom-Json
foreach($file in $manifest.files.PSObject.Properties){if($file.Name -notmatch '^[a-z0-9-]+\.ps1$' -or (Get-FileHash (Join-Path $package $file.Name)).Hash -ne $file.Value){throw 'Reviewed package hash mismatch'}}
$helper="$native\inspect-state.ps1"
if((Get-FileHash $helper).Hash -ne 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2'){throw 'Inspection helper changed'}
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$t,[ref]$e)
$def=$ast.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type'},$true)
if($e.Count -or -not $def){throw 'Inspection helper parse failed'};if(-not ('RouterReceipts' -as [type])){& ([ScriptBlock]::Create($def.Extent.Text))}
$sourceRows=[RouterReceipts]::Read("SELECT payload FROM bindings WHERE json_extract(payload,'$.ThreadId')='$SourceThreadId'")
if($sourceRows.Length -ne 1){throw 'Exact originating live binding required'};$source=$sourceRows[0][0]|ConvertFrom-Json
$p=Get-Content "$root\config.json" -Raw -Encoding UTF8|ConvertFrom-Json
function PublishCatalog {
 $generation=[Guid]::NewGuid().ToString('N');$catalog=Join-Path $native ('topic-catalog-'+$generation+'.json')
 $null=& powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$package\export-topic-catalog.ps1" -OutputPath $catalog
 if($LASTEXITCODE -ne 0){throw 'Token-free catalog export failed'}
 $public='C:\Users\pou\AppData\Local\Temp\pc-topic-catalog-'+$generation+'.json';Copy-Item $catalog $public
 $linux='/mnt/c/Users/pou/AppData/Local/Temp/pc-topic-catalog-'+$generation+'.json'
 & 'C:\Windows\System32\wsl.exe' -d Ubuntu-24.04 -u pou --exec cp $linux /Users/pouya/.config/ccrelay/pc-topics.json
 if($LASTEXITCODE -ne 0){throw 'Binding ready but catalog publication failed; no creation retry'}
}
if(-not $SourceUpdate){
 $literal=$Name.Replace("'","''")
 $recent=[RouterReceipts]::Read("SELECT id FROM updates WHERE json_extract(payload,'$.message.from.id')=$($p.OwnerId) AND json_extract(payload,'$.message.chat.id')=$($source.Chat) AND json_extract(payload,'$.message.message_thread_id')=$($source.Topic) AND instr(lower(json_extract(payload,'$.message.text')),lower('$literal'))>0 ORDER BY id DESC LIMIT 1")
 if($recent.Length -ne 1){throw 'Supply the original owner request update ID'};$SourceUpdate=[long]$recent[0][0]
}
$requestRows=[RouterReceipts]::Read("SELECT payload FROM updates WHERE id=$SourceUpdate")
if($requestRows.Length -ne 1){throw 'Original authenticated human request required'};$message=($requestRows[0][0]|ConvertFrom-Json).message
if($message.from.id -ne $p.OwnerId -or $message.from.is_bot -or $message.chat.id -ne $source.Chat -or $message.message_thread_id -ne $source.Topic -or $message.forward_origin -or $message.sender_chat -or $message.via_bot -or $message.text -notmatch [regex]::Escape($Name)){throw 'Owner/source/request mismatch; agent assertions are not approval'}
if($Backend -eq 'auto'){$Backend=$source.Backend}
if(-not $Workspace){$slug=$Name.ToLowerInvariant() -replace '[^a-z0-9-]','-';$slug=$slug.Trim('-');if(-not $slug){throw 'Supply an explicit project folder for this name'};$Workspace='/Users/pouya/.openclaw/workspace/'+$slug}
if($Workspace -notmatch '^/Users/pouya/\.openclaw/workspace/[A-Za-z0-9_./-]+$' -or $Workspace -match '(^|/)\.\.?(/|$)'){throw 'Literal already-admitted Linux project folder required'}
if($Mode -eq 'existing' -and ($Backend -ne 'codex' -or -not $ThreadId)){throw 'Existing mode currently requires an exact Codex ID; existing Claude uses the enrollment reference'}
$matches=[RouterReceipts]::Read("SELECT payload FROM bindings WHERE chat=$($source.Chat)")|ForEach-Object {$_[0]|ConvertFrom-Json}|Where-Object {$_.Name -ceq $Name}
if(@($matches).Count){
 if(@($matches).Count -ne 1 -or $matches.Workspace -cne $Workspace -or $matches.Backend -ne $Backend -or ($Mode -eq 'existing' -and $matches.ThreadId -ne $ThreadId)){throw 'Existing topic differs; never repoint or duplicate silently'}
 $status=Get-Content "$root\state\status.json" -Raw -Encoding UTF8|ConvertFrom-Json
 $route=@($status.nativeSessions|Where-Object {$_.binding.ThreadId -eq $matches.ThreadId})
 if((Get-Service KhadangRouter).Status -ne 'Running' -or [DateTimeOffset]$status.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-2) -or $route.Count -ne 1 -or $route[0].held){throw 'Existing binding requires live reconciliation'}
 PublishCatalog
 @{phase='ready-existing';binding=$matches;link=('https://t.me/c/'+([string]$matches.Chat).Substring(4)+'/'+$matches.Topic);created=$false;modelPromptSent=$false}|ConvertTo-Json -Depth 8 -Compress;return
}
# Fail BEFORE allocation/creation if a restart cannot safely load the ledger.
if([RouterReceipts]::Read("SELECT key FROM meta WHERE key LIKE 'bubble/%' AND json_array_length(value,'$.pendingAnswers')>256").Length){throw 'Oversized pending answer outbox; no topic/session created'}
if([RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('received','dispatching','unknown')").Length){throw 'Unsettled incoming delivery; no topic/session created'}
$s=Get-Content "$root\state\status.json" -Raw -Encoding UTF8|ConvertFrom-Json
if((Get-Service KhadangRouter).Status -ne 'Running' -or [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-2)){throw 'Fresh running router required'}
foreach($row in [RouterReceipts]::Read("SELECT kind,payload,status FROM operations WHERE status IN ('attempting','unknown')")){
 if($row[0] -eq 'telegram/editMessageText'){continue}
 if($row[2] -ne 'unknown' -or $row[0] -notin @('telegram/sendMessage','telegram/sendRichMessage','telegram/sendPhoto','telegram/sendDocument')){throw 'Uncertain native/unclassified effect; no topic/session created'}
 $effect=$row[1]|ConvertFrom-Json
 if($effect.chat_id -ge 0 -or $effect.message_thread_id -le 0 -or [RouterReceipts]::Read("SELECT payload FROM bindings WHERE chat=$([long]$effect.chat_id) AND topic=$([int]$effect.message_thread_id)").Length -ne 1){throw 'Unscoped output uncertainty; no topic/session created'}
}
foreach($row in [RouterReceipts]::Read("SELECT key,value FROM meta WHERE key LIKE 'bubble/%' AND json_extract(value,'$.busy')=1")){
 $bubble=$row[1]|ConvertFrom-Json;$id=$row[0].Substring(7)
 $routeRows=[RouterReceipts]::Read("SELECT payload FROM bindings WHERE json_extract(payload,'$.ThreadId')='$id'")
 if($routeRows.Length -ne 1){throw 'Unbound active session; no effects'};$active=$routeRows[0][0]|ConvertFrom-Json
 if($active.Backend -ne 'codex' -or $active.Runtime -ne 'linux' -or (-not $bubble.held -and -not $bubble.turn)){throw 'Router-owned native work must be quiescent; no effects'}
}
if($Backend -eq 'claude' -and $s.unknown){throw 'Claude enrollment requires its existing clean-state gate; no topic/session created'}
$code=(Get-FileHash "$root\bin\KhadangRouter.dll").Hash;$policy=(Get-FileHash "$root\config.json").Hash
$proof=Get-Content "$root\state\probe.json" -Raw -Encoding UTF8|ConvertFrom-Json
if(-not $proof.verified -or $proof.routerSha256 -ne $code -or $proof.policySha256 -ne $policy){throw 'Matching native proof required before effects'}
function InvokeHelper([string]$File,[hashtable]$Arguments){
 $output=@(& powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $package $File) @Arguments)
 if($LASTEXITCODE -ne 0){throw ('Workflow stopped at '+$File+'; inspect retained receipts, never replay unknown effects')}
 return $output
}
# Check rights before allocating a native session. No competing Telegram poller.
$preflightId=$(if($ThreadId){$ThreadId}else{[Guid]::NewGuid().ToString()})
$null=InvokeHelper 'create-codex-topic.ps1' @{ThreadId=$preflightId;Name=$Name;ChatId=$source.Chat;PreflightOnly=$true}
if($PreflightOnly){@{phase='preflight-ready';name=$Name;backend=$Backend;mode=$Mode;workspace=$Workspace;chat=$source.Chat;effects=0}|ConvertTo-Json -Compress;return}
$requestDir=Join-Path $native ('topic-request-'+$SourceUpdate)
if(Test-Path $requestDir){throw 'Existing request plan requires reconciliation; no automatic allocation or creation retry'}
New-Item -ItemType Directory $requestDir|Out-Null
$acl=Get-Acl $package;Set-Acl $requestDir $acl
$settings=@{name=$Name;backend=$Backend;workspace=$Workspace;mode=$Mode;sourceUpdate=$SourceUpdate;source=$source}
[IO.File]::WriteAllText("$requestDir\plan.json",($settings|ConvertTo-Json -Depth 10),[Text.UTF8Encoding]::new($false))
if($Backend -eq 'codex'){
 $receipt='/Users/pouya/.migration/topic-request-'+$SourceUpdate
 $wsl='C:\Windows\System32\wsl.exe'
 $null=& $wsl -d Ubuntu-24.04 -u pou --exec mkdir -m 700 -p $Workspace
 if($LASTEXITCODE -ne 0){throw 'Workspace preparation failed'}
 $null=& $wsl -d Ubuntu-24.04 -u pou --exec mkdir -m 700 $receipt
 if($LASTEXITCODE -ne 0){throw 'Native receipt already exists; reconcile without allocation retry'}
 $args=@('-d','Ubuntu-24.04','-u','pou','--exec','/usr/bin/python3','/Users/pouya/.openclaw/workspace/claude-code-relay/scripts/pc_create_fresh_codex.py','--receipt-directory',$receipt,'--workspace',$Workspace,'--name',$Name,'--chat',[string]$source.Chat,'--mode','new-topic','--source-update',[string]$SourceUpdate)
 if($Mode -eq 'existing'){$args+=@('--existing-thread',$ThreadId)}
 $raw=@(& $wsl @args);if($LASTEXITCODE -ne 0){throw 'Native allocation/read unconfirmed; retain request and do not retry'}
 $nativeResult=($raw -join "`n")|ConvertFrom-Json
 if(-not $nativeResult.complete -or $nativeResult.unknownEffects -ne 0 -or $nativeResult.modelsStarted -ne 0 -or $nativeResult.workspace -cne $Workspace){throw 'Native result differs'}
 $ThreadId=$nativeResult.thread
 [IO.File]::WriteAllText("$requestDir\native.json",($nativeResult|ConvertTo-Json -Depth 10),[Text.UTF8Encoding]::new($false))
}else{$ThreadId=[Guid]::NewGuid().ToString()}
[IO.File]::WriteAllText("$requestDir\allocated-thread.txt",$ThreadId,[Text.UTF8Encoding]::new($false))
$null=InvokeHelper 'create-codex-topic.ps1' @{ThreadId=$ThreadId;Name=$Name;ChatId=$source.Chat}
if($Backend -eq 'codex'){
 $null=InvokeHelper 'enroll-codex-topic-fast.ps1' @{ThreadId=$ThreadId;SourceThreadId=$SourceThreadId;Workspace=$Workspace;SourceUpdate=$SourceUpdate;ExpectedCode=$code;ExpectedPolicy=$policy}
}else{
 $settings=@{ThreadId=$ThreadId;SourceThreadId=$SourceThreadId;Workspace=$Workspace;ExpectedCode=$code;ExpectedPolicy=$policy}
 foreach($phase in @('fence','stage','probe','accept','activate','verify')){
  if($phase -eq 'accept'){
   $deadline=[DateTimeOffset]::UtcNow.AddSeconds(55)
   do{$proof=Get-Content "$root\state\probe.json" -Raw -Encoding UTF8|ConvertFrom-Json;if($proof.routerSha256 -eq $code -and $proof.policySha256 -ne $policy -and $proof.verified){break};Start-Sleep -Milliseconds 500}while([DateTimeOffset]::UtcNow -lt $deadline)
   if($proof.routerSha256 -ne $code -or $proof.policySha256 -eq $policy -or -not $proof.verified){throw 'Fresh probe not confirmed; preserve phased receipts'}
   Stop-Service KhadangRouter;(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(20))
  }
  if($phase -eq 'verify'){
   $deadline=[DateTimeOffset]::UtcNow.AddSeconds(55)
   do{$observed=Get-Content "$root\state\status.json" -Raw -Encoding UTF8|ConvertFrom-Json;if([DateTimeOffset]$observed.at -gt $activation -and @($observed.bindings|Where-Object ThreadId -eq $ThreadId).Count -eq 1){break};Start-Sleep -Milliseconds 500}while([DateTimeOffset]::UtcNow -lt $deadline)
  }
  if($phase -eq 'activate'){$activation=[DateTimeOffset]::UtcNow}
  $null=InvokeHelper 'enroll-fresh-claude-topic.ps1' ($settings+@{Phase=$phase})
 }
}
PublishCatalog
$live=Get-Content "$root\topic-enrollment-$ThreadId\live-verified.json" -Raw -Encoding UTF8|ConvertFrom-Json
$answer=@{phase='ready';binding=$live.binding;link=('https://t.me/c/'+([string]$live.binding.Chat).Substring(4)+'/'+$live.binding.Topic);modelPromptSent=$false;phoneRoundTripVerified=$live.phoneRoundTripVerified}
[IO.File]::WriteAllText("$requestDir\result.json",($answer|ConvertTo-Json -Depth 10),[Text.UTF8Encoding]::new($false));$answer|ConvertTo-Json -Depth 8 -Compress
