"""Windows-only adapter for pinned alexbers/mtprotoproxy; no secrets in argv/logs."""
import importlib.util
import json
from pathlib import Path
import re
import sys
import tomllib

SOURCE_ROOT = Path(r'C:\ProgramData\OracovaVPN-20261003-FA9g4b\config')


def configuration(document, expected_bind):
    if document.get('bind-to') != expected_bind:
        raise ValueError('Original listener changed; reconcile before replacing')
    secret = document.get('secret', '')
    if not isinstance(secret, str) or not re.fullmatch('ee[0-9a-fA-F]{34,}', secret):
        raise ValueError('Expected original hexadecimal FakeTLS secret')
    raw = bytes.fromhex(secret)
    domain = raw[17:].decode('ascii')
    if len(raw) < 19 or not re.fullmatch(r'[A-Za-z0-9.-]{1,253}', domain):
        raise ValueError('Invalid original FakeTLS domain')
    address, port = expected_bind.rsplit(':', 1)
    return dict(PORT=int(port), USERS={'owner': raw[1:17].hex()},
                TLS_DOMAIN=domain, MASK_HOST=domain, MASK_PORT=443,
                MODES={'classic': False, 'secure': False, 'tls': True},
                LISTEN_ADDR_IPV4=address, LISTEN_ADDR_IPV6=None,
                PREFER_IPV6=False, FAST_MODE=False, USE_MIDDLE_PROXY=False,
                CLIENT_IPS_LEN=0, IGNORE_TIME_SKEW=False,
                METRICS_PORT=11090 if port == '10990' else 11091,
                METRICS_LISTEN_ADDR_IPV4='127.0.0.1', METRICS_LISTEN_ADDR_IPV6=None,
                METRICS_EXPORT_LINKS=False)


def prepare(release):
    sys.path.insert(0, str(release / 'deps'))
    from Crypto.Cipher import AES
    if AES.new(bytes(16), AES.MODE_ECB).encrypt(bytes(16)).hex() != '66e94bd4ef8a2c3b884cfa59ca342b2e':
        raise ValueError('Accelerated AES known-answer check failed')
    for name, filename, bind in (
        ('OracovaMTProto', 'mtg.toml', '127.0.0.1:10990'),
        ('OracovaMTProto8443', 'mtg-direct.toml', '0.0.0.0:8443'),
    ):
        config = configuration(tomllib.loads((SOURCE_ROOT / filename).read_text()), bind)
        # A private, administrator-owned config file. JSON string quoting avoids
        # executing source strings; only the reviewed upper-case keys are emitted.
        with (release / (name + '.py')).open('x', encoding='utf-8') as target:
            for key, value in config.items():
                target.write(key + ' = ' + repr(value) + '\n')
    print(json.dumps({'configsPrepared': 2, 'secretsChanged': False, 'linksChanged': False,
                      'acceleratedAesKnownAnswerPassed': True}))


def serve(release, name):
    if name not in ('OracovaMTProto', 'OracovaMTProto8443'):
        raise ValueError('Unknown fixed service')
    upstream = release / 'upstream'
    sys.path.insert(0, str(release / 'deps'))
    sys.path.insert(0, str(upstream))
    spec = importlib.util.spec_from_file_location('reviewed_mtprotoproxy', upstream / 'mtprotoproxy.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # The upstream startup printer exposes bearer secrets in proxy URLs. Keep
    # its protocol implementation unchanged and suppress only that printer.
    module.print_tg_info = lambda: None
    sys.argv = [str(upstream / 'mtprotoproxy.py'), str(release / (name + '.py'))]
    module.main()


if __name__ == '__main__':
    try:
        if sys.platform != 'win32' or len(sys.argv) != 2:
            raise ValueError('Exact Windows service or preparation entry required')
        release = Path(__file__).resolve().parent
        if sys.argv[1] == '--prepare':
            prepare(release)
        else:
            serve(release, sys.argv[1])
    except (ValueError, OSError) as error:
        print(json.dumps({'errorType': type(error).__name__}), file=sys.stderr)
        sys.exit(2)
