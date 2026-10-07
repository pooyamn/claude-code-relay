"""Read-only authenticated FakeTLS + Telegram req_pq_multi health check.

Only fixed local listeners/configuration. Bearer secrets never leave private
memory, arguments or logs. Does not execute the service's Python configuration.
"""
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import socket
import ssl
import struct
import sys
import time
import tomllib

ROOT = Path(r'C:\ProgramData\OracovaVPN-20261003-FA9g4b')
MTROOT = Path(r'C:\ProgramData\OracovaMTProto-2a2ae0dae7f749a2bcd664519271c88d')
SERVICES = {'OracovaMTProto': ('mtg.toml', 10990),
            'OracovaMTProto8443': ('mtg-direct.toml', 8443)}
DC = ('149.154.167.51', 443)


def exact(sock, size):
    result = bytearray()
    while len(result) < size:
        chunk = sock.recv(size - len(result))
        if not chunk:
            raise OSError('closed')
        result.extend(chunk)
    return bytes(result)


def record(sock):
    header = exact(sock, 5)
    size = int.from_bytes(header[3:5], 'big')
    if size > 32768:
        raise ValueError('record size')
    return header + exact(sock, size)


def client_hello(domain, secret):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.maximum_version = ssl.TLSVersion.TLSv1_3
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    connection = context.wrap_bio(incoming, outgoing, server_hostname=domain)
    try:
        connection.do_handshake()
    except ssl.SSLWantReadError:
        pass
    hello = bytearray(outgoing.read())
    # The pinned implementation intentionally rejects small ClientHellos.
    if len(hello) < 517 or hello[0] != 22:
        raise ValueError('ClientHello shape')
    hello[11:43] = bytes(32)
    digest = bytearray(hmac.digest(secret, hello, 'sha256'))
    timestamp = int(time.time()).to_bytes(4, 'little')
    for i in range(4):
        digest[28 + i] ^= timestamp[i]
    hello[11:43] = digest
    return bytes(hello), bytes(digest)


def verify_server(records, secret, digest):
    if len(records) < 3 or records[0][0] != 22 or records[1] != b'\x14\x03\x03\x00\x01\x01' or records[2][0] != 23:
        raise ValueError('FakeTLS shape')
    response = b''.join(records)
    expected = hmac.digest(secret, digest + response[:11] + bytes(32) + response[43:], 'sha256')
    if not hmac.compare_digest(response[11:43], expected):
        raise ValueError('FakeTLS authentication')


class Transport:
    def __init__(self, sock, secret):
        from Crypto.Cipher import AES
        self.sock, self.buffer = sock, bytearray()
        header = bytearray(secrets.token_bytes(64))
        header[56:60] = b'\xdd' * 4
        header[60:62] = (2).to_bytes(2, 'little', signed=True)
        keyiv, reverse = bytes(header[8:56]), bytes(header[8:56])[::-1]
        self.encrypt = AES.new(hashlib.sha256(keyiv[:32] + secret).digest(), AES.MODE_CTR,
                               nonce=b'', initial_value=int.from_bytes(keyiv[32:], 'big'))
        self.decrypt = AES.new(hashlib.sha256(reverse[:32] + secret).digest(), AES.MODE_CTR,
                               nonce=b'', initial_value=int.from_bytes(reverse[32:], 'big'))
        encrypted = self.encrypt.encrypt(bytes(header))
        self.write(bytes(header[:56]) + encrypted[56:])

    def write(self, payload):
        self.sock.sendall(b'\x17\x03\x03' + len(payload).to_bytes(2, 'big') + payload)

    def read(self, size):
        while len(self.buffer) < size:
            packet = record(self.sock)
            if packet[0] != 23:
                raise ValueError('transport record')
            self.buffer.extend(self.decrypt.decrypt(packet[5:]))
        result = bytes(self.buffer[:size])
        del self.buffer[:size]
        return result

    def request_pq(self):
        nonce = secrets.token_bytes(16)
        body = struct.pack('<I', 0xbe7e8ef1) + nonce
        message_id = int(time.time() * (1 << 32)) & ~3
        packet = bytes(8) + struct.pack('<QI', message_id, len(body)) + body + secrets.token_bytes(7)
        self.write(self.encrypt.encrypt(struct.pack('<I', len(packet)) + packet))
        size = int.from_bytes(self.read(4), 'little')
        if not 40 <= size <= 4096:
            raise ValueError('response size')
        response = self.read(size)
        body_size = int.from_bytes(response[16:20], 'little')
        if response[:8] != bytes(8) or not 20 <= body_size <= len(response) - 20:
            raise ValueError('response envelope')
        if response[20:24] != struct.pack('<I', 0x05162463) or response[24:40] != nonce:
            raise ValueError('resPQ nonce')


def probe(name):
    filename, port = SERVICES[name]
    document = tomllib.loads((ROOT / 'config' / filename).read_text())
    raw = bytes.fromhex(document['secret'])
    if raw[0] != 0xee or len(raw) < 19:
        raise ValueError('configuration')
    secret, domain = raw[1:17], raw[17:].decode('ascii')
    result = dict(name=name, localAuthenticated=False, telegram=False, upstreamReachable=False)
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=4) as sock:
            sock.settimeout(4)
            hello, digest = client_hello(domain, secret)
            sock.sendall(hello)
            verify_server([record(sock) for _ in range(3)], secret, digest)
            result['localAuthenticated'] = True
            # FakeTLS client ChangeCipherSpec precedes application records.
            sock.sendall(b'\x14\x03\x03\x00\x01\x01')
            Transport(sock, secret).request_pq()
            result['telegram'] = True
    except (OSError, ValueError, ssl.SSLError):
        pass
    if not result['telegram']:
        try:
            with socket.create_connection(DC, timeout=3):
                result['upstreamReachable'] = True
        except OSError:
            pass
    return result


if __name__ == '__main__':
    try:
        if sys.platform != 'win32' or len(sys.argv) != 2 or sys.argv[1] not in SERVICES:
            raise ValueError('fixed Windows probe required')
        sys.path.insert(0, str(MTROOT / 'deps'))
        print(json.dumps(probe(sys.argv[1]), separators=(',', ':')))
    except Exception as error:
        # Never print a traceback/configuration/secret.
        print(json.dumps({'probeError': type(error).__name__}))
        sys.exit(2)
