param([Parameter(Mandatory=$true)][ValidateSet('prepare','fence','stage','probe','accept','activate','verify')][string]$Phase,
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{32}$')][string]$Generation,
 [Parameter(Mandatory=$true)][ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$CodeSha256)
# Fixed October 9 router-only repair. Preserve the uncertain Display upload,
# native agents, every input receipt and Web/Display safety hold. No replay.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$nativeRoot='C:\ProgramData\OracovaNativeRemote';$hostRoot='C:\ProgramData\KhadangClaudeHost';$release="$root\release-$Generation"
$oldCode='C3B90DC278BA5ED47276A0B900E51DF97207B0AE02D1A5C9B822F5C551881BBE'
$hostCode='A2E3E8B6B0A71684A513D270E0F06D21F3A12560B99CA67AF9032F969BCFE369'
$policyHash='70AB674B2B297489C6C5D78965335B3E5B738E15C7F9FBCAB9D51D1A78D8A205'
$startupHash='2B4692B2F9DDD8B3F73A42186546D3B892326C32A319FF816586AC3ED94D5665'
$uploadId='a1271f1d97834aa2a9637031094c2198'
$normal='"'+$root+'\bin\KhadangRouter.exe" --service --config "'+$root+'\config.json"'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Exact PC administrator required'}
$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544');$system=[Security.Principal.SecurityIdentifier]::new('S-1-5-18');$owner=[Security.Principal.SecurityIdentifier]::new('S-1-5-21-71459778-1164188569-2276148161-1001')
$helper="$nativeRoot\migrate-lab-topics-65fc17bfcb9d47a190ab128b096bba5d.ps1"
foreach($entry in @(@($helper,'86F3D550CBA51D280CE2D6BCDCBD7A3C3B1B1CBB7435FE9BC54590C0F87E6513'),@("$nativeRoot\inspect-state.ps1",'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2'),@("$nativeRoot\stage-dut-topic.ps1",'0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF'))){if((Get-FileHash $entry[0]).Hash -ne $entry[1]){throw 'Protected helper changed'}}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save')){$def=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true);. ([ScriptBlock]::Create($def.Extent.Text))}
function Receipt([string]$Path,$Value){Save $Path $Value;Protect $Path $false}
function Sql([string]$File,[string]$Class){$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($File,[ref]$t,[ref]$e);$d=$a.Find({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type' -and $n.Extent.Text.Contains("class $Class")},$true);if($e.Count -or -not $d){throw 'Protected SQL helper syntax'};if(-not ($Class -as [type])){& ([ScriptBlock]::Create($d.Extent.Text))}}
Sql "$nativeRoot\inspect-state.ps1" 'RouterReceipts'
function Original {if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $oldCode -or (Get-FileHash "$root\config.json").Hash -ne $policyHash -or (Get-FileHash "$nativeRoot\router-startup.ps1").Hash -ne $startupHash){throw 'Production changed; preserve'}}
function Fenced {if((Get-Service KhadangRouter).Status.ToString() -ne 'Stopped' -or (Get-ScheduledTask Oracova-KhadangStartup).State.ToString() -ne 'Disabled'){throw 'Stopped fenced router required'}}
function HostIdentity {
 if((Get-Service KhadangClaudeHost).Status.ToString() -ne 'Running' -or (Get-FileHash "$hostRoot\bin\KhadangRouter.dll").Hash -ne $hostCode){throw 'Unchanged live Claude host required'}
 return @{host=(Get-Content "$hostRoot\host.json" -Raw -Encoding UTF8|ConvertFrom-Json);workers=@(Get-ChildItem "$hostRoot\state" -Directory|Sort-Object Name|ForEach-Object {Get-Content "$($_.FullName)\endpoint.json" -Raw -Encoding UTF8|ConvertFrom-Json})}
}
function Inputs {[RouterReceipts]::Read("SELECT id,kind,status FROM operations WHERE kind IN ('native/turn/start','native/turn/steer','claude/user/send-now','claude/control/answer') ORDER BY id")}
function ExpectedUncertainty {
 $unknown=[RouterReceipts]::Read("SELECT id,kind,payload FROM operations WHERE status='unknown' AND kind<>'telegram/editMessageText'")
 if($unknown.Length -ne 1 -or $unknown[0][0] -ne $uploadId -or $unknown[0][1] -ne 'telegram/sendDocument' -or [RouterReceipts]::Read("SELECT id FROM updates WHERE status='unknown'").Length){throw 'New uncertain operation; preserve'}
 $p=$unknown[0][2]|ConvertFrom-Json
 if($p.chat_id -ne -1004393585932 -or $p.message_thread_id -ne 2 -or $p.size -ne 20859985 -or $p.sha256 -ne 'ec8992778478575221b4955fb5b242d91712a2c455113e82f63682af3bccf38e'){throw 'Upload uncertainty identity changed'}
 return $unknown
}
function Fresh {
 $s=Get-Content "$root\state\status.json" -Raw -Encoding UTF8|ConvertFrom-Json
 if((Get-Service KhadangRouter).Status.ToString() -ne 'Running' -or $s.unknown -ne 1 -or @($s.bindings).Count -ne 16 -or $s.nativeLinuxPid -ne 479 -or [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-2) -or @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and -not $_.claudeConnected}).Count){throw 'Fresh exact routes/native generations required'}
 $null=ExpectedUncertainty;return $s
}
if($Phase -eq 'prepare'){
 Original;if(Test-Path "$release\prepared.json"){throw 'Already prepared'}
 if((Get-FileHash "$release\candidate\KhadangRouter.dll").Hash -ne $CodeSha256){throw 'Reviewed candidate required'}
 $output=(& "$release\candidate\KhadangRouter.exe" --self-test) -join "`n";if($LASTEXITCODE -ne 0){throw 'Full Windows regression failed; production untouched'}
 Receipt "$release\prepared.json" @{code=$CodeSha256;tests=$output;passed=$true;at=[DateTimeOffset]::UtcNow.ToString('o')}
 @{phase='prepared';tests=$output;productionChanged=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'fence'){
 Original;$p=Get-Content "$release\prepared.json" -Raw -Encoding UTF8|ConvertFrom-Json;if(-not $p.passed -or $p.code -ne $CodeSha256 -or (Test-Path "$release\before.json")){throw 'Fresh tested release required'};$null=Fresh
 Receipt "$release\before.json" @{bindings=[RouterReceipts]::Read('SELECT payload FROM bindings ORDER BY chat,topic');inputs=(Inputs);host=(HostIdentity);uncertainty=(ExpectedUncertainty);bubbles=[RouterReceipts]::Read("SELECT key,value FROM meta WHERE key LIKE 'bubble/%'");startup=(Get-ScheduledTask Oracova-KhadangStartup).State.ToString();at=[DateTimeOffset]::UtcNow.ToString('o')}
 Copy-Item "$root\state\probe.json" "$release\previous-probe.json";Copy-Item "$root\config.json" "$release\previous-config.json"
 Disable-ScheduledTask Oracova-KhadangStartup|Out-Null;Stop-ScheduledTask Oracova-KhadangStartup
 try{Stop-Service KhadangRouter}catch{};(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Fenced
 Receipt "$release\fenced.json" @{at=[DateTimeOffset]::UtcNow.ToString('o')};@{phase='fenced';nativeAgentsStopped=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'stage'){
 Fenced;Original;if(Test-Path "$release\staged.json"){throw 'Already staged'};$null=ExpectedUncertainty
 Sql "$nativeRoot\stage-dut-topic.ps1" 'PcbaRegistry'
 $exclusive=[IO.File]::Open("$root\state\exclusive.lock",'Open','ReadWrite','None');$db=$null
 try{
  $db=[PcbaRegistry]::new();if($db.Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText' UNION ALL SELECT CAST(id AS TEXT) FROM updates WHERE status IN ('dispatching','received','unknown')").Length){throw 'In-flight intake/effect; preserve'}
  # A failed pre-write guard may already have retained the preimage. Never
  # overwrite it; exact original code/holds below still gate a second attempt.
  if(-not (Test-Path "$release\previous-router.db")){$null=$db.Read("VACUUM INTO '$release\previous-router.db'");Protect "$release\previous-router.db" $false}
  $repairs=@(@('01a1122c-c62d-75f2-9b47-9ad9adcdf7d5',4901,759322941,199200674),@('01a104cc-9a63-7901-8897-abf8aff3dfb3',18,759322943,110123423))
  $db.Read('BEGIN IMMEDIATE')|Out-Null
  try{
   foreach($entry in $repairs){
    $pin=$entry[0];$topic=[int]$entry[1];$update=[long]$entry[2];$sender=[long]$entry[3];$key="bubble/$pin"
    $b=$db.Read("SELECT value FROM meta WHERE key='$key'")[0][0]|ConvertFrom-Json
    $binding=$db.Read("SELECT payload FROM bindings WHERE chat=-1004395661179 AND topic=$topic")[0][0]|ConvertFrom-Json
    $u=$db.Read("SELECT payload FROM updates WHERE id=$update AND status='held-no-replay'")
    if($u.Length -ne 1){throw 'Exact held owner input required'};$m=($u[0][0]|ConvertFrom-Json).message
    if($binding.ThreadId -ne $pin -or $binding.Backend -ne 'codex' -or $binding.Runtime -ne 'linux' -or $b.chat -ne -1004395661179 -or $b.topic -ne $topic -or
     -not $b.held -or $b.busy -or $b.turn -or $b.sendUnknown -or $b.status -ne ('Held '+[char]0x2014+" input $update not confirmed") -or
     $m.from.id -ne $sender -or $m.chat.id -ne -1004395661179 -or $m.message_thread_id -ne $topic -or -not $m.text -or
     @($b.pendingAnswers|ForEach-Object{$_.Parts+$_.Files}|Where-Object SendUnknown).Count -or @($b.finalAnswer.Parts+$b.finalAnswer.Files|Where-Object SendUnknown).Count -or
     @($b.pendingResponses|Where-Object {$_.sendUnknown -or @($_.finalAnswer.Parts+$_.finalAnswer.Files|Where-Object SendUnknown).Count}).Count){throw 'Exact unrelated quiescent false hold required'}
    # Native attempts store the submitted text. Its absence plus the exact
    # old-code global pre-dispatch guard proves this input was never sent.
    $hex=([BitConverter]::ToString([Text.Encoding]::UTF8.GetBytes($m.text))).Replace('-','')
    if($db.Read("SELECT id FROM operations WHERE kind IN ('native/turn/start','native/turn/steer') AND instr(payload,CAST(X'$hex' AS TEXT))>0").Length){throw 'Possible native dispatch; preserve hold'}
    $b.held=$false;$b.status='Ready';$b.tail+="`nUnrelated upload isolation fixed. Earlier input $update was never dispatched and remains retained; no automatic replay.`n"
    $hex=([BitConverter]::ToString([Text.Encoding]::UTF8.GetBytes(($b|ConvertTo-Json -Depth 100 -Compress)))).Replace('-','');$null=$db.Read("UPDATE meta SET value=CAST(X'$hex' AS TEXT) WHERE key='$key'")
   }
   $db.Read('COMMIT')|Out-Null
  }catch{$db.Read('ROLLBACK')|Out-Null;throw}
  Copy-Item "$root\bin" "$release\previous-bin" -Recurse
  Copy-Item "$release\candidate\*" "$root\bin" -Recurse -Force;Get-ChildItem "$root\bin" -Recurse -Force|ForEach-Object {Protect $_.FullName $_.PSIsContainer}
  Receipt "$release\staged.json" @{code=$CodeSha256;policy=(Get-FileHash "$root\config.json").Hash;at=[DateTimeOffset]::UtcNow.ToString('o');repairedFalseHolds=2;inputsReplayed=0}
 }finally{if($db){$db.Dispose()};$exclusive.Dispose()}
 @{phase='staged';falseHoldsCleared=2;uncertainUploadPreserved=$true;hostUpdated=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'probe'){
 Fenced;$svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" --probe-service --config "'+$root+'\config.json"');StartMode='Manual'};if($r.ReturnValue){throw 'Probe service path failed'}
 Start-Service KhadangRouter;@{phase='probe-running';modelInference=$false;telegramPolling=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'accept'){
 Fenced;$stage=Get-Content "$release\staged.json" -Raw -Encoding UTF8|ConvertFrom-Json;$p=Get-Content "$root\state\probe.json" -Raw -Encoding UTF8|ConvertFrom-Json;$old=Get-Content "$release\previous-probe.json" -Raw -Encoding UTF8|ConvertFrom-Json
 if($p.routerSha256 -ne $CodeSha256 -or $p.policySha256 -ne $policyHash -or -not $p.verified -or -not $p.credentialAndCodeDenied -or -not $p.aclProbeWithoutProviderSandbox -or -not $p.nativeWindowsSandboxVerified -or -not $p.nativeLinuxCodexVerified -or -not $p.nativeLinuxCommandOwnerVerified -or -not $p.nativePersistentClaudeHostAclDenied -or $p.modelInference -or $p.telegramPolling -or [DateTimeOffset]$p.testedAt -le [DateTimeOffset]$stage.at -or $old.routerSha256 -ne $oldCode -or $old.policySha256 -ne $policyHash -or -not $old.nativeLinuxClaudeContinuityVerified){throw 'Fresh OS proof and prior native acceptance required'}
 Copy-Item "$root\state\probe.json" "$release\generic-proof.json"
 foreach($field in @('nativeLinuxClaudeLaunchVerified','nativeLinuxClaudeToolOwnerVerified','nativeLinuxClaudeContinuityVerified','nativeLinuxClaudeAcceptance')){if($old.PSObject.Properties[$field]){$p|Add-Member $field $old.$field -Force}}
 $p|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Router-only output uncertainty isolation; protected config/connectors/independent host unchanged';priorCode=$oldCode;modelTestsRerun=$false} -Force
 Receipt "$root\state\probe.json" $p;Receipt "$release\accepted.json" @{code=$CodeSha256;policy=$policyHash;at=[DateTimeOffset]::UtcNow.ToString('o')};@{phase='accepted';hostUpdated=$false}|ConvertTo-Json -Compress;return
}
if($Phase -eq 'activate'){
 Fenced;if(-not (Test-Path "$release\accepted.json") -or (Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $CodeSha256 -or (Get-FileHash "$root\config.json").Hash -ne $policyHash){throw 'Exact accepted code/config required'};$null=HostIdentity
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'";$r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=$normal;StartMode='Manual'};if($r.ReturnValue){throw 'Normal service path failed'}
 Start-Service KhadangRouter;@{phase='activated';nativeInputsSent=0}|ConvertTo-Json -Compress;return
}
$s=Fresh;$before=Get-Content "$release\before.json" -Raw -Encoding UTF8|ConvertFrom-Json
if(((HostIdentity)|ConvertTo-Json -Depth 100 -Compress) -cne ($before.host|ConvertTo-Json -Depth 100 -Compress) -or
 ([RouterReceipts]::Read('SELECT payload FROM bindings ORDER BY chat,topic')|ConvertTo-Json -Compress) -cne ($before.bindings|ConvertTo-Json -Compress) -or
 ((Inputs)|ConvertTo-Json -Compress) -cne ($before.inputs|ConvertTo-Json -Compress) -or ((ExpectedUncertainty)|ConvertTo-Json -Compress) -cne ($before.uncertainty|ConvertTo-Json -Compress)){throw 'Native generation, registry, input or upload uncertainty changed'}
foreach($row in $before.bubbles){$b=$row[1]|ConvertFrom-Json;$now=[RouterReceipts]::Read("SELECT value FROM meta WHERE key='$($row[0])'")[0][0]|ConvertFrom-Json
 if($row[0] -in @('bubble/01a1122c-c62d-75f2-9b47-9ad9adcdf7d5','bubble/01a104cc-9a63-7901-8897-abf8aff3dfb3')){if($now.held){throw 'False hold remains'}}
 elseif($b.held -and -not $now.held){throw 'Unrelated safety hold changed'}
}
Receipt "$release\verified.json" @{at=[DateTimeOffset]::UtcNow.ToString('o');routes=16;nativeGenerationsUnchanged=$true;nativeInputsSent=0;uncertainUploadPreserved=$true;falseHoldsCleared=2;otherHoldsPreserved=$true}
if($before.startup -ne 'Disabled'){Enable-ScheduledTask Oracova-KhadangStartup|Out-Null;Start-ScheduledTask Oracova-KhadangStartup}
@{phase='verified';routes=16;falseHoldsCleared=2;uncertainUploadPreserved=$true;nativeInputsSent=0;startupRestored=$true}|ConvertTo-Json -Compress
