"""Authenticated WEB -> MTProxy -> Telegram resPQ probe; no credentials logged.

Run as root to read the destination-only configuration. Uses system cryptography.
This protocol probe does not replace acceptance in the user's actual Telegram app.
"""
import base64
import hashlib
import hmac
import http.client
import json
from pathlib import Path
import re
import secrets
import struct
import sys
import time
import tomllib

def frame(kind, stream=0, payload=b''):
    return bytes([kind]) + stream.to_bytes(3, 'big') + len(payload).to_bytes(4, 'big') + payload


def frames(body):
    while body:
        if len(body) < 8:
            raise ValueError('short frame')
        kind, stream, size = body[0], int.from_bytes(body[1:4], 'big'), int.from_bytes(body[4:8], 'big')
        if size > len(body) - 8:
            raise ValueError('short payload')
        yield kind, stream, body[8:8 + size]
        body = body[8 + size:]


def probe(public=True):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    config = tomllib.loads(Path('/etc/oracova-telegram-web/telemt.toml').read_text())
    vhost = config['web']['vhosts'][0]
    host, base = vhost['host'], '/' + vhost['base_path']
    secret = bytes.fromhex(config['access']['users']['owner'])
    capability = base64.urlsafe_b64encode(hmac.digest(b'\xdd' + secret,
        b'tdesktop-web-proxy-bridge-v2\n' + host.encode() + b'\n' + vhost['base_path'].encode(), 'sha256')).rstrip(b'=').decode()
    token = None
    phase = 'bridge'
    started = time.monotonic()

    def request(method, suffix, body=None, bearer=None, headers=None):
        connection = (http.client.HTTPSConnection(host, timeout=35) if public else
                      http.client.HTTPConnection('127.0.0.1', 18180, timeout=35))
        fields = {'Host': host, 'User-Agent': 'Oracova-Telegram-WEB-Health/1', 'Cache-Control': 'no-store'}
        if not public:
            fields['X-Forwarded-For'] = '127.0.0.1'
        if bearer:
            fields['Authorization'] = 'Bearer ' + bearer
        if body is not None:
            fields['Content-Type'] = 'application/octet-stream'
        fields.update(headers or {})
        try:
            connection.request(method, base + suffix, body=body, headers=fields)
            response = connection.getresponse()
            data = response.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise ValueError('response limit')
            return response.status, dict((key.lower(), value) for key, value in response.getheaders()), data
        finally:
            connection.close()

    try:
        status, headers, body = request('GET', '/?bridge=' + capability)
        if status != 200:
            raise ValueError('bridge status ' + str(status))
        match = re.search(rb'let bootstrap="([A-Za-z0-9_-]{43})"', body)
        if not match or 'no-store' not in headers.get('cache-control', ''):
            raise ValueError('bridge contract')
        bootstrap = match[1].decode()
        phase = 'session'
        status, headers, body = request('POST', '/api/v1/session', frame(0x10, payload=b'\x01'), bootstrap)
        if status != 200 or body != frame(0x11) or headers.get('x-carrier-mode') != 'https':
            raise ValueError('session contract ' + str(status))
        token = headers.get('x-session-token')
        if not token:
            raise ValueError('session credential missing')

        phase = 'telegram'
        header = bytearray(secrets.token_bytes(64))
        header[56:60] = b'\xdd' * 4
        header[60:62] = (2).to_bytes(2, 'little', signed=True)
        keyiv, reverse = bytes(header[8:56]), bytes(header[8:56])[::-1]
        encrypt = Cipher(algorithms.AES(hashlib.sha256(keyiv[:32] + secret).digest()), modes.CTR(keyiv[32:])).encryptor()
        decrypt = Cipher(algorithms.AES(hashlib.sha256(reverse[:32] + secret).digest()), modes.CTR(reverse[32:])).decryptor()
        encrypted = encrypt.update(bytes(header))
        handshake = bytes(header[:56]) + encrypted[56:]
        nonce = secrets.token_bytes(16)
        request_body = struct.pack('<I', 0xbe7e8ef1) + nonce
        message_id = int(time.time() * (1 << 32)) & ~3
        packet = bytes(8) + struct.pack('<QI', message_id, len(request_body)) + request_body + secrets.token_bytes(7)
        payload = handshake + encrypt.update(struct.pack('<I', len(packet)) + packet)
        status, _, _ = request('POST', '/api/v1/up', frame(1, 1) + frame(2, 1, payload), token, {'X-Up-Seq': '1'})
        if status != 204:
            raise ValueError('uplink status ' + str(status))
        data = bytearray()
        cursor = '0'
        for attempt in range(4):
            status, headers, body = request('POST', '/api/v1/down', bearer=token, headers={'X-Down-Cursor': cursor})
            if status not in (200, 204):
                raise ValueError('downlink status ' + str(status))
            cursor = headers.get('x-down-cursor', cursor)
            for kind, stream, payload in frames(body):
                if kind == 2 and stream == 1:
                    data.extend(decrypt.update(payload))
                if kind == 3 and stream == 1:
                    raise ValueError('inner MTProxy stream closed')
            if len(data) >= 4:
                size = int.from_bytes(data[:4], 'little')
                if not 40 <= size <= 4096:
                    raise ValueError('Telegram envelope size')
                if len(data) >= 4 + size:
                    response = data[4:4 + size]
                    if response[:8] != bytes(8) or response[20:24] != struct.pack('<I', 0x05162463) or response[24:40] != nonce:
                        raise ValueError('Telegram resPQ/nonce verification')
                    return dict(ok=True, scope='public-cloudflare' if public else 'private',
                                carrier='https', tlsVerified=public, authenticated=True, telegramResPQ=True,
                                seconds=round(time.monotonic() - started, 3))
        raise ValueError('no Telegram response')
    except Exception as error:
        # Do not render exception text: network exceptions may include bearer URLs.
        return dict(ok=False, scope='public-cloudflare' if public else 'private', phase=phase,
                    error=type(error).__name__, reason=str(error) if isinstance(error, ValueError) else 'network failure')
    finally:
        if token:
            try:
                request('DELETE', '/api/v1/session', bearer=token)
            except Exception:
                pass


if __name__ == '__main__':
    result = probe(public='--private' not in sys.argv)
    print(json.dumps(result, separators=(',', ':')))
    sys.exit(0 if result['ok'] else 1)
