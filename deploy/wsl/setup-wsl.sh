#!/usr/bin/env bash
# Prepare an Ubuntu 24.04 WSL2 distro to run the relay (ccrelayd), no OpenClaw.
#
#   sudo bash setup-wsl.sh root      # once, as root: packages, user, wsl.conf
#   (in PowerShell)  wsl --shutdown   # so systemd + the default user take effect
#   bash setup-wsl.sh user            # as pouya: tools, whisper.cpp, services
#
# The user's home is /Users/pouya ON PURPOSE. Claude's project dirs, ~/.claude.json
# folder trust, relay-codes.json, session pins (cr-<md5(folder)>) and codex thread
# cwds all hold absolute paths; keeping the home path identical means none of
# them need rewriting and every topic resumes its existing session.
set -euo pipefail
U=pouya
H=/Users/$U
HERE="$(cd "$(dirname "$0")" && pwd)"

root_part() {
  apt-get update
  apt-get install -y tmux git python3 python3-venv ffmpeg lsof curl jq zip unzip \
    rsync build-essential cmake ca-certificates gnupg openssh-client
  # Node 22 (claude/codex CLIs are npm packages)
  if ! command -v node >/dev/null || [ "$(node -v | cut -c2- | cut -d. -f1)" -lt 22 ]; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -y nodejs
  fi
  # GitHub CLI
  if ! command -v gh >/dev/null; then
    install -d -m 0755 /etc/apt/keyrings
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      -o /etc/apt/keyrings/githubcli-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list
    apt-get update && apt-get install -y gh
  fi
  mkdir -p /Users
  if ! id "$U" >/dev/null 2>&1; then
    useradd -m -d "$H" -s /bin/bash "$U"
    usermod -aG sudo "$U"
    echo "set a password for $U:"; passwd "$U"
  fi
  cat > /etc/wsl.conf <<EOF
[boot]
systemd=true

[user]
default=$U
EOF
  # user services run at boot without an interactive login
  loginctl enable-linger "$U" 2>/dev/null || echo "run 'loginctl enable-linger $U' after the restart"
  echo "root part done. In Windows PowerShell: wsl --shutdown, then reopen and run: bash $0 user"
}

user_part() {
  [ "$HOME" = "$H" ] || { echo "run as $U (HOME must be $H)"; exit 1; }
  mkdir -p ~/.local/bin ~/.npm-global ~/.config/ccrelay ~/.config/systemd/user
  npm config set prefix ~/.npm-global
  grep -q npm-global ~/.bashrc || echo 'export PATH="$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"' >> ~/.bashrc
  export PATH="$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"

  command -v claude >/dev/null || curl -fsSL https://claude.ai/install.sh | bash
  command -v codex  >/dev/null || npm i -g @openai/codex

  # whisper.cpp for voice notes (models come over with the data, ~/.openclaw/whisper-models)
  if ! command -v whisper-cli >/dev/null; then
    rm -rf /tmp/whisper.cpp && git clone --depth 1 https://github.com/ggml-org/whisper.cpp /tmp/whisper.cpp
    cmake -S /tmp/whisper.cpp -B /tmp/whisper.cpp/build -DCMAKE_BUILD_TYPE=Release
    cmake --build /tmp/whisper.cpp/build -j"$(nproc)" --target whisper-cli
    install -m 0755 /tmp/whisper.cpp/build/bin/whisper-cli ~/.local/bin/whisper-cli
  fi

  # freeze renders TUI screenshots (cc shot); optional
  if ! command -v freeze >/dev/null; then
    v=$(curl -fsSL https://api.github.com/repos/charmbracelet/freeze/releases/latest | jq -r .tag_name)
    curl -fsSL "https://github.com/charmbracelet/freeze/releases/download/$v/freeze_${v#v}_Linux_x86_64.tar.gz" \
      | tar -xz -C /tmp && install -m 0755 /tmp/freeze_*/freeze ~/.local/bin/freeze || echo "freeze: skipped"
  fi

  cp "$HERE"/systemd/* ~/.config/systemd/user/
  systemctl --user daemon-reload
  echo
  echo "Tools installed. Next, by hand (they need a browser/your account):"
  echo "  claude          # log in (macOS kept this in the Keychain, it cannot be copied)"
  echo "  codex login"
  echo "  gh auth login"
  echo "Then bring the data over (pull-from-mac.sh) and run: bash $0 enable"
}

enable_part() {
  [ -f ~/.config/ccrelay/prod.json ] || { echo "missing ~/.config/ccrelay/prod.json (see README)"; exit 1; }
  systemctl --user enable --now relay-openrouter-proxy.service codex-remote-ensure.timer relay-staleenv.timer
  systemctl --user enable --now ccrelayd.service
  systemctl --user --no-pager status ccrelayd.service | head -5
}

case "${1:-}" in
  root)   [ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }; root_part ;;
  user)   user_part ;;
  enable) enable_part ;;
  *) echo "usage: $0 root|user|enable"; exit 1 ;;
esac
