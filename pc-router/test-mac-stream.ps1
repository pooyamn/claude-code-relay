$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'capture-mac-stream.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Capture source parse failed'}
$definition=$ast.Find({param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Add-Type'},$true)
& ([ScriptBlock]::Create($definition.Extent.Text))
foreach($function in $ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){. ([ScriptBlock]::Create($function.Extent.Text))}
$checks=0
function Assert([bool]$Value,[string]$Label){if(-not $Value){throw $Label};$script:checks++}
$root=Join-Path ([IO.Path]::GetTempPath()) ('mac-stream-fixture-'+[Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($root,(New-MigrationStreamAcl $true)) | Out-Null
try{
 Assert-MigrationStreamParent $root
 $file=New-MigrationStreamFile (Join-Path $root 'fixture.bin');$sink=[MigrationStreamSink]::new($file,8)
 try{
  $b=[byte[]]@(0,255,10,13,128,1,2,3);$sink.Write($b,0,8);$sink.Seal();$file.Flush($true)
  Assert ($sink.Count -eq 8 -and $sink.Digest -eq '3a41e63b3fd362a90aff866e7c451eb7afe587dda10da12a3d8df082c2ab5e01') 'Binary bytes have exact SHA256'
  try{$sink.Write($b,0,1);throw 'accepted'}catch{Assert ($_.Exception.Message -match 'sealed') 'Sealed stream rejects later writes'}
 }finally{$sink.Dispose();$file.Dispose()}
 Assert ((Get-Item (Join-Path $root 'fixture.bin')).Length -eq 8) 'All byte values survive native binary sink'
 $out=[IO.MemoryStream]::new();$bounded=[MigrationStreamSink]::new($out,1)
 try{
  try{$bounded.Write([byte[]]@(1,2),0,2);throw 'accepted'}catch{Assert ($_.Exception.Message -match 'bound exceeded') 'Oversize archive fails before write'}
  Assert ($out.Length -eq 0) 'Byte bound cannot silently truncate as success'
 }finally{$bounded.Dispose();$out.Dispose()}
 try{$f=New-MigrationStreamFile (Join-Path $root 'fixture.bin');$f.Dispose();throw 'accepted'}catch{Assert ($_.Exception.Message -match 'exists') 'Existing archive never overwritten'}
 foreach($profile in @('vm-personal','vm-library','vm-extra-work','vm-codex-sqlite','physical-projects','physical-bench-home')){
  $source=Get-MigrationStreamSource $profile
  Assert ($source.host -in @('mac','bench-mac') -and $source.members.Count -gt 0) 'Explicit pinned source profiles only'
 }
 $sqlite=Get-MigrationStreamSource 'vm-codex-sqlite'
 Assert ($sqlite.captureMode -eq 'sqlite-backup-api-memory' -and $sqlite.root -eq '/Users/pouya/.codex') 'SQLite profile explicitly requires backup API memory capture, never raw live-file tar'
 try{Get-MigrationStreamSource '../';throw 'accepted'}catch{Assert ($_.Exception.Message -match 'explicitly selected') 'No arbitrary source/root injection'}
 Assert ((ConvertTo-MigrationNativeArgument 'a"b\') -eq '"a\"b\\"') 'Embedded quote and final backslash literal'
 Assert ((ConvertTo-MigrationNativeArgument 'literal$(name);&') -eq '"literal$(name);&"') 'Arguments do not use a local shell'
 Assert ((ConvertTo-MigrationNativeArgument '-d') -eq '-d') 'WSL parser gets an unquoted flag'
 $literal='a"b\ literal$(name);&'
 $nativeArgs=@('-d','Ubuntu-24.04','-u','pou','--exec','/usr/bin/printf','%s',$literal)
 $start=[Diagnostics.ProcessStartInfo]::new('C:\Windows\System32\wsl.exe',(($nativeArgs|ForEach-Object {ConvertTo-MigrationNativeArgument $_}) -join ' '))
 $start.UseShellExecute=$false;$start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
 $child=[Diagnostics.Process]::Start($start);$out=$child.StandardOutput.ReadToEndAsync();$err=$child.StandardError.ReadToEndAsync()
 if(-not $child.WaitForExit(30000)){$child.Kill();throw 'Fixture native WSL process timed out'}
 Assert ($child.ExitCode -eq 0 -and $out.GetAwaiter().GetResult() -ceq $literal -and $err.GetAwaiter().GetResult().Length -eq 0) 'Actual Windows->WSL argv keeps quote/backslash/shell literals'
 $child.Dispose()
 $acl=Get-Acl (Join-Path $root 'fixture.bin')
 Assert ($acl.AreAccessRulesProtected -and $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -eq 'S-1-5-32-544') 'Actual private file protected and admin owned'
 Assert (@($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]) | Where-Object {$_.IdentityReference.Value -notin @('S-1-5-18','S-1-5-32-544')}).Count -eq 0) 'No ordinary-owner ACL grant'
 [Console]::WriteLine(('All '+$checks+' migration-stream fixtures passed; no Mac/model/real source access.'))
}finally{
 # Only the generated test tree, never a live source/migration root.
 [IO.Directory]::Delete($root,$true)
}
