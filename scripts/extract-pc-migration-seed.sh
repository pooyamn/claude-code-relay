#!/usr/bin/env bash
# Restore an initial PC seed as the ordinary personal owner, never as root.
# Archives remain immutable rollback inputs. No models, hooks or services start.
set -euo pipefail
umask 077

validate_arguments() {
  [[ $# -eq 4 ]] || { echo 'Expected run, component, SHA256 and byte count' >&2; return 2; }
  [[ $1 =~ ^[a-f0-9]{32}$ ]] || { echo 'Invalid run' >&2; return 2; }
  case "$2" in
    workspace-file|claude-home-file|codex-home-file|codex-sqlite-snapshot|openclaw-media|openclaw-state) ;;
    *) echo 'Unknown component' >&2; return 2 ;;
  esac
  [[ $3 =~ ^[a-f0-9]{64}$ ]] || { echo 'Invalid digest' >&2; return 2; }
  [[ $4 =~ ^[1-9][0-9]{0,14}$ ]] || { echo 'Invalid size' >&2; return 2; }
}

extract_seed() {
  validate_arguments "$@"
  local run=$1 component=$2 digest=$3 bytes=$4
  local owner_root=/Users/pouya
  [[ $(id -u) == 1000 && $(id -un) == pou ]] || { echo 'Ordinary PC owner required' >&2; return 2; }
  [[ $(stat -c '%u:%a' "$owner_root") == 1000:700 && ! -L $owner_root ]] || {
    echo 'Private owner home required' >&2; return 2;
  }
  local archive="/mnt/c/ProgramData/OracovaMigration/$run/$component-sftp.tar.gz"
  [[ -f $archive && ! -L $archive ]] || { echo 'Expected staged archive' >&2; return 2; }
  [[ $(stat -c '%s' "$archive") == "$bytes" ]] || { echo 'Archive size mismatch' >&2; return 2; }
  [[ $(sha256sum "$archive" | cut -d' ' -f1) == "$digest" ]] || { echo 'Archive digest mismatch' >&2; return 2; }

  local ledger_root="$owner_root/.migration/$run" parent destination
  case "$component" in
    workspace-file) parent="$owner_root/.openclaw"; destination="$parent/workspace" ;;
    openclaw-media) parent="$owner_root/.openclaw"; destination="$parent/media" ;;
    *) parent="$ledger_root/native-seeds"; destination="$parent/$component" ;;
  esac
  # Resolve every ancestor before creating or writing beneath it. A source
  # symlink may exist inside the restored project; it cannot redirect the ledger.
  local check part tree
  local -a parts
  for tree in "$parent" "$ledger_root"; do
    check=$owner_root
    IFS=/ read -ra parts <<< "${tree#"$owner_root/"}"
    for part in "${parts[@]}"; do
      check="$check/$part"
      [[ ! -L $check ]] || { echo 'Destination ancestor is a symlink' >&2; return 2; }
      [[ ! -e $check || -d $check ]] || { echo 'Destination ancestor is not a directory' >&2; return 2; }
    done
  done
  [[ ! -e $destination && ! -L $destination ]] || { echo 'Existing destination preserved' >&2; return 2; }
  mkdir -p "$ledger_root" "$parent"
  [[ $(stat -c '%u:%a' "$ledger_root") == 1000:700 ]] || { echo 'Private ledger required' >&2; return 2; }
  # One extraction at a time. A lost observation does not start another writer.
  exec 9>"$ledger_root/extraction.lock"
  flock -n 9 || { echo 'Another extraction is running' >&2; return 2; }
  [[ ! -e "$ledger_root/$component.started.json" ]] || { echo 'Existing attempt must be reconciled' >&2; return 2; }
  local scratch
  scratch=$(mktemp -d "$ledger_root/$component.extract.XXXXXX")
  printf '{"component":"%s","pid":%s,"scratch":"%s","startedAt":"%s","consistentFinalSnapshot":false}\n' \
    "$component" "$$" "$scratch" "$(date -u +%FT%TZ)" > "$ledger_root/$component.started.json"
  printf 'Extracting %s as UID 1000; private attempt %s\n' "$component" "$scratch"
  mkdir "$scratch/payload"
  # GNU tar's default traversal checks stay enabled. Ownership is not restored;
  # the private umask applies and no archive-supplied hooks run. Keep diagnostics.
  if ! tar --extract --gzip --file "$archive" --directory "$scratch/payload" \
      --no-same-owner --no-same-permissions --delay-directory-restore \
      > "$scratch/stdout.private" 2> "$scratch/stderr.private"; then
    echo 'Extraction failed; retained partial attempt and untouched archive' >&2
    return 1
  fi
  [[ $(stat -c '%u' "$scratch/payload") == 1000 ]] || { echo 'Unexpected restored owner' >&2; return 1; }
  # -n never replaces a target that appeared after the initial check. Detect its
  # otherwise-successful no-op, retaining the attempt instead of declaring success.
  mv -T -n "$scratch/payload" "$destination"
  [[ ! -e "$scratch/payload" ]] || { echo 'Target appeared; preserved both copies' >&2; return 1; }
  printf '{"component":"%s","sha256":"%s","archiveBytes":%s,"destination":"%s","uid":1000,"finishedAt":"%s","consistentFinalSnapshot":false,"modelsStarted":false}\n' \
    "$component" "$digest" "$bytes" "$destination" "$(date -u +%FT%TZ)" > "$ledger_root/$component.extracted.json"
  printf 'Extracted %s to %s; seed only, no native session launched\n' "$component" "$destination"
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  extract_seed "$@"
fi
