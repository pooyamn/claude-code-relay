require 'minitest/autorun'
require 'tmpdir'
require 'open3'
require_relative '../capture-codex-migration-state'

class CodexMigrationSnapshot < Minitest::Test
  def test_wal_records_are_preserved_without_changing_source
    Dir.mktmpdir('ccrelay-snapshot-test-') do |scratch|
      source = File.join(scratch, 'source')
      Dir.mkdir(source, 0700)
      database = File.join(source, 'state_5.sqlite')
      # Keep the producer connection open: committed row remains in its WAL.
      Open3.popen3('sqlite3', database) do |input, output, errors, producer|
        input.puts('PRAGMA journal_mode=WAL; CREATE TABLE facts(value TEXT); INSERT INTO facts VALUES("committed"); SELECT "ready";')
        input.flush
        assert_equal 'wal', output.gets.strip
        assert_equal 'ready', output.gets.strip
        assert File.size(database + '-wal') > 0
        capture = capture_databases(source, scratch)
        backup = File.join(capture.fetch(:directory), 'state_5.sqlite')
        value, error, checked = Open3.capture3('sqlite3', '-readonly', "file:#{backup}?immutable=1", 'SELECT value FROM facts;')
        assert checked.success?, error
        assert_equal 'committed', value.strip
        assert_equal 0600, File.stat(backup).mode & 0777
        assert_equal false, capture[:consistent_final_snapshot]
        input.puts('SELECT count(*) FROM facts; PRAGMA journal_mode;')
        input.flush
        assert_equal '1', output.gets.strip
        assert_equal 'wal', output.gets.strip
        input.close
        assert producer.value.success?, errors.read
      end
    end
  end

  def test_closed_wal_database_without_companions
    Dir.mktmpdir('ccrelay-closed-wal-snapshot-') do |scratch|
      source = File.join(scratch, 'source')
      Dir.mkdir(source, 0700)
      database = File.join(source, 'memories_1.sqlite')
      _, error, made = Open3.capture3('sqlite3', database, 'PRAGMA journal_mode=WAL; CREATE TABLE facts(value TEXT); INSERT INTO facts VALUES("closed"); PRAGMA wal_checkpoint(TRUNCATE);')
      assert made.success?, error
      # Some SQLite builds persist empty companions. This closed, checkpointed
      # synthetic fixture deliberately reproduces the inactive source DB shape.
      assert_equal 0, File.size(database + '-wal') if File.exist?(database + '-wal')
      %w[-wal -shm].each { |suffix| File.unlink(database + suffix) if File.exist?(database + suffix) }
      refute File.exist?(database + '-wal')
      capture = capture_databases(source, scratch)
      backup = File.join(capture.fetch(:directory), 'memories_1.sqlite')
      value, error, checked = Open3.capture3('sqlite3', '-readonly', "file:#{backup}?immutable=1", 'SELECT value FROM facts;')
      assert checked.success?, error
      assert_equal 'closed', value.strip
    end
  end

  def test_source_symlink_is_rejected
    Dir.mktmpdir('ccrelay-snapshot-link-test-') do |scratch|
      database = File.join(scratch, 'source.sqlite')
      File.open(database, 'w') {}
      root = File.join(scratch, 'home')
      Dir.mkdir(root)
      File.symlink(database, File.join(root, 'state_5.sqlite'))
      assert_raises(RuntimeError) { capture_databases(root, scratch) }
    end
  end
end
