param([Parameter(Mandatory=$true)][string]$Launcher)
# Only inert exit-code tests; no provider, auth, services or scheduled tasks.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
if(-not [IO.File]::Exists($Launcher)){throw 'Literal launcher required'}
$checks=0
foreach($case0 in @(@{args='--self-test';exit=37},@{args='invalid-provider';exit=64},@{args='';exit=64},@{args='Claude extra';exit=64})){
 $info0=[Diagnostics.ProcessStartInfo]::new('C:\Windows\System32\wscript.exe',('//B //NoLogo "'+$Launcher+'" '+$case0.args))
 $info0.UseShellExecute=$false;$info0.CreateNoWindow=$true
 $child0=[Diagnostics.Process]::Start($info0)
 try{
  if(-not $child0.WaitForExit(15000)){throw 'Inert launcher test timed out'}
  if($child0.ExitCode -ne $case0.exit){throw ('Launcher test failed: '+$case0.args+' returned '+$child0.ExitCode)}
  $checks++
 }finally{if(-not $child0.HasExited){$child0.Kill()};$child0.Dispose()}
}
@{passed=$checks;modelLaunches=0;taskChanges=0;exitCodePropagation=$true}|ConvertTo-Json -Compress
