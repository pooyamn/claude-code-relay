param(
 [Parameter(Mandatory=$true)][ValidateSet('vm-personal','vm-library','vm-extra-work','vm-owner-tools','vm-owner-tools-manifest','vm-package-caches','vm-editor-cache','vm-darwin-cad-tools','vm-codex-sqlite','vm-ai-hil-kicad-dependency','vm-dirty-work-manifest','vm-agent-settings-current','vm-native-history-delta','vm-useful-library-delta','physical-projects','physical-bench-home','physical-shared','vm-shared','physical-service-config','vm-service-config','physical-service-code','vm-system-applications','physical-system-applications')][string]$Profile,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RunId,
 [ValidatePattern('^[0-9a-f]{64}$')][string]$SqliteProducerSha256,
 [ValidatePattern('^[0-9a-f]{64}$')][string]$OwnerToolsProducerSha256,
 [ValidatePattern('^[0-9a-f]{64}$')][string]$DirtySelectionSha256
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
function Compress-MigrationProducer([byte[]]$Bytes){
 # Only already hash-reviewed code, not private selections/file data. Keep the
 # argv below Windows' process-launch limit; never materialize code on the Mac.
 if(-not $Bytes -or $Bytes.Length -gt 256KB){throw 'Reviewed producer code byte bound'}
 $buffer=[IO.MemoryStream]::new()
 try{
  $gzip=[IO.Compression.GZipStream]::new($buffer,[IO.Compression.CompressionLevel]::Optimal,$true)
  try{$gzip.Write($Bytes,0,$Bytes.Length)}finally{$gzip.Dispose()}
  return [Convert]::ToBase64String($buffer.ToArray())
 }finally{$buffer.Dispose()}
}
function Get-MigrationStreamSource([string]$Name){
 switch($Name){
  'vm-personal' {return @{host='mac';user='pouya';root='/Users/pouya';members=@('Documents','Downloads')}}
  'vm-library' {return @{host='mac';user='pouya';root='/Users/pouya';members=@('Library')}}
  'vm-extra-work' {return @{host='mac';user='pouya';root='/Users/pouya';members=@('code','src','test2','toolchains','.oracova','Applications','Movies','Music','Pictures','Public','Desktop','.Trash','Augur-1.zip','note.txt','oracova-BOM-JLCPCB.csv','oracova-BOM.csv','oracova-CPL-JLCPCB.csv','oracova-positions.csv','oss-cad-dl.log','oss-cad-extract.err')}}
  # These literal, separately bounded cohorts close the home-root inventory
  # gaps, including caches. Never infer that an inaccessible/cache file is
  # disposable; preserve bytes without activating Darwin tools on the PC.
  'vm-owner-tools' {return @{host='mac';user='pouya';root='/Users/pouya';members=@('.CFUserTextEncoding','.DS_Store','.anydesk','.aspnet','.azure','.bun','.cargo','.claude.json','.claude.json.bak-trust-20260924-190310','.config','.copilot','.dotnet','.gitconfig','.homebrew','.kimi-code','.local','.matplotlib','.net','.nuget','.rustup','.ssh','.templateengine','.webos','.zcompdump','.zprofile','.zsh_history','.zsh_sessions','.zshrc','.zshrc.bak-opus5-20260727-192500')}}
  'vm-owner-tools-manifest' {$spec=Get-MigrationStreamSource 'vm-owner-tools';$spec.captureMode='file-bytes-and-socket-metadata';return $spec}
  'vm-package-caches' {return @{host='mac';user='pouya';root='/Users/pouya';members=@('.cache','.npm')}}
  'vm-editor-cache' {return @{host='mac';user='pouya';root='/Users/pouya';members=@('.vscode-server')}}
  'vm-darwin-cad-tools' {return @{host='mac';user='pouya';root='/Users/pouya';members=@('oss-cad-suite')}}
  'vm-codex-sqlite' {return @{host='mac';user='pouya';root='/Users/pouya/.codex';members=@('.');captureMode='sqlite-backup-api-memory'}}
  # Preserve this source-only dependency metadata before Mac retirement. Its
  # broken .git links are retained as links, never activated or followed.
  'vm-ai-hil-kicad-dependency' {return @{host='mac';user='pouya';root='/Users/pouya/.openclaw/workspace/ai-hil/hardware/duts/dut-d/node_modules';members=@('circuit-json-to-kicad')}}
  'vm-dirty-work-manifest' {return @{host='mac';user='pouya';root='/Users/pouya/.openclaw/workspace';members=@();captureMode='observed-exact-leaf-content'}}
  # Separately sealed exact leaves, restricted by the producer to ten fixed
  # native-history roots. No recursive home/caches or live DB consistency grant.
  'vm-native-history-delta' {return @{host='mac';user='pouya';root='/Users/pouya';members=@();captureMode='observed-exact-native-leaf-content'}}
  'vm-useful-library-delta' {return @{host='mac';user='pouya';root='/Users/pouya';members=@();captureMode='observed-exact-useful-library-content'}}
  # Current unique settings/credentials/memory after the earlier seed. No
  # downloadable apps, packages, model caches or active-PC import. Retired
  # memory/task journals stay together; no live SQLite consistency is claimed.
  'vm-agent-settings-current' {return @{host='mac';user='pouya';root='/Users/pouya';members=@(
   '.claude.json','.claude/settings.json','.claude/.credentials.json','.claude/CLAUDE.md',
   '.codex/auth.json','.codex/config.toml','.codex/AGENTS.md','.codex/session_index.jsonl',
   '.openclaw/openclaw.json','.openclaw/openclaw.json.last-good','.openclaw/exec-approvals.json',
   '.openclaw/identity','.openclaw/devices','.openclaw/credentials','.openclaw/secrets',
   '.openclaw/service-env','.openclaw/cron','.openclaw/memory','.openclaw/tasks')}}
  'physical-projects' {return @{host='bench-mac';user='oracova';root='/Users/pouya';members=@('Codes','Developer','Sources','flutter_blue_plus','flutter_bluetooth')}}
  'physical-bench-home' {return @{host='bench-mac';user='oracova';root='/Users/oracova';members=@('.')}}
  # Operational projects also exist outside the account homes. Preserve the
  # complete Shared cohort, including relocated items, without activating it.
  'physical-shared' {return @{host='bench-mac';user='oracova';root='/Users';members=@('Shared')}}
  'vm-shared' {return @{host='mac';user='pouya';root='/Users';members=@('Shared')}}
  # Preserve only these three selected system-level configuration cohorts.
  # This does not grant database data, root account or whole-machine capture.
  'physical-service-config' {return @{host='bench-mac';user='oracova';root='/';members=@('Library/LaunchAgents','Library/LaunchDaemons','opt/homebrew/etc')}}
  'vm-service-config' {return @{host='mac';user='pouya';root='/';members=@('Library/LaunchAgents','Library/LaunchDaemons','opt/homebrew/etc')}}
  # System Applications is distinct from the already preserved owner's
  # Applications directory. Copy bytes/links only, never activate Mac apps.
  'vm-system-applications' {return @{host='mac';user='pouya';root='/';members=@('Applications')}}
  'physical-system-applications' {return @{host='bench-mac';user='oracova';root='/';members=@('Applications')}}
  # Original Darwin service/client code and local tools, not an active PC
  # replacement. PostgreSQL's protected data and Library remain open gaps.
  'physical-service-code' {return @{host='bench-mac';user='oracova';root='/';members=@(
   'Library/PostgreSQL/16/StackBuilder_3rd_party_licenses.txt','Library/PostgreSQL/16/commandlinetools_3rd_party_licenses.txt',
   'Library/PostgreSQL/16/bin','Library/PostgreSQL/16/debug_symbols','Library/PostgreSQL/16/doc','Library/PostgreSQL/16/include',
   'Library/PostgreSQL/16/installation_summary.log','Library/PostgreSQL/16/installer','Library/PostgreSQL/16/lib',
   'Library/PostgreSQL/16/pgAdmin 4.app','Library/PostgreSQL/16/pgAdmin_3rd_party_licenses.txt','Library/PostgreSQL/16/pgAdmin_license.txt',
   'Library/PostgreSQL/16/pg_env.sh','Library/PostgreSQL/16/scripts','Library/PostgreSQL/16/server_license.txt','Library/PostgreSQL/16/share',
   'Library/PostgreSQL/16/stackbuilder.app','Library/PostgreSQL/16/uninstall-postgresql.app',
   'Library/PrivilegedHelperTools','Library/Frameworks/OpenVPNConnect.framework','Library/Frameworks/OVPNHelper.framework','usr/local/bin')}}
  default {throw 'Only explicitly selected migration source profiles admitted'}
 }
}
function Get-MigrationStreamArchiveLimit([string]$Name){
 # The physical Applications preflight observed about30GiB allocated. Grant
 # only this exact cohort a40GiB sink; all existing profiles retain20GiB.
 Get-MigrationStreamSource $Name | Out-Null
 if($Name -eq 'physical-system-applications'){return 40GB}
 return 20GB
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
if($SqliteProducerSha256 -and $OwnerToolsProducerSha256){throw 'Exactly one explicit producer grant allowed'}
if($OwnerToolsProducerSha256 -and $Profile -notin @('vm-owner-tools-manifest','vm-dirty-work-manifest','vm-native-history-delta','vm-useful-library-delta')){throw 'File-manifest producer grant cannot apply to a different profile'}
if($DirtySelectionSha256 -and $Profile -notin @('vm-dirty-work-manifest','vm-native-history-delta','vm-useful-library-delta')){throw 'Dirty selection grant cannot apply to a different profile'}
if($Profile -eq 'vm-codex-sqlite'){
 if(-not $SqliteProducerSha256 -or $PSScriptRoot -notmatch '^C:\\ProgramData\\OracovaMigration\\stream-helper-[0-9a-f]{32}$'){throw 'Independently reviewed sealed SQLite producer required'}
 Assert-MigrationStreamParent $PSScriptRoot
 $sqliteCode=Join-Path $PSScriptRoot 'stream_codex_sqlite.py'
 if((Get-Item -LiteralPath $sqliteCode).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Literal sealed producer required'}
 $codeBytes=[IO.File]::ReadAllBytes($sqliteCode)
 $codeHash=[BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($codeBytes)).Replace('-','').ToLowerInvariant()
 if($codeHash -ne $SqliteProducerSha256){throw 'SQLite producer bytes differ from reviewed hash'}
 $encoded=Compress-MigrationProducer $codeBytes
 $remote="/opt/homebrew/bin/python3.14 -I -B -c 'import base64,gzip,sys; p=gzip.decompress(base64.b64decode(sys.argv.pop())); exec(p)' '$encoded'"
}elseif($SqliteProducerSha256){throw 'SQLite producer grant cannot apply to a different profile'}
if($Profile -in @('vm-owner-tools-manifest','vm-dirty-work-manifest','vm-native-history-delta','vm-useful-library-delta')){
 if(-not $OwnerToolsProducerSha256 -or $PSScriptRoot -notmatch '^C:\\ProgramData\\OracovaMigration\\stream-helper-[0-9a-f]{32}$'){throw 'Independently reviewed sealed owner-tools producer required'}
 Assert-MigrationStreamParent $PSScriptRoot
 $ownerToolsCode=Join-Path $PSScriptRoot 'stream_owner_tools.py'
 if((Get-Item -LiteralPath $ownerToolsCode).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Literal sealed producer required'}
 $codeBytes=[IO.File]::ReadAllBytes($ownerToolsCode)
 $codeHash=[BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($codeBytes)).Replace('-','').ToLowerInvariant()
 if($codeHash -ne $OwnerToolsProducerSha256){throw 'Owner-tools producer bytes differ from reviewed hash'}
 $encoded=Compress-MigrationProducer $codeBytes
 $remote="/opt/homebrew/bin/python3.14 -I -B -c 'import base64,gzip,sys; p=gzip.decompress(base64.b64decode(sys.argv.pop())); exec(p)' '$encoded'"
 if($Profile -in @('vm-dirty-work-manifest','vm-native-history-delta','vm-useful-library-delta')){
  if(-not $DirtySelectionSha256){throw 'Independently reviewed exact dirty selection required'}
  $selectionFile=Join-Path $PSScriptRoot 'dirty-selection.json'
  if((Get-Item $selectionFile).Attributes -band [IO.FileAttributes]::ReparsePoint -or (Get-Item $selectionFile).Length -gt 4MB){throw 'Literal bounded sealed selection required'}
  if((Get-FileHash $selectionFile).Hash.ToLowerInvariant() -ne $DirtySelectionSha256){throw 'Sealed dirty selection differs from reviewed hash'}
  $selectionBytes=[IO.File]::ReadAllBytes($selectionFile)
  $selectionMode=$(if($Profile -eq 'vm-native-history-delta'){'--native-selection'}elseif($Profile -eq 'vm-useful-library-delta'){'--library-selection'}else{'--dirty-selection'})
  $remote="/opt/homebrew/bin/python3.14 -I -B -c 'import base64,gzip,sys; p=gzip.decompress(base64.b64decode(sys.argv.pop())); sys.argv.append(`"$selectionMode`"); exec(p)' '$encoded'"
 }
}
$wsl='C:\Windows\System32\wsl.exe'
$migrationArguments=@('-d','Ubuntu-24.04','-u','pou','--exec','/usr/bin/timeout','--signal=TERM','--kill-after=15s','900s',
 '/usr/bin/ssh','-F','/Users/pouya/.ssh/config','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=10','-T',$source.host,$remote)
$info=[Diagnostics.ProcessStartInfo]::new($wsl, (($migrationArguments | ForEach-Object {ConvertTo-MigrationNativeArgument $_}) -join ' '))
$info.UseShellExecute=$false;$info.CreateNoWindow=$true;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true;$info.RedirectStandardInput=$true
$archive=Join-Path $folder ($Profile+'.tar.gz');$diagnostics=Join-Path $folder 'producer.private.log'
$file=New-MigrationStreamFile $archive;$errors=New-MigrationStreamFile $diagnostics
$sink=[MigrationStreamSink]::new($file,(Get-MigrationStreamArchiveLimit $Profile));$child=$null
$report=[ordered]@{schema='ccrelay.mac_to_pc_direct_stream.v1';profile=$Profile;run=$RunId;startedAt=[DateTime]::UtcNow.ToString('o');finishedAt=$null;
 destination=$archive;sourceMacTemporaryArchive=$false;producerExit=$null;transportExit=$null;archiveReaderExit=$null;
 bytes=[long]0;sha256=$null;producerDigestMatched=$false;sourceWarningBytes=$null;sourceWarningTruncated=$null;targetProtected=$false;seedAccepted=$false;
 sqliteConsistentPerDatabase=$false;sqliteDatabaseCount=$null;sqliteSnapshotBytes=$null;sqliteSourcePeakRssBytes=$null;sqliteTargetVerified=$false;
 fileManifestTargetVerified=$false;fileManifestEntries=$null;fileManifestBytes=$null;socketMetadataCount=$null;socketKernelStatePreserved=$false;
 sourceWritersFrozen=$false;consistentFinalSnapshot=$false;fullMacBackup=$false;encryptedAtRest=$false;extracted=$false;errorType=$null}
try{
 if($info.Arguments.Length -gt 30000){throw 'Reviewed producer transport argument bound exceeded; retain failed run'}
 $child=[Diagnostics.Process]::Start($info)
 $copy=$child.StandardOutput.BaseStream.CopyToAsync($sink);$errorCopy=$child.StandardError.BaseStream.CopyToAsync($errors)
 if($Profile -in @('vm-dirty-work-manifest','vm-native-history-delta','vm-useful-library-delta')){
  $selectionWrite=$child.StandardInput.BaseStream.WriteAsync($selectionBytes,0,$selectionBytes.Length)
  if(-not $selectionWrite.Wait(30000)){throw 'Owned selection transfer deadline exceeded'}
  $selectionWrite.GetAwaiter().GetResult()|Out-Null
 }
 $child.StandardInput.Close()
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
  if($Profile -eq 'vm-codex-sqlite'){
   $report.sqliteConsistentPerDatabase=($receipt.consistentPerDatabase -eq $true)
   $report.sqliteDatabaseCount=$receipt.databaseCount;$report.sqliteSnapshotBytes=$receipt.databaseBytes;$report.sqliteSourcePeakRssBytes=$receipt.peakRssBytes
  }
  if($Profile -in @('vm-owner-tools-manifest','vm-dirty-work-manifest','vm-native-history-delta','vm-useful-library-delta')){
   $report.fileManifestEntries=$receipt.fileManifestEntries;$report.fileManifestBytes=$receipt.fileBytes;$report.socketMetadataCount=$receipt.socketCount
  }
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
  if($Profile -eq 'vm-codex-sqlite' -and $report.transportExit -eq 0 -and $report.producerDigestMatched){
   $checker='/mnt/c/'+$sqliteCode.Substring(3).Replace('\','/')
   $checkArgs=@('-d','Ubuntu-24.04','-u','pou','--exec','/usr/bin/timeout','240s','/usr/bin/python3','-I','-B',$checker,'--verify',('/mnt/c/ProgramData/OracovaMigration/'+$RunId+'/'+$Profile+'.tar.gz'))
   $checkInfo=[Diagnostics.ProcessStartInfo]::new($wsl,(($checkArgs|ForEach-Object {ConvertTo-MigrationNativeArgument $_}) -join ' '))
   $checkInfo.UseShellExecute=$false;$checkInfo.RedirectStandardOutput=$true;$checkInfo.RedirectStandardError=$true
   $checkChild=[Diagnostics.Process]::Start($checkInfo);$checkOut=$checkChild.StandardOutput.ReadToEndAsync()
   $checkLog=New-MigrationStreamFile (Join-Path $folder 'sqlite-check.private.log')
   try{
    $checkErrors=$checkChild.StandardError.BaseStream.CopyToAsync($checkLog);$checkChild.WaitForExit();$checkErrors.GetAwaiter().GetResult()|Out-Null
    $checked=$checkOut.GetAwaiter().GetResult()|ConvertFrom-Json
    $report.sqliteTargetVerified=($checkChild.ExitCode -eq 0 -and $checked.schema -eq 'ccrelay.memory_sqlite_target_verification.v1' -and
     $checked.verified -eq $true -and $checked.databaseCount -eq $report.sqliteDatabaseCount -and $checked.databaseBytes -eq $report.sqliteSnapshotBytes -and
     $checked.consistentPerDatabase -eq $true -and $checked.consistentFinalSnapshot -eq $false -and $checked.activeProfileChanged -eq $false -and $checked.extractedToFilesystem -eq $false)
   }finally{$checkLog.Dispose();$checkChild.Dispose()}
  }
  if($Profile -in @('vm-owner-tools-manifest','vm-dirty-work-manifest','vm-native-history-delta','vm-useful-library-delta') -and $report.transportExit -eq 0 -and $report.producerDigestMatched){
   $checker='/mnt/c/'+$ownerToolsCode.Substring(3).Replace('\','/')
   $checkArgs=@('-d','Ubuntu-24.04','-u','pou','--exec','/usr/bin/timeout','900s','/usr/bin/python3','-I','-B',$checker,'--verify',('/mnt/c/ProgramData/OracovaMigration/'+$RunId+'/'+$Profile+'.tar.gz'))
   if($Profile -in @('vm-dirty-work-manifest','vm-native-history-delta','vm-useful-library-delta')){
    if((Get-FileHash $selectionFile).Hash.ToLowerInvariant() -ne $DirtySelectionSha256){throw 'Selection changed before independent verification'}
    $selectionLinux='/mnt/c/'+$selectionFile.Substring(3).Replace('\','/')
    $verificationMode=$(if($Profile -eq 'vm-native-history-delta'){'--verify-native'}elseif($Profile -eq 'vm-useful-library-delta'){'--verify-library'}else{'--verify-dirty'})
    $checkArgs=@('-d','Ubuntu-24.04','-u','pou','--exec','/usr/bin/timeout','900s','/usr/bin/python3','-I','-B',$checker,$verificationMode,$selectionLinux,('/mnt/c/ProgramData/OracovaMigration/'+$RunId+'/'+$Profile+'.tar.gz'))
   }
   $checkInfo=[Diagnostics.ProcessStartInfo]::new($wsl,(($checkArgs|ForEach-Object {ConvertTo-MigrationNativeArgument $_}) -join ' '))
   $checkInfo.UseShellExecute=$false;$checkInfo.RedirectStandardOutput=$true;$checkInfo.RedirectStandardError=$true
   $checkChild=[Diagnostics.Process]::Start($checkInfo);$checkOut=$checkChild.StandardOutput.ReadToEndAsync()
   $checkLog=New-MigrationStreamFile (Join-Path $folder 'file-manifest-check.private.log')
   try{
    $checkErrors=$checkChild.StandardError.BaseStream.CopyToAsync($checkLog);$checkChild.WaitForExit();$checkErrors.GetAwaiter().GetResult()|Out-Null
    $checked=$checkOut.GetAwaiter().GetResult()|ConvertFrom-Json
    $report.fileManifestTargetVerified=($checkChild.ExitCode -eq 0 -and $checked.schema -eq 'ccrelay.owner_tools_target_verification.v1' -and
     $checked.verified -eq $true -and $checked.fileManifestEntries -eq $report.fileManifestEntries -and $checked.fileBytes -eq $report.fileManifestBytes -and
     $checked.socketCount -eq $report.socketMetadataCount -and $checked.socketKernelStatePreserved -eq $false -and $checked.consistentFinalSnapshot -eq $false -and
     $checked.activeProfileChanged -eq $false -and $checked.extractedToFilesystem -eq $false)
    if($Profile -in @('vm-dirty-work-manifest','vm-native-history-delta','vm-useful-library-delta')){$report.fileManifestTargetVerified=($report.fileManifestTargetVerified -and $checked.expectedSelectionMatched -eq $true)}
   }finally{$checkLog.Dispose();$checkChild.Dispose()}
  }
  $report.seedAccepted=($report.transportExit -eq 0 -and $report.producerExit -eq 0 -and $receipt.warningBytes -eq 0 -and
   $report.producerDigestMatched -and $report.targetProtected -and $report.archiveReaderExit -eq 0 -and (Get-FileHash -LiteralPath $archive).Hash.ToLowerInvariant() -eq $report.sha256)
  if($Profile -eq 'vm-codex-sqlite'){
   $report.seedAccepted=($report.seedAccepted -and $report.sqliteTargetVerified -and $report.sqliteConsistentPerDatabase -and
    $receipt.snapshotSchema -eq 'ccrelay.memory_sqlite_snapshot.v1' -and $report.sqliteDatabaseCount -ge 1 -and $report.sqliteDatabaseCount -le 32 -and
    $receipt.consistentFinalSnapshot -eq $false -and $receipt.sourceTemporaryDatabaseFiles -eq $false)
  }
  if($Profile -in @('vm-owner-tools-manifest','vm-dirty-work-manifest','vm-native-history-delta','vm-useful-library-delta')){
   $minimumEntries=$(if($Profile -in @('vm-dirty-work-manifest','vm-native-history-delta','vm-useful-library-delta')){1}else{29})
   $report.seedAccepted=($report.seedAccepted -and $report.fileManifestTargetVerified -and $receipt.fileManifestSchema -eq 'ccrelay.owner_tools_file_manifest.v1' -and
    $report.fileManifestEntries -ge $minimumEntries -and $report.fileManifestEntries -le 750000 -and $report.socketMetadataCount -ge 0 -and
    $receipt.socketKernelStatePreserved -eq $false -and $receipt.consistentFinalSnapshot -eq $false -and $receipt.sourceTemporaryFiles -eq $false)
  }
  if($Profile -in @('vm-dirty-work-manifest','vm-native-history-delta','vm-useful-library-delta')){$report.seedAccepted=($report.seedAccepted -and (Get-FileHash $selectionFile).Hash.ToLowerInvariant() -eq $DirtySelectionSha256)}
 }catch{$report.errorType=$_.Exception.GetType().Name}
}
$report.finishedAt=[DateTime]::UtcNow.ToString('o')
$result=New-MigrationStreamFile (Join-Path $folder 'result.json')
try{$body=[Text.UTF8Encoding]::new($false).GetBytes(($report | ConvertTo-Json -Compress));$result.Write($body,0,$body.Length);$result.Flush($true)}finally{$result.Dispose()}
[Console]::WriteLine(($report | ConvertTo-Json -Compress))
if(-not $report.seedAccepted){throw 'Stream not accepted; retain attempt and inspect receipt, no automatic retry'}
