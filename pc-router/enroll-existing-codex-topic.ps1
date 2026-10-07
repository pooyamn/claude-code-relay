param(
 [Parameter(Mandatory=$true)][ValidateSet('fence','stage','probe','accept','activate','verify')][string]$Phase,
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$')][string]$ThreadId,
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$')][string]$SourceThreadId,
 [Parameter(Mandatory=$true)][ValidatePattern('^/Users/pouya/\.openclaw/workspace/[A-Za-z0-9_./-]+$')][string]$Workspace,
 [Parameter(Mandatory=$true)][ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$ExpectedCode,
 [Parameter(Mandatory=$true)][ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$ExpectedPolicy,
 [Parameter(Mandatory=$true)][string]$NativeResult,
 [switch]$AllowOwnerActivity
)
# Reviewed elevated controller lane only. Reuse an exact durable topic result.
# No model prompt, token copy, daemon restart, repointing or recovery-hold repair.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$root='C:\ProgramData\KhadangRouter';$nativeRoot='C:\ProgramData\OracovaNativeRemote'
$release=Join-Path $root ('topic-enrollment-'+$ThreadId)
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or
 $ThreadId -eq $SourceThreadId -or $Workspace -match '(^|/)\.\.?(/|$)'){throw 'Literal fresh session and PC administrator required'}
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544');$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
function Protect([string]$Path,[bool]$Directory,[bool]$Readable=$false){
 if((Get-Item -LiteralPath $Path).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Literal artifact required'}
 $acl=$(if($Directory){[Security.AccessControl.DirectorySecurity]::new()}else{[Security.AccessControl.FileSecurity]::new()})
 $inherit=$(if($Directory){[Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'}else{[Security.AccessControl.InheritanceFlags]::None})
 $acl.SetOwner($admin);$acl.SetAccessRuleProtection($true,$false)
 foreach($sid in @($admin,$system)){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl',$inherit,'None','Allow'))}
 if($Readable){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($owner,'ReadAndExecute',$inherit,'None','Allow'))};Set-Acl -LiteralPath $Path -AclObject $acl
}
function SaveNew([string]$Path,$Value){
 $body=[Text.Encoding]::UTF8.GetBytes(($Value|ConvertTo-Json -Depth 100 -Compress))
 $f=[IO.File]::Open($Path,'CreateNew','Write','None');try{$f.Write($body,0,$body.Length);$f.Flush($true)}finally{$f.Dispose()}
 Protect $Path $false
}
function ReadState {
 $helper="$nativeRoot\inspect-state.ps1"
 if((Get-FileHash $helper).Hash -ne 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2'){throw 'Read-only inspection helper changed'}
 $raw=@(& powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $helper)
 if($LASTEXITCODE -ne 0){throw 'State inspection failed'};return (($raw -join "`n")|ConvertFrom-Json)
}
function Stopped {
 if((Get-Service KhadangRouter).Status.ToString() -ne 'Stopped' -or (Get-ScheduledTask Oracova-KhadangStartup).State.ToString() -ne 'Disabled'){throw 'Stopped router and fenced watchdog required'}
}
function Safe($s){
 if($s.status.unknown -or @($s.status.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Connected native sessions and no uncertain input required'}
 foreach($m in @($s.metadata|Where-Object key -like 'bubble/*')){
  $b=$m.value;$route=@($s.bindings|Where-Object ThreadId -eq $m.key.Substring(7))
  if($b.sendUnknown -or @($b.pendingResponses).Count -or @($b.pendingAnswers).Count){throw 'Uncertain or pending response; preserve'}
  # Prior owner model switches retain their old idle bubble receipts. They
  # are not live routes; preserve them, rather than treating them as new work.
  if($route.Count -eq 0 -and -not $b.busy -and -not $b.held -and -not $b.turn){continue}
  if($route.Count -ne 1){throw 'Unbound active/held bubble; reconcile before enrollment'}
  if($b.busy -and ($route[0].Runtime -ne 'linux' -or $route[0].Backend -ne 'codex' -or $b.held -or -not $b.turn)){throw 'Router-owned native work must be idle; independent Codex needs exact turn'}
 }
}
if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $ExpectedCode){throw 'Reviewed router code changed'}
if($Phase -eq 'fence'){
 if((Get-FileHash "$root\config.json").Hash -ne $ExpectedPolicy -or (Get-Service KhadangRouter).Status.ToString() -ne 'Running' -or (Test-Path $release)){throw 'Unchanged live policy and fresh enrollment required'}
 $s=ReadState;Safe $s
 if([DateTimeOffset]$s.status.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-2)){throw 'Stale live status'}
 $source=@($s.bindings|Where-Object ThreadId -eq $SourceThreadId)
 $resultItem=Get-Item -LiteralPath $NativeResult;$resultAcl=Get-Acl -LiteralPath $NativeResult
 if(-not $NativeResult.StartsWith($nativeRoot+'\',[StringComparison]::OrdinalIgnoreCase) -or
  $resultItem.Attributes -band [IO.FileAttributes]::ReparsePoint -or -not $resultAcl.AreAccessRulesProtected -or
  $resultAcl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $admin.Value){throw 'Sealed native receipt required'}
 $created=Get-Content -LiteralPath $NativeResult -Raw -Encoding UTF8|ConvertFrom-Json
 if($source.Count -ne 1 -or $source[0].Backend -ne 'codex' -or $source[0].Runtime -ne 'linux' -or
  $created.phase -ne 'native-session-ready-existing-topic' -or $created.thread -ne $ThreadId -or $created.workspace -cne $Workspace -or
  -not $created.complete -or -not $created.checkpointPersisted -or $created.modelsStarted -ne 0 -or $created.unknownEffects -ne 0 -or
  $created.nativeOwnerUid -ne 1000 -or $created.backend -ne 'codex' -or $created.runtime -ne 'linux' -or
  $created.approvalPolicy -ne 'never' -or $created.permissions -ne ':danger-full-access' -or
  @($s.bindings|Where-Object {$_.ThreadId -eq $ThreadId -or $_.Chat -eq $created.chat -and $_.Topic -eq $created.topic}).Count){throw 'Same-forum source and unbound exact creation result required'}
 $p=Get-Content "$root\config.json" -Raw -Encoding UTF8|ConvertFrom-Json
 if($p.OwnerId -ne 110123423 -or $p.OwnerSid -ne $owner.Value -or $p.BotUsername -ne 'TheKhadangBot' -or -not $p.OwnerFullAccess -or -not $p.LinuxClaude.GuardedRecovery){throw 'Existing owner/router runtime required'}
 $receiptHelper="$nativeRoot\inspect-state.ps1"
 $t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($receiptHelper,[ref]$t,[ref]$e)
 $def=$a.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type' -and $n.Extent.Text -like '*class RouterReceipts*'},$true)
 if($e.Count -or -not $def){throw 'Protected read-only receipt helper missing'}
 if(-not ('RouterReceipts' -as [type])){& ([ScriptBlock]::Create($def.Extent.Text))}
 $rows=[RouterReceipts]::Read("SELECT payload FROM updates WHERE id=$([long]$created.sourceUpdate)")
 if($rows.Length -ne 1){throw 'Existing topic creation receipt missing'}
 $creation=$rows[0][0]|ConvertFrom-Json;$message=$creation.message
 if($message.from.id -ne $p.OwnerId -or $message.from.is_bot -ne $false -or $message.chat.id -ne $created.chat -or
  -not $message.chat.is_forum -or $message.message_thread_id -ne $created.topic -or
  $message.forum_topic_created.name -cne $created.name -or $message.forward_origin -or $message.sender_chat -or $message.via_bot){throw 'Exact owner-created existing topic required'}
 foreach($file in $p.LinuxClaude.FileSha256.PSObject.Properties){if((Get-FileHash (Join-Path $p.LinuxClaude.PackageRoot $file.Name)).Hash -ne $file.Value){throw 'Native connector changed'}}
 $binding=[ordered]@{Chat=$created.chat;Topic=$created.topic;Name=$created.name;Workspace=$Workspace;ThreadId=$ThreadId;Backend='codex';Runtime='linux'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 SaveNew "$release\plan.json" @{binding=$binding;source=$source[0];code=$ExpectedCode;policy=$ExpectedPolicy;count=@($s.bindings).Count;nativeLinuxPid=$s.status.nativeLinuxPid;package=$p.LinuxClaude.PackageRoot;
  inputs=@($s.receipts|Where-Object kind -in @('native/turn/start','native/turn/steer','claude/user/send-now','claude/control/answer'));at=[DateTimeOffset]::UtcNow.ToString('o')}
 SaveNew "$release\existing-topic-receipt.json" $creation
 SaveNew "$release\native-session-receipt.json" $created
 SaveNew "$release\previous-watchdog.json" @{enabled=((Get-ScheduledTask Oracova-KhadangStartup).State.ToString() -ne 'Disabled')}
 Copy-Item "$root\config.json" "$release\previous-config.json";Copy-Item "$root\state\probe.json" "$release\previous-probe.json"
 SaveNew "$release\previous-service.json" (Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"|Select-Object PathName,StartMode)
 SaveNew "$release\previous-bindings.json" $s.bindings
 [IO.File]::WriteAllText("$release\startup-before.xml",(Export-ScheduledTask Oracova-KhadangStartup),[Text.UTF8Encoding]::new($false))
 Disable-ScheduledTask Oracova-KhadangStartup|Out-Null;Stop-ScheduledTask Oracova-KhadangStartup
 try{Stop-Service KhadangRouter}catch{(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(20))}
 (Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(20));Stopped
 @{phase='fenced';daemonRestarted=$false}|ConvertTo-Json -Compress;return
}
$plan=Get-Content "$release\plan.json" -Raw|ConvertFrom-Json;$binding=$plan.binding
if($binding.ThreadId -ne $ThreadId -or $binding.Workspace -cne $Workspace -or $plan.source.ThreadId -ne $SourceThreadId -or
 $plan.code -ne $ExpectedCode -or $plan.policy -ne $ExpectedPolicy){throw 'Frozen enrollment plan differs'}
if($Phase -eq 'stage'){
 Stopped
 if((Get-FileHash "$root\config.json").Hash -ne $ExpectedPolicy -or (Test-Path "$release\staged.json")){throw 'Staging already attempted or policy changed; inspect'}
 $helper="$nativeRoot\stage-dut-topic.ps1"
 if((Get-FileHash $helper).Hash -ne '0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF'){throw 'Protected SQLite helper changed'}
 $t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$t,[ref]$e)
 $def=$a.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type' -and $n.Extent.Text -like '*class PcbaRegistry*'},$true)
 if($e.Count -or -not $def){throw 'Protected SQLite helper missing'};& ([ScriptBlock]::Create($def.Extent.Text))
 $exclusive=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null;$tx=$false;$written=$false
 try{
  $db=[PcbaRegistry]::new()
  if([int]$db.Read("SELECT (SELECT COUNT(*) FROM operations WHERE status IN ('attempting','unknown') AND kind NOT LIKE 'telegram/edit%')+(SELECT COUNT(*) FROM updates WHERE status IN ('dispatching','unknown','received'))")[0][0]){throw 'Uncertain native/initial delivery; preserve'}
  $prior=$db.Read('SELECT payload FROM bindings ORDER BY chat,topic')
  if($prior.Length -ne $plan.count -or $db.Read("SELECT payload FROM bindings WHERE json_extract(payload,'$.ThreadId')='$ThreadId' OR (chat=$($binding.Chat) AND topic=$($binding.Topic))").Length){throw 'Registry changed or already enrolled'}
  $unrelated=$db.UnrelatedDigest();$null=$db.Read("VACUUM INTO '$release\previous-router.db'")
  Protect "$release\previous-router.db" $false
  $null=$db.Read('BEGIN IMMEDIATE');$tx=$true
  $json=$binding|ConvertTo-Json -Depth 8 -Compress;$hex=([BitConverter]::ToString([Text.Encoding]::UTF8.GetBytes($json))).Replace('-','')
  $null=$db.Read("INSERT INTO bindings(chat,topic,payload) VALUES($($binding.Chat),$($binding.Topic),CAST(X'$hex' AS TEXT))")
  $retained=$db.Read("SELECT payload FROM bindings WHERE NOT(chat=$($binding.Chat) AND topic=$($binding.Topic)) ORDER BY chat,topic")
  if($db.UnrelatedDigest() -ne $unrelated -or ($retained|ConvertTo-Json -Compress) -cne ($prior|ConvertTo-Json -Compress)){throw 'Existing registry or ledger changed'}
  $p=Get-Content "$release\previous-config.json" -Raw -Encoding UTF8|ConvertFrom-Json
  if($p.ChatId -ne $binding.Chat){
   $existing=@($p.AdditionalChats|Where-Object Chat -eq $binding.Chat)
   if($existing.Count -gt 1 -or $existing.Count -eq 1 -and -not $existing[0].IsForum){throw 'Conflicting forum admission'}
   if(-not $existing.Count){$p.AdditionalChats=@($p.AdditionalChats)+@([ordered]@{Chat=$binding.Chat;IsForum=$true})}
  }
  if((Get-FileHash "$root\config.json").Hash -ne $ExpectedPolicy){throw 'Live policy changed'}
  [IO.File]::WriteAllText("$root\config.json",($p|ConvertTo-Json -Depth 100),[Text.UTF8Encoding]::new($false));$written=$true
  $null=$db.Read('COMMIT');$tx=$false
  SaveNew "$release\staged.json" @{policy=(Get-FileHash "$root\config.json").Hash;at=[DateTimeOffset]::UtcNow.ToString('o');existingPayloadsPreserved=$true;unrelatedLedgerSha256=$unrelated}
 }catch{if($tx){$null=$db.Read('ROLLBACK');if($written){Copy-Item "$release\previous-config.json" "$root\config.json"}};throw}finally{if($db){$db.Dispose()};$exclusive.Dispose()}
 @{phase='staged';modelPromptSent=$false}|ConvertTo-Json -Compress;return
}
$staged=Get-Content "$release\staged.json" -Raw|ConvertFrom-Json
if((Get-FileHash "$root\config.json").Hash -ne $staged.policy){throw 'Staged policy changed'}
if($Phase -eq 'probe'){
 Stopped;$svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $path='"'+$root+'\bin\KhadangRouter.exe" --probe-service --config "'+$root+'\config.json"'
 $r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=$path;StartMode='Manual'}
 if($r.ReturnValue -ne 0 -or (Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'").PathName -cne $path){throw 'Probe service path readback failed'}
 Start-Service KhadangRouter;@{phase='probe-running';modelInference=$false;telegramPolling=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'accept'){
 Stopped;$proof=Get-Content "$root\state\probe.json" -Raw|ConvertFrom-Json;$old=Get-Content "$release\previous-probe.json" -Raw|ConvertFrom-Json
 $previous=Get-Content "$release\previous-config.json" -Raw|ConvertFrom-Json;$current=Get-Content "$root\config.json" -Raw|ConvertFrom-Json
 foreach($field in @('LinuxClaude','LinuxCodex','OwnerFullAccess','OwnerSid','CodexExecutable','CodexSha256','LinuxWorkspaceRoot')){
  if(($previous.$field|ConvertTo-Json -Depth 100 -Compress) -cne ($current.$field|ConvertTo-Json -Depth 100 -Compress)){throw 'Native components changed; prior Claude acceptance cannot be reused'}
 }
 foreach($file in $current.LinuxClaude.FileSha256.PSObject.Properties){if((Get-FileHash (Join-Path $current.LinuxClaude.PackageRoot $file.Name)).Hash -ne $file.Value){throw 'Native connector changed'}}
 if($proof.policySha256 -ne $staged.policy -or $proof.routerSha256 -ne $ExpectedCode -or -not $proof.verified -or -not $proof.credentialAndCodeDenied -or
  -not $proof.nativeWindowsSandboxVerified -or -not $proof.nativeLinuxCodexVerified -or -not $proof.nativeLinuxCommandOwnerVerified -or
  $proof.nativeOwnerSid -ne $owner.Value -or $proof.modelInference -or $proof.telegramPolling -or [DateTimeOffset]$proof.testedAt -le [DateTimeOffset]$staged.at -or
  $old.policySha256 -ne $ExpectedPolicy -or $old.routerSha256 -ne $ExpectedCode -or -not $old.nativeLinuxClaudeLaunchVerified -or -not $old.nativeLinuxClaudeToolOwnerVerified -or -not $old.nativeLinuxClaudeContinuityVerified){throw 'Fresh SYSTEM native proof required'}
 SaveNew "$release\generic-proof.json" $proof
 $proof.nativeLinuxClaudeLaunchVerified=$true;$proof.nativeLinuxClaudeToolOwnerVerified=$true;$proof.nativeLinuxClaudeContinuityVerified=$true
 if($old.nativeLinuxClaudeAcceptance){$proof|Add-Member nativeLinuxClaudeAcceptance $old.nativeLinuxClaudeAcceptance -Force}
 $proof|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Native code, connector, checkpoints and permissions unchanged; admitted one owner-created forum and fresh Codex binding';modelsRerun=$false;liveExactInitializationRequired=$true;at=[DateTimeOffset]::UtcNow.ToString('o')} -Force
 [IO.File]::WriteAllText("$root\state\probe.json",($proof|ConvertTo-Json -Depth 100),[Text.UTF8Encoding]::new($false))
 SaveNew "$release\accepted.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');policy=$staged.policy}
 @{phase='accepted-not-live'}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'activate'){
 Stopped;if(-not (Test-Path "$release\accepted.json")){throw 'Acceptance required'}
 $saved=Get-Content "$release\previous-service.json" -Raw|ConvertFrom-Json
 $r=Invoke-CimMethod -InputObject (Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'") -MethodName Change -Arguments @{PathName=$saved.PathName;StartMode=$(if($saved.StartMode -eq 'Auto'){'Automatic'}else{'Manual'})}
 if($r.ReturnValue -ne 0){throw 'Normal service restore failed'};Start-Service KhadangRouter
 @{phase='activation-started';sharedDaemonRestarted=$false;modelPromptSent=$false}|ConvertTo-Json -Compress;return
}
$s=ReadState
if($s.service -ne 'Running' -or [DateTimeOffset]$s.status.at -le [DateTimeOffset]$staged.at -or $s.status.unknown -or
 @($s.bindings).Count -ne ($plan.count+1) -or @($s.status.nativeSessions).Count -ne ($plan.count+1) -or $s.status.nativeLinuxPid -ne $plan.nativeLinuxPid){throw 'Fresh full registry and unchanged shared daemon required'}
$oldBindings=Get-Content "$release\previous-bindings.json" -Raw -Encoding UTF8|ConvertFrom-Json
# Historical payloads may omit Binding's native Windows defaults. Preserve
# those bytes in staging; normalize only this read-only semantic comparison.
foreach($b in (@($oldBindings)+@($s.bindings))){
 if(-not $b.PSObject.Properties['Backend']){$b|Add-Member Backend 'codex'}
 if(-not $b.PSObject.Properties['Runtime']){$b|Add-Member Runtime 'windows'}
}
$retained=@($s.bindings|Where-Object {-not ($_.Chat -eq $binding.Chat -and $_.Topic -eq $binding.Topic)})
if(($retained|Sort-Object Chat,Topic|ConvertTo-Json -Depth 20 -Compress) -cne ($oldBindings|Sort-Object Chat,Topic|ConvertTo-Json -Depth 20 -Compress)){throw 'Existing routes changed'}
$current=@($s.bindings|Where-Object {$_.Chat -eq $binding.Chat -and $_.Topic -eq $binding.Topic})
$new=@($s.status.nativeSessions|Where-Object {$_.binding.Chat -eq $binding.Chat -and $_.binding.Topic -eq $binding.Topic})
if($current.Count -ne 1 -or $new.Count -ne 1 -or $new[0].binding.Workspace -cne $Workspace){throw 'Exact new topic/workspace missing'}
$ownerChanged=$current[0].ThreadId -ne $ThreadId -or $current[0].Backend -ne 'codex'
if($ownerChanged){
 if(-not $AllowOwnerActivity){throw 'New topic changed after initialization; inspect owner activity, do not repoint it'}
 $helper="$nativeRoot\inspect-state.ps1"
 if((Get-FileHash $helper).Hash -ne 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2'){throw 'Read-only inspection helper changed'}
 $t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$t,[ref]$e)
 $def=$ast.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type'},$true)
 if($e.Count -or -not $def){throw 'Read-only SQLite definition missing'};& ([ScriptBlock]::Create($def.Extent.Text))
 $key="model-switch/$($binding.Chat)/$($binding.Topic)"
 $rows=[RouterReceipts]::Read("SELECT value FROM meta WHERE key='$key'")
 if($rows.Length -ne 1){throw 'Protected owner switch receipt missing'};$switch=$rows[0][0]|ConvertFrom-Json
 $commandHex=([BitConverter]::ToString([Text.Encoding]::UTF8.GetBytes('cc model '+$switch.requestedModel.ToLowerInvariant()))).Replace('-','')
 $commands=[RouterReceipts]::Read("SELECT id FROM updates WHERE status='control' AND json_extract(payload,'$.message.from.id')=110123423 AND json_extract(payload,'$.message.chat.id')=$($binding.Chat) AND json_extract(payload,'$.message.message_thread_id')=$($binding.Topic) AND lower(trim(json_extract(payload,'$.message.text')))=CAST(X'$commandHex' AS TEXT)")
 if($switch.phase -ne 'committed' -or $switch.source.ThreadId -ne $ThreadId -or $switch.target.ThreadId -ne $current[0].ThreadId -or
  $switch.target.Workspace -cne $Workspace -or $switch.target.Chat -ne $binding.Chat -or $switch.target.Topic -ne $binding.Topic -or $commands.Length -eq 0){throw 'Verified original-owner model switch required'}
}
$bubble=@($s.metadata|Where-Object key -eq "bubble/$($current[0].ThreadId)")
if($bubble.Count -ne 1 -or $bubble[0].value.held -or $bubble[0].value.sendUnknown -or
 (-not $AllowOwnerActivity -and ($bubble[0].value.busy -or $bubble[0].value.status -ne 'Ready')) -or
 ($current[0].Backend -eq 'claude' -and -not $new[0].claudeConnected) -or
 @($s.status.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Exact new topic is held or disconnected'}
$inputs=@($s.receipts|Where-Object kind -in @('native/turn/start','native/turn/steer','claude/user/send-now','claude/control/answer'))
$inputChanged=($inputs|ConvertTo-Json -Depth 8 -Compress) -cne ($plan.inputs|ConvertTo-Json -Depth 8 -Compress)
if($inputChanged -and -not $AllowOwnerActivity){throw 'Model input after activation; inspect owner activity without replay'}
if((Get-Content "$release\previous-watchdog.json" -Raw|ConvertFrom-Json).enabled){Enable-ScheduledTask Oracova-KhadangStartup|Out-Null}
SaveNew "$release\live-verified.json" @{binding=$current[0];initialBinding=$binding;existingRoutesPreserved=$true;sharedDaemonUnchanged=$true;
 ownerSwitchPreserved=$ownerChanged;nativeInputsChangedAfterActivation=$inputChanged;noInputSentByEnrollment=$true;startupRestored=$true;phoneRoundTripVerified=$false;at=[DateTimeOffset]::UtcNow.ToString('o')}
Get-Content "$release\live-verified.json" -Raw
