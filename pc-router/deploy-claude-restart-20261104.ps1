param([ValidateSet('prepare','stage','probe','activate','verify')][string]$Phase,[Parameter(Mandatory=$true)][string]$ManifestSha256)
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$hostRoot='C:\ProgramData\KhadangClaudeHost';$native='C:\ProgramData\OracovaNativeRemote';$temp='C:\Users\pou\AppData\Local\Temp'
$release=$root+'\release-claude-restart-20261104';$incoming=$temp+'\router-claude-restart-20261104'
$oldCode='0E219BC929A8DB6903DDC3F172BC2D14F22E710D7270D48EEB2E33668000E851';$oldHost='32E50A1F4199BF281BDE3BC71B0ACB94731DF0B9BC6981CD82002EF863261C25';$oldPolicy='A17182A3B0D654563CC7CA63AC344059C45D7E8BC086A39DBE14824EE958F05B'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$helper=$temp+'\deploy-switch-isolation-20261014.ps1'
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helpers changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Bindings','Unknown','HostIdentity','ExactTask')){
 $d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true);. ([scriptblock]::Create($d.Extent.Text))
}
LoadSql ($native+'\inspect-state.ps1') 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
function Status{[IO.File]::ReadAllText($root+'\state\status.json')|ConvertFrom-Json}
function Original{
 if((Get-FileHash ($root+'\bin\KhadangRouter.dll')).Hash -ne $oldCode -or (Get-FileHash ($hostRoot+'\bin\KhadangRouter.dll')).Hash -ne $oldHost -or
  (Get-FileHash ($root+'\config.json')).Hash -ne $oldPolicy){throw 'Reviewed original deployment changed'}
}
function RestoreSupervisors($b){foreach($n in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){(ExactTask $n).Enabled=[bool]$(if($n -like '*Startup'){$b.startup}else{$b.watchdog})}}
function StartObserver([bool]$Probe=$false){
 $mode=if($Probe){'--probe-service'}else{'--service'}
 $svc=Get-CimInstance Win32_Service -Filter "Name='KhadangRouter'"
 $r=Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{PathName=('"'+$root+'\bin\KhadangRouter.exe" '+$mode+' --config "'+$root+'\config.json"');StartMode='Manual'}
 if($r.ReturnValue){throw 'Service path update failed'};Start-Service KhadangRouter
}
function Stopped{
 if((Get-Service KhadangRouter).Status -ne 'Stopped' -or (ExactTask 'Oracova-KhadangStartup').Enabled -or (ExactTask 'Oracova-KhadangWatchdog').Enabled){throw 'Observer must be fenced'}
}
function CheckManifest($path){if((Get-FileHash $path).Hash -ne $ManifestSha256){throw 'Exact reviewed manifest required'};[IO.File]::ReadAllText($path)|ConvertFrom-Json}
if($Phase -eq 'prepare'){
 Original;if(Test-Path $release){throw 'Retained release exists: inspect, never repeat'}
 $m=CheckManifest ($temp+'\router-claude-restart-20261104.manifest.json')
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 Copy-Item ($temp+'\router-claude-restart-20261104.manifest.json') ($release+'\manifest.json');Protect ($release+'\manifest.json')
 New-Item -ItemType Directory ($release+'\candidate')|Out-Null;Protect ($release+'\candidate') $true
 foreach($f in $m.files){
  if($f.name -notmatch '^[A-Za-z0-9._-]+$' -or $f.sha256 -notmatch '^[A-Fa-f0-9]{64}$'){throw 'Invalid file entry'}
  $from=Join-Path $incoming $f.name;$to=Join-Path ($release+'\candidate') $f.name
  if((Get-FileHash $from).Hash -ne $f.sha256 -or (Get-Item $from).Length -ne $f.bytes){throw 'Candidate changed'}
  Copy-Item $from $to;Protect $to;if((Get-FileHash $to).Hash -ne $f.sha256){throw 'Sealed candidate differs'}
 }
 if((Get-FileHash ($temp+'\pc_claude_stdio-restart-20261104.py')).Hash -ne $m.connector){throw 'Reviewed connector changed'}
 Copy-Item ($temp+'\pc_claude_stdio-restart-20261104.py') ($release+'\pc_claude_stdio.py');Protect ($release+'\pc_claude_stdio.py')
 $tests=@{}
 foreach($suite in @('--self-test-claude-restart','--self-test-controller-handoff','--self-test-transport-health','--self-test-delivery','--self-test-startup-isolation','--self-test')){
  $out=(& ($release+'\candidate\KhadangRouter.exe') $suite)-join "`n"
  if($LASTEXITCODE -or $out -notmatch '(Passed \d+ .+ checks|All \d+ PC-router checks passed)'){throw "Sealed Windows suite failed: $suite $out"}
  $tests[$suite]=$out;Save ($release+'\tests.json') $tests
 }
 Save ($release+'\prepared.json') @{at=[DateTimeOffset]::UtcNow;code=$m.code;connector=$m.connector;manifest=$ManifestSha256}
 $tests|ConvertTo-Json -Compress;return
}
$m=CheckManifest ($release+'\manifest.json')
if($Phase -eq 'stage'){
 Original;$null=[IO.File]::ReadAllText($release+'\prepared.json');if(Test-Path ($release+'\before.json')){throw 'Stage already attempted'}
 $s=Status;$old=[IO.File]::ReadAllText($root+'\config.json')|ConvertFrom-Json
 if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or
  @($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude' -and ($_.nativeConnected -or $_.pid -ne 0 -or $_.busy)}).Count -or
  @($s.nativeSessions|Where-Object {$_.binding.Runtime -eq 'windows' -and $_.busy}).Count -or
  [RouterReceipts]::Read("SELECT id FROM updates WHERE status IN ('received','dispatching','unknown')").Length -or
  [RouterReceipts]::Read("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Length){throw 'Only offline Claude workers and settled mutations may be staged'}
 $live=(& C:\Windows\System32\wsl.exe -d Ubuntu-24.04 -u pou --exec /usr/bin/pgrep -x claude)-join ''
 if($LASTEXITCODE -ne 1 -or $live){throw 'A live Claude native process must not be stopped by deployment'}
 $installed=[IO.File]::ReadAllText($hostRoot+'\installed.json')|ConvertFrom-Json
 if($installed.dll -ne $oldHost -or $installed.exe -ne (Get-FileHash ($hostRoot+'\bin\KhadangRouter.exe')).Hash){throw 'Original host attestation mismatch'}
 $b=@{at=[DateTimeOffset]::UtcNow;startup=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdog=(ExactTask 'Oracova-KhadangWatchdog').Enabled;bindings=(Bindings);unknown=(Unknown);nativePid=$s.nativeLinuxPid;claudeBindings=@($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude'}|ForEach-Object {$_.binding})}
 Save ($release+'\before.json') $b
 try{
  foreach($n in @('Oracova-KhadangStartup','Oracova-KhadangWatchdog')){$t=ExactTask $n;$t.Enabled=$false;if($t.State -eq 4){$t.Stop(0)}}
  $svc=Get-Service KhadangRouter;$svc.Stop();$svc.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(45));Stopped
  if((Bindings) -cne $b.bindings -or (Unknown) -cne $b.unknown){throw 'Custody changed during stop'}
  $h=Get-Service KhadangClaudeHost;$h.Stop();$h.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30))
  Copy-Item ($root+'\config.json') ($release+'\previous-config.json');Protect ($release+'\previous-config.json')
  Copy-Item ($root+'\state\probe.json') ($release+'\previous-probe.json');Protect ($release+'\previous-probe.json')
  Copy-Item ($hostRoot+'\installed.json') ($release+'\previous-installed.json');Protect ($release+'\previous-installed.json')
  $connector=$old.LinuxClaude.PackageRoot+'\pc_claude_stdio.py'
  if((Get-FileHash $connector).Hash -ne $old.LinuxClaude.FileSha256.'pc_claude_stdio.py'){throw 'Original connector changed'}
  Copy-Item $connector ($release+'\previous-connector.py');Protect ($release+'\previous-connector.py')
  foreach($entry in @(@{root=$root;backup='previous-router-bin'},@{root=$hostRoot;backup='previous-host-bin'})){
   Move-Item ($entry.root+'\bin') ($release+'\'+$entry.backup)
   New-Item -ItemType Directory ($entry.root+'\bin')|Out-Null;Protect ($entry.root+'\bin') $true
   foreach($f in $m.files){Copy-Item (Join-Path ($release+'\candidate') $f.name) (Join-Path ($entry.root+'\bin') $f.name);Protect (Join-Path ($entry.root+'\bin') $f.name)}
  }
  $acl=Get-Acl $connector;$tmp=$connector+'.restart-reviewed';Copy-Item ($release+'\pc_claude_stdio.py') $tmp;Set-Acl $tmp $acl
  [IO.File]::Replace($tmp,$connector,[System.Management.Automation.Language.NullString]::Value)
  $old.LinuxClaude.FileSha256.'pc_claude_stdio.py'=$m.connector.ToLowerInvariant();Save ($root+'\config.json.reviewed') $old
  [IO.File]::Replace($root+'\config.json.reviewed',$root+'\config.json',[System.Management.Automation.Language.NullString]::Value)
  $installed.dll=$m.code;$installed.exe=(Get-FileHash ($hostRoot+'\bin\KhadangRouter.exe')).Hash;$installed.generation='claude-restart-20261104';$installed.at=[DateTimeOffset]::UtcNow.ToString('o')
  Save ($hostRoot+'\installed.json.reviewed') $installed
  [IO.File]::Replace($hostRoot+'\installed.json.reviewed',$hostRoot+'\installed.json',[System.Management.Automation.Language.NullString]::Value)
  Save ($release+'\staged.json') @{at=[DateTimeOffset]::UtcNow;code=$m.code;policy=(Get-FileHash ($root+'\config.json')).Hash;connector=$m.connector}
 }catch{RestoreSupervisors $b;throw}
 'STAGED; no live Claude worker stopped, no history/input changes';return
}
$b=[IO.File]::ReadAllText($release+'\before.json')|ConvertFrom-Json
$stage=[IO.File]::ReadAllText($release+'\staged.json')|ConvertFrom-Json
if((Get-FileHash ($root+'\bin\KhadangRouter.dll')).Hash -ne $m.code -or (Get-FileHash ($hostRoot+'\bin\KhadangRouter.dll')).Hash -ne $m.code -or
 (Get-FileHash ($root+'\config.json')).Hash -ne $stage.policy){throw 'Staged artifacts changed'}
if($Phase -eq 'probe'){
 Stopped;StartObserver $true;$end=[DateTimeOffset]::UtcNow.AddSeconds(55)
 do{$proof=[IO.File]::ReadAllText($root+'\state\probe.json')|ConvertFrom-Json;if($proof.routerSha256 -eq $m.code -and $proof.policySha256 -eq $stage.policy -and [DateTimeOffset]$proof.testedAt -gt [DateTimeOffset]$stage.at){break};Start-Sleep -Milliseconds 500}while([DateTimeOffset]::UtcNow -lt $end)
 $svc=Get-Service KhadangRouter;$svc.Stop();$svc.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));Stopped
 if(-not $proof.verified -or -not $proof.credentialAndCodeDenied -or -not $proof.nativeWindowsSandboxVerified -or -not $proof.nativeLinuxCommandOwnerVerified -or
  $proof.modelInference -or $proof.telegramPolling -or $proof.routerSha256 -ne $m.code -or $proof.policySha256 -ne $stage.policy -or [DateTimeOffset]$proof.testedAt -le [DateTimeOffset]$stage.at){throw 'Fresh SYSTEM denial/owner proof failed'}
 Save ($release+'\generic-proof.json') $proof
 $prior=[IO.File]::ReadAllText($release+'\previous-probe.json')|ConvertFrom-Json
 foreach($field in @('nativeLinuxClaudeLaunchVerified','nativeLinuxClaudeToolOwnerVerified','nativeLinuxClaudeContinuityVerified','nativeLinuxClaudeAcceptance')){if($prior.PSObject.Properties[$field]){$proof|Add-Member $field $prior.$field -Force}}
 $proof|Add-Member nativeLinuxClaudeAcceptanceReuse @{reason='Same native executable, account, exact IDs and least-owner launch contract; guarded restart/history-parser changes require fresh live verification';liveRecoveryClaimed=$false} -Force
 Save ($root+'\state\probe.json') $proof;Save ($release+'\accepted.json') @{at=[DateTimeOffset]::UtcNow;code=$m.code;policy=$stage.policy}
 'FRESH SECURITY PROBE PASSED';return
}
if($Phase -eq 'activate'){
 Stopped;$null=[IO.File]::ReadAllText($release+'\accepted.json')
 try{if((Get-Service KhadangClaudeHost).Status -ne 'Running'){Start-Service KhadangClaudeHost};StartObserver}finally{RestoreSupervisors $b}
 Save ($release+'\activated.json') @{at=[DateTimeOffset]::UtcNow};'ACTIVATED';return
}
$s=Status;$targets=@($s.nativeSessions|Where-Object {$_.binding.Backend -eq 'claude'})
if([DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddSeconds(-30) -or -not $s.backgroundHealthy -or -not $s.nativeTransportHealthy -or
 $targets.Count -ne @($b.claudeBindings).Count -or @($targets|Where-Object {$_.held -or -not $_.nativeConnected -or $_.pid -eq 0 -or $_.admission.Blocking -ne 0}).Count -or
 (Bindings) -cne $b.bindings -or (Unknown) -cne $b.unknown -or $s.nativeLinuxPid -ne $b.nativePid){throw 'Exact full recovery not yet verified; inspect, never clear/replay'}
$result=@{at=$s.at;code=$m.code;policy=$stage.policy;claude=$targets;bindingsPreserved=$true;unknownPreserved=$true;daemonPreserved=$true;inputReplay=0;wsLRestartTested=$false}
Save ($release+'\verified.json') $result;$result|ConvertTo-Json -Depth 9 -Compress
