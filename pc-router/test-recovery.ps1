param([ValidateSet('Compile','OwnerToken','SecretBoundary','EncryptedSnapshots')][string]$Mode='Compile')
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
# Load ONLY reviewed Add-Type definitions, not installation/startup bodies.
function Load-Definition([string]$name){
 $tokens=$null;$errors=$null
 $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $name),[ref]$tokens,[ref]$errors)
 if($errors.Count){throw 'Recovery source parse failed'}
 $command=$ast.Find({param($node) $node -is [Management.Automation.Language.CommandAst] -and $node.GetCommandName() -eq 'Add-Type'},$true)
 if(-not $command){throw 'Reviewed API definition absent'}
 & ([ScriptBlock]::Create($command.Extent.Text))
}
if($Mode -eq 'Compile'){
 Load-Definition 'configure-autologon.ps1';Load-Definition 'router-startup.ps1'
 [Console]::WriteLine('Both recovery API definitions compile; no APIs invoked');exit 0
}
if($Mode -eq 'EncryptedSnapshots'){
 Load-Definition 'configure-autologon.ps1'
 $flags=[Reflection.BindingFlags]'NonPublic,Static';$seal=[OwnerAutologon].GetMethod('SealSnapshot',$flags);$open=[OwnerAutologon].GetMethod('OpenSnapshot',$flags);$checks=0
 foreach($case in @(@($false,[byte[]]@()),@($true,[byte[]]@()),@($true,[Text.Encoding]::Unicode.GetBytes('FAKE')), @($true,[Text.Encoding]::Unicode.GetBytes("FAKE`0")))){
  $sealed=$seal.Invoke($null,[object[]]@([bool]$case[0],[byte[]]$case[1]));$plain=$open.Invoke($null,[object[]]@(,$sealed))
  if($plain[3] -ne [byte][bool]$case[0] -or $plain.Length -ne 6+$case[1].Length){throw 'Snapshot presence/length did not round-trip'};$checks++
  for($i=0;$i -lt $case[1].Length;$i++){if($plain[$i+6] -ne $case[1][$i]){throw 'Snapshot changed original bytes'}};$checks++
  [Array]::Clear($plain,0,$plain.Length);$sealed[$sealed.Length-1]=$sealed[$sealed.Length-1] -bxor 1;$denied=$false
  try{$null=$open.Invoke($null,[object[]]@(,$sealed))}catch{$denied=$true};if(-not $denied){throw 'Corrupt DPAPI snapshot accepted'};$checks++
 }
 foreach($case in @(@($false,[byte[]]@(0,0)),@($true,[byte[]]@(0)))){
  $denied=$false;try{$null=$seal.Invoke($null,[object[]]@([bool]$case[0],[byte[]]$case[1]))}catch{$denied=$true};if(-not $denied){throw 'Invalid prior-secret shape accepted'};$checks++
 }
 [Console]::WriteLine("All $checks encrypted-snapshot checks passed; fixed fake bytes only, no LSA APIs or credential changes");exit 0
}
if($Mode -eq 'OwnerToken'){
 if(-not [Security.Principal.WindowsIdentity]::GetCurrent().IsSystem){throw 'SYSTEM token probe required'}
 Load-Definition 'router-startup.ps1'
 if(-not [ConsoleOwnerReady]::Ready('S-1-5-21-71459778-1164188569-2276148161-1001')){throw 'Exact medium console token not ready'}
 [Console]::WriteLine('Exact non-elevated console owner token verified; no service/process started');exit 0
}
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=[Security.Principal.WindowsPrincipal]::new($identity)
if($identity.User.Value -ne 'S-1-5-21-71459778-1164188569-2276148161-1001' -or $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or [Diagnostics.Process]::GetCurrentProcess().SessionId -eq 0){throw 'Actual non-elevated interactive owner required'}
Load-Definition 'configure-autologon.ps1'
$denied=$false
try{[OwnerAutologon]::Present() | Out-Null}catch{
 $exception=$_.Exception
 while($exception.InnerException){$exception=$exception.InnerException}
 if($exception -is [ComponentModel.Win32Exception] -and $exception.NativeErrorCode -eq 5){$denied=$true}else{throw}
}
if(-not $denied){throw 'Owner unexpectedly accessed the LSA secret policy'}
$denied=$false;$handle=$null
try{$handle=[IO.File]::Open((Join-Path $PSScriptRoot 'router-startup.ps1'),[IO.FileMode]::Open,[IO.FileAccess]::Write)}catch{
 $exception=$_.Exception
 while($exception.InnerException){$exception=$exception.InnerException}
 if($exception -is [UnauthorizedAccessException]){$denied=$true}else{throw}
}finally{if($handle){$handle.Dispose()}}
if(-not $denied){throw 'Owner unexpectedly obtained protected startup-code write access'}
[Console]::WriteLine('Medium owner denied LSA policy read and protected startup-code write; no secret disclosed or file changed')
