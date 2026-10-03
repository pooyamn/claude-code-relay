require 'minitest/autorun'
require 'tmpdir'
require_relative '../copy-pc-migration'

class PcMigrationCopyTest < Minitest::Test
  def setup
    @root = Dir.mktmpdir('ccrelay-migration-options-')
    File.write(File.join(@root, 'source.txt'), 'fixture')
    @base = ['--run', 'a' * 32, '--label', 'fixture', '--root', @root]
  end

  def teardown
    # Only this test's validated temporary files, never source/target archives.
    File.unlink(File.join(@root, 'source.txt'))
    Dir.rmdir(@root)
  end

  def test_valid_literal_member
    assert_equal ['source.txt'], validated_options(@base + ['source.txt'])[:members]
  end

  def test_rejects_parent_traversal_and_shell_option
    ['../source.txt', '/etc/passwd', '--checkpoint', 'nested/../../x'].each do |name|
      assert_raises(RuntimeError) { validated_options(@base + [name]) }
    end
  end

  def test_rejects_missing_member
    assert_raises(RuntimeError) { validated_options(@base + ['missing']) }
  end

  def test_requires_explicit_members
    assert_raises(RuntimeError) { validated_options(@base) }
  end

  def test_rejects_unexpected_destination
    assert_raises(RuntimeError) { validated_options(@base + ['--host', 'other@host', 'source.txt']) }
  end

  def test_rejects_unsafe_labels
    ['../x', 'a;command', 'A', 'x' * 65].each do |label|
      assert_raises(RuntimeError) { validated_options(@base + ['--label', label, 'source.txt']) }
    end
  end
end
