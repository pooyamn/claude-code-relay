#!/usr/bin/env bash
# Personal-owner migration preparation, not the deferred role/broker runtime.
# Installs pinned native builds without starting a session or changing logins.
set -euo pipefail
umask 077
[[ $(id -u) == 1000 && $(id -un) == pou ]] || { echo 'Ordinary PC owner required' >&2; exit 2; }
owner_root=/Users/pouya
[[ $(stat -c '%u:%a' "$owner_root") == 1000:700 && ! -L $owner_root ]] || exit 2
install_root="$owner_root/.local/share/pc-migration-native"
for path in "$owner_root/.local" "$owner_root/.local/share" "$install_root"; do
  [[ ! -L $path && ( ! -e $path || -d $path ) ]] || { echo 'Unexpected installation ancestor' >&2; exit 2; }
done
[[ ! -e $install_root ]] || { echo 'Existing native installation preserved' >&2; exit 2; }
mkdir -p "$install_root"
printf 'Preparing pinned Codex 0.160.0 and Claude 2.1.288 as UID 1000\n'

codex_root="$install_root/codex-0.160.0"
mkdir "$codex_root"
curl --fail --location --proto '=https' --tlsv1.2 --max-time 300 \
  https://github.com/openai/codex/releases/download/rust-v0.160.0/codex-package-x86_64-unknown-linux-musl.tar.gz \
  --output "$codex_root/package.tar.gz" 2> "$codex_root/download.private.log"
[[ $(sha256sum "$codex_root/package.tar.gz" | cut -d' ' -f1) == \
  4fcc47ab57f52ff75363951a8761146cd10c8288bd86fed45487dbb204a16b71 ]] || {
  echo 'Codex package digest mismatch; do not execute' >&2; exit 1;
}
mkdir "$codex_root/package"
tar -xzf "$codex_root/package.tar.gz" -C "$codex_root/package" --no-same-owner --no-same-permissions

claude_root="$install_root/claude-2.1.288"
mkdir "$claude_root" "$claude_root/gnupg"
base=https://downloads.claude.ai/claude-code-releases/2.1.288
curl --fail --location --proto '=https' --tlsv1.2 --max-time 120 \
  https://downloads.claude.ai/keys/claude-code.asc --output "$claude_root/signing-key.asc" \
  2> "$claude_root/key-download.private.log"
gpg --homedir "$claude_root/gnupg" --batch --import "$claude_root/signing-key.asc" \
  > "$claude_root/key-import.private.log" 2>&1
fingerprint=$(gpg --homedir "$claude_root/gnupg" --batch --with-colons --fingerprint security@anthropic.com \
  | awk -F: '$1 == "fpr" { print $10; exit }')
[[ $fingerprint == 31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE ]] || {
  echo 'Anthropic signing-key fingerprint mismatch; do not execute' >&2; exit 1;
}
for name in manifest.json manifest.json.sig; do
  curl --fail --location --proto '=https' --tlsv1.2 --max-time 120 \
    "$base/$name" --output "$claude_root/$name" 2> "$claude_root/$name.download.private.log"
done
gpg --homedir "$claude_root/gnupg" --batch --verify "$claude_root/manifest.json.sig" "$claude_root/manifest.json" \
  > "$claude_root/signature.private.log" 2>&1
checksum=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["version"]=="2.1.288"; print(d["platforms"]["linux-x64"]["checksum"])' "$claude_root/manifest.json")
[[ $checksum == 0298068b686e7fdbaf9402a7a587bb7f49c0b0e084de09f69145a0719207640c ]] || {
  echo 'Unexpected signed Claude release digest; do not execute' >&2; exit 1;
}
curl --fail --location --proto '=https' --tlsv1.2 --max-time 300 \
  "$base/linux-x64/claude" --output "$claude_root/claude" 2> "$claude_root/binary-download.private.log"
[[ $(sha256sum "$claude_root/claude" | cut -d' ' -f1) == "$checksum" ]] || {
  echo 'Claude binary digest mismatch; do not execute' >&2; exit 1;
}
chmod 700 "$claude_root/claude"
DISABLE_AUTOUPDATER=1 DISABLE_UPDATES=1 "$claude_root/claude" --version
printf 'Native downloads verified; Codex package at %s; no sessions or logins started\n' "$codex_root/package"
