param([ValidateSet('Inspect','Apply')][string]$Mode='Inspect')
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'

function Read-VpnFailureActions([byte[]]$Bytes){
 if($null -eq $Bytes -or $Bytes.Length -lt 20){throw 'Missing recovery policy'}
 $count=[BitConverter]::ToUInt32($Bytes,12);$offset=[BitConverter]::ToUInt32($Bytes,16)
 if($count -lt 1 -or $count -gt 16 -or $offset -lt 20 -or [long]$offset+8*[long]$count -gt $Bytes.Length){throw 'Invalid recovery action bounds'}
 $actions=@(for($i=0;$i -lt $count;$i++){
  $type=[BitConverter]::ToUInt32($Bytes,$offset+8*$i)
  if($type -notin @(0,1)){throw 'Unexpected reboot or command recovery action; preserve for review'}
  [pscustomobject]@{type=$type;delayMs=[BitConverter]::ToUInt32($Bytes,$offset+8*$i+4)}
 })
 [pscustomobject]@{resetSeconds=[BitConverter]::ToUInt32($Bytes,0);actions=$actions}
}
function Read-VpnRecovery([string]$Name){
 $s=Get-CimInstance Win32_Service -Filter ('Name="'+$Name+'"')
 if($null -eq $s){throw 'Required VPN service missing'}
 $r=Get-ItemProperty -LiteralPath ('HKLM:\SYSTEM\CurrentControlSet\Services\'+$Name)
 [pscustomobject]@{name=$Name;state=$s.State;pid=$s.ProcessId;start=$s.StartMode;account=$s.StartName;
  path=$s.PathName;delayed=[int]$r.DelayedAutoStart;failureFlag=[int]$r.FailureActionsOnNonCrashFailures;
  recovery=(Read-VpnFailureActions $r.FailureActions)}
}
function Invoke-VpnSc([string[]]$Arguments){
 $null=& 'C:\Windows\System32\sc.exe' @Arguments
 if($LASTEXITCODE -ne 0){throw 'VPN service configuration command failed'}
}

$root='C:\ProgramData\OracovaVPN-20261003-FA9g4b'
$mtRoot='C:\ProgramData\OracovaMTProto-2a2ae0dae7f749a2bcd664519271c88d'
$names=@('OracovaCloudflare','OracovaCloudflareFallback','OracovaMTProto','OracovaMTProto8443',
 'OracovaSubscription','OracovaVPN','OracovaVPNState')
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=[Security.Principal.WindowsPrincipal]::new($identity)
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
 throw 'Reviewed PC administrator required'
}
$before=@($names|ForEach-Object {Read-VpnRecovery $_})
foreach($s in $before){
 $expected=if($s.name -in @('OracovaMTProto','OracovaMTProto8443')){'"'+$mtRoot+'\ServiceHost.exe" '+$s.name}else{'"'+$root+'\services\'+$s.name+'.exe"'}
 if($s.path -ne $expected -or $s.account -ne 'NT AUTHORITY\LocalService' -or $s.start -ne 'Auto'){
  throw 'Exact installed LocalService VPN service required; no unrelated service changes'
 }
}
if($Mode -eq 'Inspect'){$before|Select-Object name,state,pid,start,delayed,failureFlag,recovery|ConvertTo-Json -Depth 6 -Compress;return}

# Inspect and preserve every policy before the first mutation. No secrets,
# binaries, routes, credentials, service accounts, or firewall rules change.
$rootItem=Get-Item -LiteralPath $root;$rootAcl=Get-Acl -LiteralPath $root
if(($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -or -not $rootAcl.AreAccessRulesProtected -or
 $rootAcl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne 'S-1-5-32-544'){throw 'Protected VPN root required'}
$snapshot=Join-Path $root ('recovery-policy-'+[Guid]::NewGuid().ToString('N'))
$acl=[Security.AccessControl.DirectorySecurity]::new();$admin=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
$acl.SetOwner($admin);$acl.SetAccessRuleProtection($true,$false)
foreach($sid in @($admin,[Security.Principal.SecurityIdentifier]::new('S-1-5-18'))){
 $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
}
[IO.Directory]::CreateDirectory($snapshot,$acl)|Out-Null
[IO.File]::WriteAllText((Join-Path $snapshot 'before.json'),($before|ConvertTo-Json -Depth 6))
foreach($name in $names){
 $null=& 'C:\Windows\System32\reg.exe' export ('HKLM\SYSTEM\CurrentControlSet\Services\'+$name) (Join-Path $snapshot ($name+'.reg'))
 if($LASTEXITCODE -ne 0){throw 'Recovery preimage export failed; no settings changed'}
}
foreach($name in $names){
 Invoke-VpnSc -Arguments @('config',$name,'start=','auto')
 # Windows repeats the last action, so retries continue once per minute.
 Invoke-VpnSc -Arguments @('failure',$name,'reset=','3600','actions=','restart/10000/restart/30000/restart/60000')
 Invoke-VpnSc -Arguments @('failureflag',$name,'1')
 $s=Read-VpnRecovery $name
 $signature=(@($s.recovery.actions|ForEach-Object {"$($_.type)/$($_.delayMs)"}) -join ',')
 if($s.start -ne 'Auto' -or $s.delayed -ne 0 -or $s.failureFlag -ne 1 -or $s.recovery.resetSeconds -ne 3600 -or
  $signature -ne '1/10000,1/30000,1/60000'){throw 'Recovery configuration readback failed; retained preimages required'}
}
$after=@($names|ForEach-Object {Read-VpnRecovery $_})
[IO.File]::WriteAllText((Join-Path $snapshot 'after.json'),($after|ConvertTo-Json -Depth 6))
[pscustomobject]@{snapshot=$snapshot;services=@($after|Select-Object name,state,start,delayed,failureFlag,recovery);
 servicesRestarted=$false;routesChanged=$false;credentialsChanged=$false;nextBootVerified=$false}|ConvertTo-Json -Depth 7 -Compress
