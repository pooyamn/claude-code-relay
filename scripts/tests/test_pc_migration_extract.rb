require 'minitest/autorun'
require 'open3'

class MigrationExtractionArguments < Minitest::Test
  SCRIPT = File.expand_path('../extract-pc-migration-seed.sh', __dir__)
  RUN = '35d21d73d97ad5411f82033a86562528'
  HASH = 'a' * 64

  def valid?(*args)
    # Only validate arguments; never invoke extraction during these tests.
    _, _, status = Open3.capture3('bash', '-c', 'source "$1"; shift; validate_arguments "$@"', 'test', SCRIPT, *args)
    status.success?
  end

  def test_known_components
    %w[workspace-file claude-home-file codex-home-file codex-sqlite-snapshot openclaw-media openclaw-state].each do |component|
      assert valid?(RUN, component, HASH, '22649280767')
    end
  end

  def test_rejects_other_component_or_traversal
    %w[../../home owner-home config].each { |component| refute valid?(RUN, component, HASH, '1') }
  end

  def test_rejects_invalid_run
    refute valid?('../run', 'workspace-file', HASH, '1')
  end

  def test_rejects_invalid_digest
    refute valid?(RUN, 'workspace-file', 'unverified', '1')
  end

  def test_rejects_invalid_size
    %w[0 -1 1e6].each { |size| refute valid?(RUN, 'workspace-file', HASH, size) }
  end
end
