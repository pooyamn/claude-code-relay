#!/usr/bin/env ruby
# SQLite's backup API includes committed WAL records without stopping a daemon.
# Each DB has its own consistent snapshot; cross-DB/final topic cutover still
# needs reconciliation. No credentials, conversations or rows are printed.
require 'tmpdir'
require 'open3'
require 'json'
require 'digest'
require 'time'

def capture_databases(root, parent = '/tmp')
  raise 'Literal existing source directory required' unless File.directory?(root) && !File.symlink?(root)
  databases = Dir.children(root).select { |name| name.match?(/\A[a-z][a-z0-9_]*\.sqlite\z/) }.sort
  raise 'No SQLite databases found' if databases.empty?
  scratch = Dir.mktmpdir('ccrelay-codex-snapshot-', parent)
  records = []
  databases.each do |name|
    source = File.join(root, name)
    raise 'Source DB must be a regular file, not a symlink' unless File.file?(source) && !File.symlink?(source)
    destination = File.join(scratch, name)
    File.open(destination, File::WRONLY | File::CREAT | File::EXCL, 0600) {}
    started = Time.now.utc.iso8601
    # Opening an inactive WAL DB read-only failed on the Mac when its WAL/SHM
    # companions were absent. A normal SQLite connection can initialize those
    # support files. query_only prevents SQL data writes on this connection;
    # the backup API writes only the new destination DB, not source tables.
    output, error, status = Open3.capture3('sqlite3', '-cmd', 'PRAGMA query_only=ON;', source, ".backup '#{destination}'")
    File.open(File.join(scratch, name + '.backup.private.log'), File::WRONLY | File::CREAT | File::EXCL, 0600) do |file|
      file.write(output); file.write(error)
    end
    raise 'SQLite snapshot failed; retain attempt' unless status.success?
    # The backup child has closed this standalone snapshot. Explicit immutable
    # read verification cannot create ancillary WAL/SHM files beside it. Never
    # apply immutable=1 to the live source DB, whose WAL still contains records.
    check, error, checked = Open3.capture3('sqlite3', '-readonly', "file:#{destination}?immutable=1", 'PRAGMA quick_check;')
    File.open(File.join(scratch, name + '.check.private.log'), File::WRONLY | File::CREAT | File::EXCL, 0600) do |file|
      file.write(check); file.write(error)
    end
    raise 'SQLite snapshot failed integrity check; retain attempt' unless checked.success? && check.strip == 'ok' && error.empty?
    records << { name: name, bytes: File.size(destination), sha256: Digest::SHA256.file(destination).hexdigest,
                 started_at: started, finished_at: Time.now.utc.iso8601, quick_check: 'ok' }
  end
  receipt = {schema: 'ccrelay.migration.sqlite_snapshot.v1', directory: scratch, databases: records,
             consistent_per_database: true, consistent_final_snapshot: false,
             source_writers_stopped: false, models_started: false}
  File.open(File.join(scratch, 'capture.json'), File::WRONLY | File::CREAT | File::EXCL, 0600) { |file| file.write(JSON.generate(receipt)) }
  receipt
end

if $PROGRAM_NAME == __FILE__
  begin
    raise 'This entry point captures the literal owner Codex home only' unless ARGV.empty?
    puts JSON.generate(capture_databases('/Users/pouya/.codex'))
  rescue StandardError => e
    warn JSON.generate(error_type: e.class.name, message: 'Snapshot failed; retain generated attempt for reconciliation')
    exit 1
  end
end
