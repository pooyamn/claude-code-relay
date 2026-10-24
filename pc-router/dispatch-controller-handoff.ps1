[CmdletBinding(DefaultParameterSetName='Dispatch')]
param(
 [Parameter(Mandatory=$true,ParameterSetName='Dispatch')][ValidatePattern('^[A-Za-z0-9_-]{8,100}$')][string]$RequestId,
 [Parameter(Mandatory=$true,ParameterSetName='Dispatch')][ValidatePattern('^[a-f0-9-]{36}$')][string]$SourceThread,
 [Parameter(Mandatory=$true,ParameterSetName='Dispatch')][ValidatePattern('^[a-f0-9-]{36}$')][string]$TargetThread,
 [Parameter(Mandatory=$true,ParameterSetName='Dispatch')][string]$TextFile,
 [Parameter(Mandatory=$true,ParameterSetName='Dispatch')][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$TextSha256,
 [Parameter(Mandatory=$true,ParameterSetName='Dispatch')][ValidateLength(1,2000)][string]$OwnerApproval,
 [ValidateRange(0,30)][int]$WaitSeconds=20,
 [Parameter(Mandatory=$true,ParameterSetName='Fixture')][switch]$SelfTest
)
# Owner-reviewed controller lane only, not an agent/cwd identity gate. Ordinary
# sessions cannot publish these requests. The live router performs native input
# and keeps its own protected exact-ID/ACK/no-replay journal.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
function Require-HandoffStateAcl([string]$Path){
 $item=Get-Item -LiteralPath $Path
 if(-not $item.PSIsContainer -or $item.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Literal handoff state directory required'}
 $acl=Get-Acl -LiteralPath $Path
 $owner=$acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
 if(-not $acl.AreAccessRulesProtected -or $owner -notin @('S-1-5-18','S-1-5-32-544')){throw 'Explicitly protected SYSTEM/Admin-owned state required before publication'}
 $mutation=[Security.AccessControl.FileSystemRights]::Write -bor [Security.AccessControl.FileSystemRights]::Delete -bor [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor [Security.AccessControl.FileSystemRights]::ChangePermissions -bor [Security.AccessControl.FileSystemRights]::TakeOwnership
 foreach($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])){
  if($rule.AccessControlType -eq 'Allow' -and ($rule.FileSystemRights -band $mutation) -and $rule.IdentityReference.Value -notin @('S-1-5-18','S-1-5-32-544')){throw 'Ordinary accounts cannot mutate handoff state'}
 }
}
if($SelfTest){
 if($env:OS -ne 'Windows_NT'){throw 'Windows ACL fixture required'}
 $fixture=Join-Path ([IO.Path]::GetTempPath()) ('khadang-handoff-acl-'+[Guid]::NewGuid().ToString('N'));[IO.Directory]::CreateDirectory($fixture)|Out-Null
 try{
  $acl=[Security.AccessControl.DirectorySecurity]::new();$acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'));$acl.SetAccessRuleProtection($true,$false)
  foreach($sid in @('S-1-5-18','S-1-5-32-544')){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','ContainerInherit,ObjectInherit','None','Allow'))};Set-Acl -LiteralPath $fixture -AclObject $acl
  Require-HandoffStateAcl $fixture;$checks=1
  $acl.SetAccessRuleProtection($false,$true);Set-Acl -LiteralPath $fixture -AclObject $acl
  $denied=$false;try{Require-HandoffStateAcl $fixture}catch{$denied=$true};if(-not $denied){throw 'Inherited state accepted'};$checks++
  $acl.SetAccessRuleProtection($true,$false);$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new('S-1-1-0'),'Write','Allow'));Set-Acl -LiteralPath $fixture -AclObject $acl
  $denied=$false;try{Require-HandoffStateAcl $fixture}catch{$denied=$true};if(-not $denied){throw 'Ordinary mutation accepted'};$checks++
  $acl.RemoveAccessRuleAll([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new('S-1-1-0'),'Write','Allow'));Set-Acl -LiteralPath $fixture -AclObject $acl
  Require-HandoffStateAcl $fixture;$checks++
  Write-Output "Passed $checks controller-handoff ACL publication checks (no production state/credentials/network/models)."
 }finally{[IO.Directory]::Delete($fixture,$true)}
 return
}
$root='C:\ProgramData\KhadangRouter';$native='C:\ProgramData\OracovaNativeRemote'
$who=[Security.Principal.WindowsIdentity]::GetCurrent()
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not ([Security.Principal.WindowsPrincipal]::new($who)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Reviewed elevated controller lane required; agent names/cwd grant no authority'}
$helper='C:\Users\pou\AppData\Local\Temp\deploy-switch-isolation-20261014.ps1'
if((Get-FileHash $helper).Hash -ne '4487D3F771A3B79B31936E361CFB6CB9BD8693E1F445B064125E6BC9668F0B01'){throw 'Reviewed helper changed'}
$ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$null,[ref]$null)
foreach($name in @('Protect','LoadSql')){$d=$ast.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true);if(-not $d){throw 'Reviewed helper missing'};. ([ScriptBlock]::Create($d.Extent.Text))}
LoadSql "$native\inspect-state.ps1" 'BFF3C4A0D5D7D5A980E41D0FBCF466A5FB3F178F381E87406AA3016C940F15A2' 'RouterReceipts'
$p=[IO.File]::ReadAllText("$root\config.json")|ConvertFrom-Json
$proof=[IO.File]::ReadAllText("$root\state\probe.json")|ConvertFrom-Json
$s=[IO.File]::ReadAllText("$root\state\status.json")|ConvertFrom-Json
if((Get-Service KhadangRouter).Status -ne 'Running' -or -not $proof.verified -or -not $proof.credentialAndCodeDenied -or
 (Get-FileHash "$root\bin\KhadangRouter.dll").Hash -ne $proof.routerSha256 -or (Get-FileHash "$root\config.json").Hash -ne $proof.policySha256 -or
 [DateTimeOffset]$s.at -lt [DateTimeOffset]::UtcNow.AddMinutes(-1) -or -not $s.nativeTransportHealthy -or -not $s.backgroundHealthy){throw 'Fresh accepted live router required'}
Require-HandoffStateAcl $p.StateDirectory
$bindings=@([RouterReceipts]::Read('SELECT payload FROM bindings')|ForEach-Object {$_[0]|ConvertFrom-Json})
$source=@($bindings|Where-Object ThreadId -eq $SourceThread);$target=@($bindings|Where-Object ThreadId -eq $TargetThread)
if($source.Count -ne 1 -or $target.Count -ne 1 -or $SourceThread -eq $TargetThread -or $target[0].Backend -notin @('codex','claude') -or $target[0].Runtime -ne 'linux' -or
 @($bindings|Where-Object {$_.ThreadId -eq '01a0facd-1bc0-7d23-95d6-c32fde0c62db' -and $_.Workspace -ceq '/Users/pouya/.openclaw/workspace/claude-code-relay'}).Count -ne 1){throw 'Exact controller/source and supported existing Linux Claude/Codex target required'}
$live=@($s.nativeSessions|Where-Object {$_.binding.ThreadId -eq $TargetThread})
if($live.Count -ne 1 -or -not $live[0].ready -or $live[0].held -or -not $live[0].nativeConnected){throw 'Recover the exact held/unavailable target first; no bypass or new session'}
if($TextFile -notmatch '^[A-Za-z]:\\' -or $TextFile.Contains('/') -or $TextFile.Substring(2).Contains(':') -or $TextFile.Split('\') -contains '..'){throw 'Explicit local Windows text path required'}
$file=Get-Item -LiteralPath $TextFile
if($file.PSIsContainer -or $file.Attributes -band [IO.FileAttributes]::ReparsePoint -or $file.Length -gt 48000){throw 'Bounded literal task file required'}
$text=[IO.File]::ReadAllText($file.FullName,[Text.UTF8Encoding]::new($false,$true))
$sha=[Security.Cryptography.SHA256]::Create();try{$digest=[BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($text))).Replace('-','')}finally{$sha.Dispose()}
if($digest -ne $TextSha256 -or [string]::IsNullOrWhiteSpace($text) -or $text.Length -gt 12000){throw 'Reviewed task text/hash changed'}
$folder="$root\state\controller-handoffs";if(-not (Test-Path $folder)){New-Item -ItemType Directory $folder|Out-Null;Protect $folder $true}
if((Get-Item $folder).Attributes -band [IO.FileAttributes]::ReparsePoint -or -not (Get-Acl $folder).AreAccessRulesProtected){throw 'Protected literal handoff folder required'}
$path=Join-Path $folder ($RequestId+'.json');$result=Join-Path $folder ($RequestId+'.result')
if(Test-Path $path){
 $old=[IO.File]::ReadAllText($path)|ConvertFrom-Json
 if($old.RequestId -ne $RequestId -or $old.Source.ThreadId -ne $SourceThread -or $old.Target.ThreadId -ne $TargetThread -or $old.TextSha256 -ne $digest -or $old.Approval -cne $OwnerApproval){throw 'Stable request ID already used with different content; no replay'}
}else{
 $now=[DateTimeOffset]::UtcNow
 $job=@{Schema='ccrelay.controller_handoff.v1';RequestId=$RequestId;OwnerId=$p.OwnerId;Source=$source[0];Target=$target[0];Text=$text;TextSha256=$digest;Approval=$OwnerApproval;ApprovedAt=$now.ToString('o');ExpiresAt=$now.AddMinutes(15).ToString('o')}
 $tmp=Join-Path $folder ($RequestId+'.publishing');$bytes=[Text.Encoding]::UTF8.GetBytes(($job|ConvertTo-Json -Depth 8 -Compress))
 $stream=[IO.File]::Open($tmp,'CreateNew','Write','None');try{$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()};Protect $tmp;[IO.File]::Move($tmp,$path)
}
$end=[DateTimeOffset]::UtcNow.AddSeconds($WaitSeconds)
do{
 if(Test-Path $result){try{$receipt=[IO.File]::ReadAllText($result)|ConvertFrom-Json;if($receipt.requestId -eq $RequestId){$receipt|ConvertTo-Json -Depth 8 -Compress;return}}catch{}}
 Start-Sleep -Milliseconds 250
}while([DateTimeOffset]::UtcNow -lt $end)
@{requestId=$RequestId;state='unconfirmed';accepted=$false;retry=$false;inspect=$result}|ConvertTo-Json -Compress
