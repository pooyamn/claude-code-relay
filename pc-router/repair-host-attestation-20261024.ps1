param([ValidateSet('repair','verify')][string]$Phase='repair')
# Correct the stale installation attestation against an already protected,
# accepted release. No host restart, native command, input replay or ACL bypass.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$root='C:\ProgramData\KhadangRouter';$hostRoot='C:\ProgramData\KhadangClaudeHost'
$release="$root\repair-host-attestation-20261024";$accepted="$root\release-reconciliation-20261024-v2"
$code='32E50A1F4199BF281BDE3BC71B0ACB94731DF0B9BC6981CD82002EF863261C25'
$old='BA71E22CB633BCC4070EB832EC8E846F78A573F0D65FD164DBC1A6E86F9D00A2'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed PC administrator required'}
$helper='C:\Users\pou\AppData\Local\Temp\deploy-switch-isolation-20261014.ps1'
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helper changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','Save','LoadSql','Bindings','HostIdentity','ExactTask')){$d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true);if(-not $d){throw 'Reviewed helper missing'};. ([ScriptBlock]::Create($d.Extent.Text))}
LoadSql 'C:\ProgramData\OracovaNativeRemote\inspect-state.ps1' 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$script:taskScheduler=New-Object -ComObject Schedule.Service;$script:taskScheduler.Connect()
function CheckHost{
 $h=Get-CimInstance Win32_Service -Filter "Name='KhadangClaudeHost'"
 if($h.State -ne 'Running' -or $h.StartName -ne 'LocalSystem' -or $h.PathName -cne ('"'+$hostRoot+'\bin\KhadangRouter.exe" --claude-host-service')){throw 'Exact running independent host required'}
 if((Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne '2FF3072D7599A11A76ACE6CCAD23184AE85C207EAEE63B906BC56804DD58B7F5' -or (Get-FileHash "$root\config.json").Hash -ne '6271B521E9C069618384FD6632088C7FAF06FDD1CBCB8A7CBCDC36E77215192C'){throw 'Reviewed live router/policy required'}
 if((Get-FileHash "$hostRoot\bin\KhadangRouter.dll").Hash -ne $code -or (Get-FileHash "$accepted\candidate\KhadangRouter.dll").Hash -ne $code){throw 'Known accepted host release required'}
 $proof=[IO.File]::ReadAllText("$accepted\verified.json")|ConvertFrom-Json
 if($proof.code -ne $code -or -not $proof.unknownReceiptsPreserved){throw 'Retained accepted release proof required'}
 $files=@(Get-ChildItem -LiteralPath "$accepted\candidate" -File)
 if(@(Get-ChildItem -LiteralPath "$hostRoot\bin").Count -ne $files.Count){throw 'Host release file set differs'}
 foreach($f in $files){$p=Join-Path "$hostRoot\bin" $f.Name;if((Get-Item -LiteralPath $p).Attributes -band [IO.FileAttributes]::ReparsePoint -or (Get-FileHash -LiteralPath $p).Hash -ne (Get-FileHash -LiteralPath $f.FullName).Hash){throw 'Host does not match accepted release'}}
 return $h
}
if($Phase -eq 'repair'){
 if(Test-Path $release){throw 'Existing evidence: inspect, never repeat'}
 $h=CheckHost
 $installed=[IO.File]::ReadAllText("$hostRoot\installed.json")|ConvertFrom-Json
 if($installed.dll -ne $old -or $installed.exe -ne '791A4EDAC3A49C47AF62E81724F61E306384177D6244372FF392C46CD3B5E121'){throw 'Exact diagnosed stale attestation required'}
 New-Item -ItemType Directory $release|Out-Null;Protect $release $true
 Save "$release\before.json" @{at=[DateTimeOffset]::UtcNow;hostPid=$h.ProcessId;hostIdentity=(HostIdentity);bindings=(Bindings);startupEnabled=(ExactTask 'Oracova-KhadangStartup').Enabled;watchdogEnabled=(ExactTask 'Oracova-KhadangWatchdog').Enabled}
 Copy-Item "$hostRoot\installed.json" "$release\previous-installed.json";Protect "$release\previous-installed.json"
 $installed.dll=$code;$installed.exe=(Get-FileHash "$hostRoot\bin\KhadangRouter.exe").Hash;$installed.generation='accepted-host-repair-20261024';$installed.at=[DateTimeOffset]::UtcNow.ToString('o')
 Save "$release\installed.json" $installed
 $tmp="$hostRoot\installed.json.attestation-repair";Copy-Item "$release\installed.json" $tmp;Protect $tmp
 [IO.File]::Replace($tmp,"$hostRoot\installed.json",[System.Management.Automation.Language.NullString]::Value)
 Save "$release\repaired.json" @{at=[DateTimeOffset]::UtcNow;hostRestarted=$false;nativeInput=0;sourceRelease=$accepted}
 # Exercise the actual SYSTEM startup supervisor, not direct Start-Service.
 $task=ExactTask 'Oracova-KhadangStartup'
 if(-not $task.Enabled){throw 'Existing startup task disabled; do not silently change scheduler'}
 if($task.State -ne 4){$null=$task.Run($null)}
 @{phase='attestation-corrected';normalStartupRequested=$true;hostRestarted=$false;inputReplay=0}|ConvertTo-Json -Compress;return
}
$b=[IO.File]::ReadAllText("$release\before.json")|ConvertFrom-Json
$h=CheckHost;$i=[IO.File]::ReadAllText("$hostRoot\installed.json")|ConvertFrom-Json
if($h.ProcessId -ne $b.hostPid -or (HostIdentity) -cne $b.hostIdentity -or (Bindings) -cne $b.bindings -or $i.dll -ne $code -or $i.exe -ne (Get-FileHash "$hostRoot\bin\KhadangRouter.exe").Hash){throw 'Independent custody/bindings/attestation changed'}
$end=[DateTimeOffset]::UtcNow.AddSeconds(50)
do{
 $s=[IO.File]::ReadAllText("$root\state\status.json")|ConvertFrom-Json
 $task=ExactTask 'Oracova-KhadangStartup'
 $ready=(Get-Service KhadangRouter).Status -eq 'Running' -and [DateTimeOffset]$s.at -ge [DateTimeOffset]::UtcNow.AddSeconds(-45) -and [DateTimeOffset]$s.lastPollAttempt -ge [DateTimeOffset]::UtcNow.AddSeconds(-60) -and $s.nativeTransportHealthy -and $s.backgroundHealthy -and $task.LastTaskResult -eq 0
 if($ready){break};Start-Sleep -Milliseconds 500
}while([DateTimeOffset]::UtcNow -lt $end)
if(-not $ready){throw 'Fresh normal-supervisor recovery not proven'}
$r=@{at=[DateTimeOffset]::UtcNow.ToString('o');normalStartupPassed=$true;hostPidPreserved=$true;bindingsPreserved=$true;poll=$s.lastPollAttempt;nativeLinuxPid=$s.nativeLinuxPid;held=@($s.nativeSessions|Where-Object held|ForEach-Object {$_.binding.Name});routes=@($s.nativeSessions|Select-Object binding,nativeConnected,held,ready,admission);inputReplay=0}
Save "$release\verified.json" $r;$r|ConvertTo-Json -Depth 7 -Compress
