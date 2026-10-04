param(
 [Parameter(Mandatory=$true)][ValidateSet('vm-personal','vm-library','vm-extra-work','physical-projects','physical-bench-home')][string]$Profile,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RunId
)
# One-shot source -> private PC stream. No Mac archive/temp file, extraction,
# activation, source freeze, deletion or retry. Selected live data is a SEED,
# never a consistent/final whole-Mac backup. Keep failed/partial runs for audit.
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
function New-MigrationStreamAcl([bool]$Directory){
 $acl=$(if($Directory){[Security.AccessControl.DirectorySecurity]::new()}else{[Security.AccessControl.FileSecurity]::new()})
 $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'));$acl.SetAccessRuleProtection($true,$false)
 foreach($sid in @('S-1-5-18','S-1-5-32-544')){
  $identity=[Security.Principal.SecurityIdentifier]::new($sid)
  if($Directory){$rule=[Security.AccessControl.FileSystemAccessRule]::new($identity,'FullControl','ContainerInherit,ObjectInherit','None','Allow')}
  else{$rule=[Security.AccessControl.FileSystemAccessRule]::new($identity,'FullControl','Allow')}
  $acl.AddAccessRule($rule)
 }
 return $acl
}
function Assert-MigrationStreamParent([string]$Path){
 for($part=[IO.DirectoryInfo]::new($Path);$null -ne $part;$part=$part.Parent){
  if(-not $part.Exists -or ($part.Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Literal existing destination ancestors required'}
 }
 $acl=Get-Acl -LiteralPath $Path
 $grants=@($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
 if($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne 'S-1-5-32-544' -or
  -not $acl.AreAccessRulesProtected -or $grants.Count -ne 2 -or
  @($grants | Where-Object {$_.IdentityReference.Value -notin @('S-1-5-18','S-1-5-32-544') -or $_.AccessControlType -ne 'Allow'}).Count){throw 'Administrator/SYSTEM-only destination required'}
}
function New-MigrationStreamFile([string]$Path){
 return [IO.FileStream]::new($Path,[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::None,65536,[IO.FileOptions]::None,(New-MigrationStreamAcl $false))
}
function ConvertTo-MigrationNativeArgument([string]$Value){
 # Windows CommandLineToArgvW/CRT quoting, not shell interpolation.
 # WSL's option parser requires its plain flags unquoted.
 if($Value -match '^[A-Za-z0-9_./:=@+-]+$'){return $Value}
 return '"'+[regex]::Replace([regex]::Replace($Value,'(\\*)"','$1$1\"'),'(\\+)$','$1$1')+'"'
}
function Get-MigrationStreamSource([string]$Name){
 switch($Name){
  'vm-personal' {return @{host='mac';user='pouya';root='/Users/pouya';members=@('Documents','Downloads')}}
  'vm-library' {return @{host='mac';user='pouya';root='/Users/pouya';members=@('Library')}}
  'vm-extra-work' {return @{host='mac';user='pouya';root='/Users/pouya';members=@('code','src','test2','toolchains','.oracova','Applications','Movies','Music','Pictures','Public','Desktop','.Trash','Augur-1.zip','note.txt','oracova-BOM-JLCPCB.csv','oracova-BOM.csv','oracova-CPL-JLCPCB.csv','oracova-positions.csv','oss-cad-dl.log','oss-cad-extract.err')}}
  'physical-projects' {return @{host='bench-mac';user='oracova';root='/Users/pouya';members=@('Codes','Developer','Sources','flutter_blue_plus','flutter_bluetooth')}}
  'physical-bench-home' {return @{host='bench-mac';user='oracova';root='/Users/oracova';members=@('.')}}
  default {throw 'Only explicitly selected migration source profiles admitted'}
 }
}
Add-Type @'
using System;
using System.IO;
using System.Security.Cryptography;
public sealed class MigrationStreamSink : Stream {
 readonly Stream output; readonly long limit; readonly SHA256 hash=SHA256.Create();
 public long Count {get; private set;} public string Digest {get; private set;}
 public MigrationStreamSink(Stream output,long limit){this.output=output;this.limit=limit;}
 public override void Write(byte[] b,int start,int count){
  if(Digest!=null || count>limit-Count)throw new IOException("Archive bound exceeded or sealed; partial retained");
  output.Write(b,start,count);hash.TransformBlock(b,start,count,null,0);Count+=count;
 }
 public void Seal(){hash.TransformFinalBlock(new byte[0],0,0);Digest=BitConverter.ToString(hash.Hash).Replace("-", "").ToLowerInvariant();output.Flush();}
 public override void Flush(){output.Flush();} public override bool CanRead{get{return false;}}
 public override bool CanWrite{get{return true;}} public override bool CanSeek{get{return false;}}
 public override long Length{get{return Count;}} public override long Position{get{return Count;}set{throw new NotSupportedException();}}
 public override int Read(byte[] b,int s,int c){throw new NotSupportedException();}
 public override long Seek(long o,SeekOrigin s){throw new NotSupportedException();}
 public override void SetLength(long n){throw new NotSupportedException();}
 protected override void Dispose(bool disposing){if(disposing)hash.Dispose();base.Dispose(disposing);}
}
'@
$principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if($env:COMPUTERNAME -ne 'DESKTOP-8SO9HDK' -or -not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Exact PC administrator capture required'}
$parent='C:\ProgramData\OracovaMigration';Assert-MigrationStreamParent $parent
$folder=Join-Path $parent $RunId
if(Test-Path -LiteralPath $folder){throw 'Run exists; inspect it, never restart or overwrite'}
[IO.Directory]::CreateDirectory($folder,(New-MigrationStreamAcl $true)) | Out-Null
$source=Get-MigrationStreamSource $Profile
# Hash the SAME compressed bytes sent down SSH. Ruby drains tar diagnostics
# without printing private filenames. Source errors remain failures; none are
# converted to a successful partial archive. No source-side writes are required.
$producer=@'
require 'json'; require 'digest'; require 'open3'; require 'etc'
STDOUT.binmode; STDOUT.sync=true
profile=JSON.parse(Base64.strict_decode64(ARGV.fetch(0))); root=profile.fetch('root'); members=profile.fetch('members')
begin
 raise 'identity' unless Etc.getpwuid.name==profile.fetch('user') && Process.uid>0
 raise 'root' unless File.directory?(root) && !File.symlink?(root) && File.realpath(root)==root
 members.each { |m| raise 'member' unless File.exist?(File.join(root,m)) || File.symlink?(File.join(root,m)) }
 hash=Digest::SHA256.new; bytes=0; errors=0; error_hash=Digest::SHA256.new; diagnostic=''.b; code=nil
 Open3.popen3({'COPYFILE_DISABLE'=>'1'},'/usr/bin/tar','--options','gzip:compression-level=1','-czf','-','-C',root,'--',*members) do |input,output,error,wait|
  input.close; output.binmode; error.binmode
  drain=Thread.new do
   while chunk=error.read(65536)
    errors+=chunk.bytesize; error_hash.update(chunk)
    diagnostic << chunk.byteslice(0,[chunk.bytesize,1048576-diagnostic.bytesize].min) if diagnostic.bytesize<1048576
   end
  end
  begin
   while chunk=output.read(65536); STDOUT.write(chunk); bytes+=chunk.bytesize; hash.update(chunk); end
  rescue Errno::EPIPE
   Process.kill('TERM',wait.pid) rescue nil
   raise
  ensure
   code=wait.value.exitstatus; drain.join
  end
 end
 # Bounded source diagnostics travel ONLY into the protected receiver log.
 # The public receipt below never includes these filenames/content bytes.
 STDERR.puts(JSON.generate(schema:'ccrelay.mac_archive_producer.v1',bytes:bytes,sha256:hash.hexdigest,producerExit:code,warningBytes:errors,warningSha256:error_hash.hexdigest,warningBase64:Base64.strict_encode64(diagnostic),warningTruncated:errors>diagnostic.bytesize))
 exit(code==0 && errors==0 ? 0 : 1)
rescue StandardError => e
 STDERR.puts(JSON.generate(schema:'ccrelay.mac_archive_producer.v1',errorType:e.class.name,producerExit:1))
 exit 1
end
'@
$encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($producer))
$spec=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($source | ConvertTo-Json -Compress)))
$remote="/usr/bin/ruby -rbase64 -e 'eval(Base64.strict_decode64(ARGV.shift))' '$encoded' '$spec'"
$wsl='C:\Windows\System32\wsl.exe'
$migrationArguments=@('-d','Ubuntu-24.04','-u','pou','--exec','/usr/bin/timeout','--signal=TERM','--kill-after=15s','900s',
 '/usr/bin/ssh','-F','/Users/pouya/.ssh/config','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=10','-T',$source.host,$remote)
$info=[Diagnostics.ProcessStartInfo]::new($wsl, (($migrationArguments | ForEach-Object {ConvertTo-MigrationNativeArgument $_}) -join ' '))
$info.UseShellExecute=$false;$info.CreateNoWindow=$true;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true;$info.RedirectStandardInput=$true
$archive=Join-Path $folder ($Profile+'.tar.gz');$diagnostics=Join-Path $folder 'producer.private.log'
$file=New-MigrationStreamFile $archive;$errors=New-MigrationStreamFile $diagnostics
$sink=[MigrationStreamSink]::new($file,20GB);$child=$null
$report=[ordered]@{schema='ccrelay.mac_to_pc_direct_stream.v1';profile=$Profile;run=$RunId;startedAt=[DateTime]::UtcNow.ToString('o');finishedAt=$null;
 destination=$archive;sourceMacTemporaryArchive=$false;producerExit=$null;transportExit=$null;archiveReaderExit=$null;
 bytes=[long]0;sha256=$null;producerDigestMatched=$false;sourceWarningBytes=$null;sourceWarningTruncated=$null;targetProtected=$false;seedAccepted=$false;
 sourceWritersFrozen=$false;consistentFinalSnapshot=$false;fullMacBackup=$false;encryptedAtRest=$false;extracted=$false;errorType=$null}
try{
 $child=[Diagnostics.Process]::Start($info);$child.StandardInput.Close()
 $copy=$child.StandardOutput.BaseStream.CopyToAsync($sink);$errorCopy=$child.StandardError.BaseStream.CopyToAsync($errors)
 [Console]::WriteLine((@{stage='streaming';run=$RunId;profile=$Profile;receiverPid=$child.Id}|ConvertTo-Json -Compress))
 $clock=[Diagnostics.Stopwatch]::StartNew()
 while(-not $child.WaitForExit(250)){
  if($copy.IsFaulted){$copy.GetAwaiter().GetResult() | Out-Null}
  if($errorCopy.IsFaulted){$errorCopy.GetAwaiter().GetResult() | Out-Null}
  if($clock.ElapsedMilliseconds -gt 930000){throw 'Owned source stream deadline exceeded; retain partial run'}
 }
 $copy.GetAwaiter().GetResult() | Out-Null;$errorCopy.GetAwaiter().GetResult() | Out-Null;$sink.Seal();$file.Flush($true)
 $report.transportExit=$child.ExitCode;$report.bytes=$sink.Count;$report.sha256=$sink.Digest
}catch{$report.errorType=$_.Exception.GetType().Name}
finally{
 if($child -and -not $child.HasExited){$child.Kill();$child.WaitForExit()}
 $sink.Dispose();$file.Dispose();$errors.Dispose()
}
if(-not $report.errorType){
 try{
  $lines=@(Get-Content -LiteralPath $diagnostics -Encoding UTF8 | Where-Object {$_ -match '^\{.*\}$'})
  if($lines.Count -ne 1){throw 'Exactly one producer receipt required'}
  $receipt=$lines[0] | ConvertFrom-Json
  $report.producerExit=$receipt.producerExit
  $report.sourceWarningBytes=$receipt.warningBytes;$report.sourceWarningTruncated=$receipt.warningTruncated
  $report.producerDigestMatched=($receipt.schema -eq 'ccrelay.mac_archive_producer.v1' -and $receipt.bytes -eq $report.bytes -and $receipt.sha256 -eq $report.sha256)
  Assert-MigrationStreamParent $folder
  $a=Get-Acl -LiteralPath $archive
  $report.targetProtected=($a.AreAccessRulesProtected -and $a.GetOwner([Security.Principal.SecurityIdentifier]).Value -eq 'S-1-5-32-544' -and
   @($a.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]) | Where-Object {$_.IdentityReference.Value -notin @('S-1-5-18','S-1-5-32-544')}).Count -eq 0)
  $read=[Diagnostics.ProcessStartInfo]::new($wsl,('-d Ubuntu-24.04 -u pou --exec /usr/bin/timeout 300s /usr/bin/tar -tzf /mnt/c/ProgramData/OracovaMigration/'+$RunId+'/'+$Profile+'.tar.gz'))
  $read.UseShellExecute=$false;$read.RedirectStandardOutput=$true;$read.RedirectStandardError=$true
  $reader=[Diagnostics.Process]::Start($read);$discard=$reader.StandardOutput.BaseStream.CopyToAsync([IO.Stream]::Null)
  $readerError=New-MigrationStreamFile (Join-Path $folder 'reader.private.log')
  try{$readerErrors=$reader.StandardError.BaseStream.CopyToAsync($readerError);$reader.WaitForExit();$discard.GetAwaiter().GetResult() | Out-Null;$readerErrors.GetAwaiter().GetResult() | Out-Null;$report.archiveReaderExit=$reader.ExitCode}finally{$readerError.Dispose();$reader.Dispose()}
  $report.seedAccepted=($report.transportExit -eq 0 -and $report.producerExit -eq 0 -and $receipt.warningBytes -eq 0 -and
   $report.producerDigestMatched -and $report.targetProtected -and $report.archiveReaderExit -eq 0 -and (Get-FileHash -LiteralPath $archive).Hash.ToLowerInvariant() -eq $report.sha256)
 }catch{$report.errorType=$_.Exception.GetType().Name}
}
$report.finishedAt=[DateTime]::UtcNow.ToString('o')
$result=New-MigrationStreamFile (Join-Path $folder 'result.json')
try{$body=[Text.UTF8Encoding]::new($false).GetBytes(($report | ConvertTo-Json -Compress));$result.Write($body,0,$body.Length);$result.Flush($true)}finally{$result.Dispose()}
[Console]::WriteLine(($report | ConvertTo-Json -Compress))
if(-not $report.seedAccepted){throw 'Stream not accepted; retain attempt and inspect receipt, no automatic retry'}
