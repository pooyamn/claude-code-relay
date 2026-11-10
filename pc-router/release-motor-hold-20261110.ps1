$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';$PSDefaultParameterValues['Get-Content:Encoding']='UTF8'
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote';$pin='8cd2d34c-0805-4705-8197-d11de0728499'
$release=$root+'\recover-motor-native-20261110';$helper='C:\Users\pou\AppData\Local\Temp\deploy-switch-isolation-20261014.ps1'
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Helper changed'}
$a=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Hex','Bindings','Unknown','HostIdentity','ExactTask')){
 $d=$a.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true);. ([scriptblock]::Create($d.Extent.Text))
}
LoadSql ($native+'\inspect-state.ps1') 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
LoadSql ($native+'\stage-dut-topic.ps1') '0F0A0998EE4E9A1098262C62E26F28E631C8A11AF63895CDC99960173C506BDF' 'PcbaRegistry'
$s=Get-Content -Raw ($root+'\state\status.json')|ConvertFrom-Json
$motor=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $pin})
if((Test-Path ($release+'\hold-release.json')) -or -not (Test-Path ($release+'\staged.json')) -or $motor.Count -ne 1 -or
 -not $motor[0].nativeConnected -or $motor[0].pid -ne 66195 -or $motor[0].busy -or $motor[0].admission.Blocking -ne 0 -or
 $motor[0].status -ne 'Held — reconcile native receipts'){throw 'Only exact recovered idle worker hold may be released'}
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
$tasks=@('Oracova-KhadangStartup','Oracova-KhadangWatchdog')|ForEach-Object {$t=ExactTask $_;@{task=$t;enabled=$t.Enabled}}
$registry=Bindings;$uncertain=Unknown;$custody=HostIdentity
try{
 foreach($t in $tasks){$t.task.Enabled=$false;if($t.task.State -eq 4){$t.task.Stop(0)}}
 try{Stop-Service KhadangRouter}catch{};(Get-Service KhadangRouter).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30))
 $lease=[IO.File]::Open($root+'\state\exclusive.lock','Open','ReadWrite','None');$db=$null
 try{
  $db=[PcbaRegistry]::new();$saved=$db.Read("SELECT value FROM meta WHERE key='bubble/$pin'")[0][0];$bubble=$saved|ConvertFrom-Json
  if($db.Read("SELECT id FROM updates WHERE status IN ('received','dispatching','unknown')").Length -or $bubble.busy -or $bubble.sendUnknown -or
   $bubble.claudeDeliveryHold -or $bubble.claudeState -ne 'idle' -or @($bubble.pendingAnswers).Count -or @($bubble.pendingResponses).Count -or
   $bubble.status -ne 'Held — reconcile native receipts' -or (HostIdentity) -cne $custody){throw 'Live state changed; preserve hold'}
  Save ($release+'\previous-held-bubble.json') $bubble
  $bubble.held=$false;$bubble.status='Ready';$bubble.nativeStatus='Ready'
  $null=$db.Read("UPDATE meta SET value=CAST(X'$(Hex $bubble)' AS TEXT) WHERE key='bubble/$pin'")
  if((Bindings) -cne $registry -or (Unknown) -cne $uncertain){throw 'Unrelated receipts changed'}
  Save ($release+'\hold-release.json') @{session=$pin;pid=66195;ownerApproval='Pouya: Motorcontrol is down again';review=($release+'\audit.json');inputReplay=0;at=[DateTimeOffset]::UtcNow}
 }finally{if($db){$db.Dispose()};$lease.Dispose()}
}finally{
 if((Get-Service KhadangRouter).Status -eq 'Stopped'){Start-Service KhadangRouter}
 foreach($t in $tasks){$t.task.Enabled=[bool]$t.enabled}
}
'Exact recovered idle Motor hold released; retained output and uncertain operations preserved.'
