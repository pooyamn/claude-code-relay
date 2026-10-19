"""Install an isolated, pinned Telemt WEB-only service (run as WSL root).

Does not install Hiddify Manager or alter existing VPN listeners/firewall rules.
Secrets are generated on the destination, never accepted in command arguments.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import pwd
import secrets
import socket
import subprocess
import sys
import tarfile

VERSION = '3.5.14'
ARCHIVE_SHA256 = 'b10f86c6851f5c422a49d98deea55e8ef4aea7879605e59c1d4aa43c8f4c70ce'
HOST = 'kk.fidior.com'
BASE = 'telegram/web'
PORT = 18180
ROOT = Path('/opt/oracova-telegram-web')
CONFIG = Path('/etc/oracova-telegram-web')
UNIT = Path('/etc/systemd/system/oracova-telegram-web.service')
ACCOUNT = 'oracova-tgweb'


def write(path, content, mode=0o644, gid=0):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, 'w') as output:
        output.write(content)
    os.chown(path, 0, gid)
    os.chmod(path, mode)


def main(archive):
    if os.geteuid() != 0:
        raise RuntimeError('root required')
    if ROOT.exists() or CONFIG.exists() or UNIT.exists():
        raise RuntimeError('existing installation: inspect before changing')
    if hashlib.sha256(Path(archive).read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise RuntimeError('upstream archive checksum mismatch')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', PORT))
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 19191))
    public_ip = socket.gethostbyname(HOST)
    try:
        pwd.getpwnam(ACCOUNT)
    except KeyError:
        subprocess.run(['useradd', '--system', '--no-create-home', '--shell', '/usr/sbin/nologin', ACCOUNT], check=True)
    gid = pwd.getpwnam(ACCOUNT).pw_gid
    ROOT.mkdir(mode=0o755)
    CONFIG.mkdir(mode=0o750)
    os.chown(CONFIG, 0, gid)
    with tarfile.open(archive, 'r:gz') as package:
        if [member.name for member in package.getmembers()] != ['telemt']:
            raise RuntimeError('unexpected archive members')
        member = package.getmember('telemt')
        if not member.isfile():
            raise RuntimeError('binary must be a regular file')
        binary = package.extractfile(member).read()
        (ROOT / 'telemt').write_bytes(binary)
        (ROOT / 'telemt').chmod(0o755)
    (ROOT / 'public').mkdir(mode=0o755)
    write(ROOT / 'public' / 'index.html', '<!doctype html><html lang="en"><title>Connection</title><p>Connection service.</p></html>\n')
    secret = secrets.token_hex(16)
    api_token = secrets.token_urlsafe(32)
    document = f'''[general]
use_middle_proxy = false
log_level = "normal"

[general.modes]
classic = false
secure = true
tls = false

[general.links]
show = []

[access.users]
owner = "{secret}"

[[server.listeners]]
ip = "127.0.0.1"
port = {PORT}
transport = "web"
proxy_protocol = false
web_client_ip_source = "x_forwarded_for"
web_trusted_proxy_cidrs = ["127.0.0.1/32"]

[server.api]
enabled = true
listen = "127.0.0.1:19191"
whitelist = ["127.0.0.1/32"]
auth_header = "Bearer {api_token}"
read_only = true

[web]
enabled = true
carrier = "https"
carriers = false
decoy_fasttrack_mode = "off"

[[web.vhosts]]
host = "{HOST}"
base_path = "{BASE}"
public_addr = "{public_ip}:443"

[web.vhosts.decoy]
mode = "static_directory"
directory = "{ROOT}/public"
index = "index.html"

[[web.vhosts.profiles]]
user = "owner"
secret_mode = "dd"
max_sessions = 8
max_streams = 512
max_streams_per_session = 64
'''
    write(CONFIG / 'telemt.toml', document, 0o640, gid)
    encoded = base64.urlsafe_b64encode(b'\x70\xdd' + bytes.fromhex(secret)).rstrip(b'=').decode()
    link = f'tg://webproxy?server={HOST}%2Ftelegram%2Fweb&secret={encoded}'
    write(CONFIG / 'owner-link.txt', link + '\n', 0o600)
    write(ROOT / 'installation.json', json.dumps(dict(version=VERSION, archive_sha256=ARCHIVE_SHA256,
          binary_sha256=hashlib.sha256(binary).hexdigest(), host=HOST, base_path=BASE,
          port=PORT, carrier='https', public_addr=public_ip + ':443'), indent=2) + '\n')
    write(UNIT, f'''[Unit]
Description=Oracova Telegram WEB proxy (Telemt {VERSION})
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=10

[Service]
Type=simple
User={ACCOUNT}
Group={ACCOUNT}
StateDirectory=oracova-telegram-web
WorkingDirectory=/var/lib/oracova-telegram-web
ExecStart={ROOT}/telemt {CONFIG}/telemt.toml
Restart=always
RestartSec=10
TimeoutStopSec=30
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/oracova-telegram-web
RestrictSUIDSGID=true
ProtectKernelTunables=true
ProtectControlGroups=true
UMask=0077
MemoryMax=512M
TasksMax=128
LimitNOFILE=8192

[Install]
WantedBy=multi-user.target
''')
    subprocess.run(['systemd-analyze', 'verify', str(UNIT)], check=True)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', UNIT.name], check=True)
    print(json.dumps(dict(installed=True, version=VERSION, host=HOST, port=PORT, secret_printed=False)))


if __name__ == '__main__':
    main(sys.argv[1])
