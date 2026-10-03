#!/usr/bin/env ruby
# File-based SFTP transfer keeps binary archive data out of Windows Console stdin.
# Transport workaround: the diagnostic framed stream stalls on bulk traffic;
# this does not claim that upstream transport is fixed. Each component keeps a private local archive and
# a protected PC copy, with post-copy byte/hash verification and no extraction.
require 'tmpdir'
require 'base64'
require 'digest'
require 'json'
require 'open3'
require 'optparse'
require 'time'

def validated_options(argv)
  options = { host: 'pou@10.0.0.35', control: '/tmp/ccrelay-pc-ssh-control.qUtMFa/control' }
  OptionParser.new do |p|
    p.on('--run ID') { |v| options[:run] = v }
    p.on('--label LABEL') { |v| options[:label] = v }
    p.on('--root PATH') { |v| options[:root] = v }
    p.on('--control PATH') { |v| options[:control] = v }
    p.on('--host HOST') { |v| options[:host] = v }
  end.parse!(argv)
  raise 'Invalid run ID' unless options[:run]&.match?(/\A[0-9a-f]{32}\z/)
  raise 'Invalid label' unless options[:label]&.match?(/\A[a-z][a-z0-9-]{0,63}\z/)
  raise 'Expected PC destination' unless options[:host] == 'pou@10.0.0.35'
  root = options[:root]
  raise 'Literal existing absolute root required' unless root && root.start_with?('/') && File.directory?(root)
  canonical = File.realpath(root)
  raise 'Do not archive a filesystem root' if ['/', '/Users'].include?(canonical)
  raise 'Source root cannot be a symlink' if File.symlink?(root)
  raise 'Explicit relative members required' if argv.empty?
  raise 'Select operational records, not the entire owner home' if canonical == '/Users/pouya' && argv.include?('.')
  argv.each do |member|
    raise 'Unsafe source member' if member.start_with?('/', '-') || member.split('/').include?('..') || member.include?("\0")
    raise 'Missing source member' unless File.exist?(File.join(root, member)) || File.symlink?(File.join(root, member))
  end
  options[:members] = argv
  options
end

def copy_archive(options)
  # Keep generated archives outside every source root, regardless of TMPDIR.
  scratch = Dir.mktmpdir('ccrelay-migration-archive-', '/tmp')
  archive = File.join(scratch, options[:label] + '.tar.gz')
  errors = File.join(scratch, 'producer.stderr.private')
  # Scratch is 0700; payload/output files are 0600 before tar writes anything.
  File.open(archive, File::WRONLY | File::CREAT | File::EXCL, 0600) {}
  File.open(errors, File::WRONLY | File::CREAT | File::EXCL, 0600) {}
  started = Time.now.utc.iso8601
  pid = Process.spawn({ 'COPYFILE_DISABLE' => '1' }, 'tar', '--options', 'gzip:compression-level=1', '-czf', archive,
                      '-C', options[:root], '--', *options[:members], err: errors)
  puts JSON.generate(stage: 'capturing', run: options[:run], label: options[:label],
                     producer_pid: pid, local_archive: archive)
  STDOUT.flush
  _, status = Process.wait2(pid)
  size = File.size(archive)
  hash = Digest::SHA256.file(archive).hexdigest
  ssh = ['ssh', '-S', options[:control], '-o', 'BatchMode=yes', '-T', options[:host]]
  remote = "C:\\ProgramData\\OracovaMigration\\#{options[:run]}\\#{options[:label]}-sftp.tar.gz"
  # Reserve a new administrator-owned file before SFTP writes, so the ordinary
  # owner cannot rewrite its ACL during transfer. Never overwrite source work.
  prepare = <<~PS
    $ErrorActionPreference="Stop";$ProgressPreference="SilentlyContinue";
    $d="C:\\ProgramData\\OracovaMigration\\#{options[:run]}";
    if(-not (Test-Path -LiteralPath $d)){throw "Missing protected migration run"};
    $a=Get-Acl $d;if($a.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne "S-1-5-32-544"){throw "Unexpected run owner"};
    $p="#{remote}";$acl=[Security.AccessControl.FileSecurity]::new();$acl.SetOwner([Security.Principal.SecurityIdentifier]::new("S-1-5-32-544"));$acl.SetAccessRuleProtection($true,$false);
    foreach($sid in @("S-1-5-18","S-1-5-32-544")){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),"FullControl","Allow"))};
    $f=[IO.FileStream]::new($p,[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::None,4096,[IO.FileOptions]::None,$acl);$f.Dispose();
    [Console]::WriteLine("RESERVED");
  PS
  encoded = Base64.strict_encode64(prepare.encode('UTF-16LE'))
  output, error, prepared = Open3.capture3(*ssh, 'powershell', '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded)
  raise 'Target reservation failed; preserve source archive' unless prepared.success? && output.include?('RESERVED')
  puts JSON.generate(stage: 'copying', label: options[:label], bytes: size, sha256: hash,
                     producer_exit: status.exitstatus, destination: remote)
  STDOUT.flush
  _, _, copied = Open3.capture3('scp', '-o', "ControlPath=#{options[:control]}", '-o', 'BatchMode=yes',
                               archive, "#{options[:host]}:#{remote.tr('\\', '/')}")
  verify = <<~PS
    $ErrorActionPreference="Stop";$ProgressPreference="SilentlyContinue";
    $p="#{remote}";$a=Get-Acl -LiteralPath $p;
    $pi=[Diagnostics.ProcessStartInfo]::new();$pi.FileName="C:\\Windows\\System32\\wsl.exe";$pi.Arguments="-d Ubuntu-24.04 -u pou -- tar -tzf /mnt/c/ProgramData/OracovaMigration/#{options[:run]}/#{options[:label]}-sftp.tar.gz";$pi.UseShellExecute=$false;$pi.RedirectStandardOutput=$true;$pi.RedirectStandardError=$true;
    $child=[Diagnostics.Process]::Start($pi);$drain=$child.StandardOutput.BaseStream.CopyToAsync([IO.Stream]::Null);$err=$child.StandardError.ReadToEndAsync();$child.WaitForExit();$drain.GetAwaiter().GetResult();$tarError=$err.GetAwaiter().GetResult();
    $report=[ordered]@{run="#{options[:run]}";label="#{options[:label]}";path=$p;bytes=(Get-Item -LiteralPath $p).Length;sha256=(Get-FileHash -LiteralPath $p).Hash.ToLowerInvariant();owner=$a.GetOwner([Security.Principal.SecurityIdentifier]).Value;protected=$a.AreAccessRulesProtected;
    grants=@($a.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])|ForEach-Object {$_.IdentityReference.Value});archiveReader="WSL GNU tar";tarExit=$child.ExitCode;tarWarning=($tarError.Length -gt 0);sourceProducerExit=#{status.exitstatus};consistentFinalSnapshot=$false;extracted=$false};
    $acl=[Security.AccessControl.FileSecurity]::new();$acl.SetOwner([Security.Principal.SecurityIdentifier]::new("S-1-5-32-544"));$acl.SetAccessRuleProtection($true,$false);foreach($sid in @("S-1-5-18","S-1-5-32-544")){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),"FullControl","Allow"))};
    $receipt="C:\\ProgramData\\OracovaMigration\\#{options[:run]}\\#{options[:label]}-sftp.verified.json";$f=[IO.FileStream]::new($receipt,[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::None,4096,[IO.FileOptions]::None,$acl);try{$b=[Text.Encoding]::UTF8.GetBytes(($report|ConvertTo-Json -Compress));$f.Write($b,0,$b.Length);$f.Flush($true)}finally{$f.Dispose()};
    $report|ConvertTo-Json -Compress;
  PS
  encoded = Base64.strict_encode64(verify.encode('UTF-16LE'))
  output, _, checked = Open3.capture3(*ssh, 'powershell', '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded)
  report_line = output.lines.reverse.find { |line| line.start_with?('{') }
  report = report_line && JSON.parse(report_line)
  matched = report && report['bytes'] == size && report['sha256'] == hash
  protected = report && report['owner'] == 'S-1-5-32-544' && report['protected'] &&
              (report['grants'] - ['S-1-5-18', 'S-1-5-32-544']).empty?
  archive_readable = report && report['tarExit'] == 0
  result = {schema: 'ccrelay.migration.sftp.v1', run: options[:run], label: options[:label],
            started_at: started, finished_at: Time.now.utc.iso8601, source_root: options[:root],
            members: options[:members], local_archive: archive, destination: remote, bytes: size, sha256: hash,
            producer_exit: status.exitstatus, sftp_exit: copied.exitstatus, verification_exit: checked.exitstatus,
            digest_matched: !!matched, protected_target: !!protected, archive_readable: !!archive_readable,
            seed_transfer_accepted: !!(status.success? && copied.success? && checked.success? && matched && protected && archive_readable),
            producer_warnings: File.size(errors) > 0, consistent_final_snapshot: false, extracted: false}
  File.open(File.join(scratch, 'result.json'), File::WRONLY | File::CREAT | File::EXCL, 0600) { |f| f.write(JSON.generate(result)) }
  puts JSON.generate(result)
  result[:seed_transfer_accepted] ? 0 : 1
end

if $PROGRAM_NAME == __FILE__
  begin
    exit copy_archive(validated_options(ARGV))
  rescue StandardError => e
    warn JSON.generate(error_type: e.class.name, message: 'File transfer failed; retain archive and reconcile before another attempt')
    exit 1
  end
end
