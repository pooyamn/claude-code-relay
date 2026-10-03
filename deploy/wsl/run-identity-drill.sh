#!/bin/sh
# Credential-free transient acceptance fixture, NOT a role installer.
# Inspect/hash this artifact before invoking it as trusted root on the target.
set -eu
if [ "${1-}" != "--run" ]; then
  exec /usr/bin/python3 -I "$(dirname "$0")/identity-drill.py"
fi
[ "$(id -u)" = 0 ] || { echo 'trusted fixture root required' >&2; exit 1; }
drill_source="$(dirname "$0")/identity-drill.py"
[ -f "$drill_source" ] && [ ! -L "$drill_source" ] || exit 1
drill_code="$(readlink -f "$drill_source")"
drill_id="$(cut -c1-8 /proc/sys/kernel/random/uuid)$(cut -c1-4 /proc/sys/kernel/random/uuid)"
drill_unit="ccrelay-identity-proof-$drill_id"
[ ! -e "/run/$drill_unit" ] || { echo 'existing fixture state refused' >&2; exit 1; }
exec /usr/bin/systemd-run --unit="$drill_unit" --wait --pipe --collect \
  --property=Type=exec --property=User=root --property=Group=root \
  --property="RuntimeDirectory=$drill_unit" --property=RuntimeDirectoryMode=0755 \
  --property=RuntimeMaxSec=30s --property=TimeoutStopSec=2s \
  --property=MemoryMax=128M --property=TasksMax=24 --property=CPUQuota=100% \
  --property=UMask=0077 --property=NoNewPrivileges=yes \
  --property='CapabilityBoundingSet=CAP_CHOWN CAP_DAC_OVERRIDE CAP_SETUID CAP_SETGID CAP_SETPCAP CAP_KILL' \
  --property=AmbientCapabilities=CAP_SETUID --property=PrivateTmp=yes \
  --property=PrivateDevices=yes --property=PrivateNetwork=yes \
  --property=ProtectSystem=strict --property=ProtectHome=yes \
  --property=ProtectControlGroups=yes --property=ProtectKernelTunables=yes \
  --property=ProtectKernelModules=yes --property=ProtectProc=invisible \
  --property=RestrictNamespaces=yes --property=RestrictSUIDSGID=yes \
  --property=RestrictAddressFamilies=AF_UNIX --property=Delegate=no \
  --property=KillMode=control-group \
  --property='InaccessiblePaths=-/mnt -/init -/run/WSL -/usr/lib/wsl -/proc/sys/fs/binfmt_misc' \
  /usr/bin/python3 -I "$drill_code" --run --fixture-root "/run/$drill_unit"
