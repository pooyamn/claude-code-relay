param([ValidateSet('Compile','OwnerToken','SecretBoundary')][string]$Mode='Compile')
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
