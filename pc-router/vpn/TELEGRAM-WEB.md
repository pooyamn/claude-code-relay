# Telegram WEB proxy on the PC

Installed 2026-10-19, independent of existing MTProto and VPN services.

Path: Telegram HTTPS carrier → Cloudflare → existing named Windows tunnel →
WSL loopback `127.0.0.1:18180` → Telemt → Telegram DCs.

Public endpoint: `https://kk.fidior.com/telegram/web/`. Ordinary or unauthenticated
requests return a no-store decoy 404; an HTTP 200 alone is not a health check.

## Pinned upstream

- Telemt 3.5.14, release commit `9d5b896bb695c55e2905b82f276da84e45a0a2ec`.
- Linux amd64 GNU archive SHA256:
  `b10f86c6851f5c422a49d98deea55e8ef4aea7879605e59c1d4aa43c8f4c70ce`.
- This is the version pinned by Hiddify Manager v14.0.2. No full Manager installer
  was run and no existing VPN listeners, subscriptions, secrets or DNS changed.
- [Upstream WEB contract](https://github.com/telemt/telemt/blob/3.5.14/docs/WEB/WEB_PROXY.en.md).

## Runtime and credentials

- Systemd unit: `oracova-telegram-web.service`, enabled, `Restart=always`.
- Dedicated non-login account: `oracova-tgweb`; read-only system/home sandbox,
  512 MiB memory ceiling. Existing Windows WSL host task starts the distro at
  logon and keeps it available. A machine reboot was not performed for this change.
- Root-owned binary and immutable decoy: `/opt/oracova-telegram-web/`.
- Destination-generated config: `/etc/oracova-telegram-web/telemt.toml`, 0640.
- Owner-only import link: `/etc/oracova-telegram-web/owner-link.txt`, 0600.
  Do not commit it or include it in diagnostic logs.
- Control API: `127.0.0.1:19191`, bearer authentication, read-only, never routed
  through the public tunnel. Generated bridge credentials are not logged.
- Fixed `https` carrier for current iOS compatibility, `dd` secret; negotiation
  disabled. Native app acceptance remains separate from the protocol health test.

## Route change and rollback

`enable-telegram-web-route.ps1` validates the existing listener from Windows,
adds only the exact hostname/path rule `^/telegram/web(/|$)` before existing
ingress rules, validates with cloudflared, checks for concurrent edits and
atomically replaces the configuration. No DNS/API credentials were needed.

Protected original tunnel config is in:
`C:\ProgramData\OracovaVPN-20261003-FA9g4b\telegram-web-route-fb34b88fabde480abe61d7212eb8a479\`.

To roll back, first inspect current ingress for later edits, remove only the
WEB rule (or restore that snapshot if no subsequent edits), validate, and restart
only `OracovaCloudflare`. Disable the new Linux unit; preserve its owner secret
for recovery. Do not touch the old MTProto services or restore flagged mtg binaries.

## Verification

Run `test_telegram_web.py` as WSL root, optionally with `--private`. The test
derives a bridge capability in memory, checks no-store and the HELLO/WELCOME
contract, opens an authenticated inner MTProxy stream, sends `req_pq_multi`,
validates Telegram's `resPQ` constructor and nonce, then closes the session.
No Telegram account login or messages are involved. Never print raw exceptions
or HTTP request headers, which can contain credentials.

Initial results: private 0.294 s; public Cloudflare HTTPS 0.729 s, both authenticated
and Telegram nonce verified. These are handshake durations, not bandwidth or
measurements from the user's phone/location. Public responses negotiated HTTP/2,
valid TLS, `CF-Cache-Status: DYNAMIC`, and `Cache-Control: no-store`.

Crash recovery was exercised by killing only this unit's main process. Systemd
started a new PID (`NRestarts=1`); after its initialization the public authenticated
Telegram probe passed again in 0.750 s. The startup/restart interval briefly
returns 502 until the private listener is ready. All seven existing Windows VPN,
subscription and Cloudflare services remained running. Three serialization and
truncation regression tests pass in `scripts/tests/test_telegram_web_probe.py`.

Installation source: `install_telegram_web.py`. It refuses an existing installation
instead of silently overwriting config/secrets. Use a reviewed upgrade procedure
and repeat protocol tests for subsequent releases.
