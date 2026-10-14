"""Opt-in isolated Hiddify route checks. Never changes system VPN or publishes.

Settings are private JSON: urls mapping ava/home/original to subscriptions.
Outputs contain rank, outcome and timing only; configs/core logs stay private.
"""
import argparse
import copy
import hashlib
import json
import pathlib
import socket
import statistics
import subprocess
import time
import urllib.request


def request(port, address, expected, seconds=8):
    result = subprocess.run(['curl', '--silent', '--show-error', '--noproxy', '',
        '--proxy', 'socks5h://127.0.0.1:' + str(port), '--connect-timeout', '6',
        '--max-time', str(seconds), '--write-out', '\n%{http_code} %{time_starttransfer}',
        address], capture_output=True, text=True, timeout=seconds + 2)
    body, _, trailer = result.stdout.rpartition('\n')
    fields = trailer.split()
    status = fields[0] if fields else '000'
    return {'ok': result.returncode == 0 and status == expected,
            'http': status, 'exit': result.returncode,
            'https_ttfb_ms': round(float(fields[1]) * 1000, 1) if len(fields) > 1 else None}, body


def probe(core, root, label, outbound, entry=None, expected_ip=None, raw=False):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    config = {'log': {'level': 'warn'},
              'inbounds': [{'type': 'mixed', 'listen': '127.0.0.1', 'listen_port': port}],
              'outbounds': [outbound] + ([entry] if entry else []),
              'route': {'final': outbound['tag']}}
    path = root / (label + '.json'); path.write_text(json.dumps(config)); path.chmod(0o600)
    settings = root / (label + '-options.json')
    settings.write_text(json.dumps({'enable-full-config': True, 'enable-tun': False,
        'set-system-proxy': False, 'mixed-port': port, 'enable-clash-api': False,
        'log-level': 'warn', 'log-file': str(root / (label + '-core.private.log')),
        'direct-dns-address': 'local', 'remote-dns-address': 'local'}))
    settings.chmod(0o600)
    result = {'label': label}
    with (root / (label + '.private.log')).open('w+') as log:
        command = [str(core), '--disable-color', 'srun', '-c', str(path)] if raw else [str(core), '--disable-color', 'run', '-c', str(path), '-h', str(settings)]
        child = subprocess.Popen(command,
                                 cwd=root, stdout=log, stderr=log)
        try:
            ready = False
            for _ in range(60):
                if child.poll() is not None: break
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.05): ready = True; break
                except OSError: time.sleep(.05)
            if not ready:
                result['startup_failed'] = True
            else:
                checks = []
                for _ in range(2):
                    check, _ = request(port, 'https://www.gstatic.com/generate_204', '204')
                    checks.append(check)
                    if not check['ok']: break
                result['checks'] = checks
                result['passed'] = len(checks) == 2 and all(check['ok'] for check in checks)
                if result['passed'] and expected_ip:
                    check, body = request(port, 'https://www.cloudflare.com/cdn-cgi/trace', '200')
                    fields = dict(line.split('=', 1) for line in body.splitlines() if '=' in line)
                    result['home_exit_verified'] = check['ok'] and fields.get('ip') == expected_ip
                    result['passed'] = result['home_exit_verified']
                if result['passed']:
                    result['median_https_ttfb_ms'] = statistics.median(check['https_ttfb_ms'] for check in checks)
        finally:
            if child.poll() is None:
                child.terminate()
                try: child.wait(timeout=3)
                except subprocess.TimeoutExpired: child.kill(); child.wait()
            log.seek(0); diagnostic = log.read().lower()
            result['error_categories'] = [name for name in ('timeout', 'certificate', 'handshake', 'websocket', 'eof', 'refused') if name in diagnostic]
    return result


def variants(node):
    # Alter only transport spelling/negotiation, never endpoints, credentials,
    # certificate validation, or the working rank-2 route.
    if node['tag'].startswith('Free tested 2 '): return []
    output = []
    clean = copy.deepcopy(node)
    tls = clean.get('tls', {})
    if tls.get('server_name'):
        tls['server_name'] = tls['server_name'].lower().rstrip('.')
    transport = clean.get('transport', {})
    if transport.get('headers', {}).get('Host'):
        transport['headers']['Host'] = transport['headers']['Host'].lower().rstrip('.')
    if transport.get('path', '').endswith('?ed'):
        transport['path'] = transport['path'][:-3]
    if clean != node: output.append(('canonical', clean))
    if 'alpn' in tls:
        no_alpn = copy.deepcopy(clean); no_alpn['tls'].pop('alpn')
        output.append(('no-alpn', no_alpn))
    if not tls.get('reality', {}).get('enabled'):
        standard = copy.deepcopy(clean)
        standard['tls'].pop('utls', None)
        standard['tls'].pop('alpn', None)
        if standard != node and not any(standard == value for _, value in output):
            output.append(('standard-tls', standard))
        browser = copy.deepcopy(clean)
        browser['tls']['utls'] = {'enabled': True, 'fingerprint': 'chrome'}
        browser['tls'].pop('alpn', None)
        if browser != node: output.append(('chrome', browser))
    return output


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('settings'); parser.add_argument('--variants', action='store_true')
    parser.add_argument('--ranks', nargs='+', type=int, choices=range(1,6))
    parser.add_argument('--home-transport', choices=('published','reality'), default='published')
    parser.add_argument('--entry-variant', choices=('published','standard-tls'), default='published')
    args = parser.parse_args(); root = pathlib.Path(args.settings).resolve().parent
    settings = json.loads(pathlib.Path(args.settings).read_text()); core = root / 'HiddifyCli'
    profiles = {}
    for name, address in settings['urls'].items():
        req = urllib.request.Request(address, headers={'User-Agent': 'Hiddify/4.1.1', 'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(req, timeout=15) as response: body = response.read()
        downloaded=root / ('published-' + name + '.json')
        downloaded.write_bytes(body); downloaded.chmod(0o600)
        profiles[name] = json.loads(body)
    reality_home = next(node for node in profiles['original']['outbounds']
                        if node.get('tls', {}).get('reality', {}).get('enabled'))
    expected_ip = reality_home['server']
    entries = [node for node in profiles['ava']['outbounds'] if node['tag'].startswith('Free tested ')]
    entries.sort(key=lambda node: (not node['tag'].startswith('Free tested 2 '), node['tag']))
    if args.ranks:
        entries=[node for node in entries if int(node['tag'].split()[2]) in args.ranks]
    homes = {node['tag']: node for node in profiles['home']['outbounds']}
    results = []
    previous = root / 'exact-results.json'
    baseline = json.loads(previous.read_text()) if args.variants and previous.exists() else []
    failed_ranks = {row['label'].split('-')[1] for row in baseline if not row.get('passed')}
    report_name = ('variants-results' if args.variants else 'exact-results')
    if args.home_transport != 'published' or args.entry_variant != 'published':
        report_name += '-'+args.home_transport+'-'+args.entry_variant
    def run(label, outbound, entry=None, home=False):
        result = probe(core, root, label, outbound, entry, expected_ip if home else None, settings.get('raw_core', False))
        results.append(result)
        print(json.dumps(result), flush=True)
        (root / (report_name+'.json')).write_text(json.dumps(results, indent=2))
    for entry in entries:
        rank = entry['tag'].split()[2]; chain = homes['US Home via ' + entry['tag'] + ' - Cloudflare']
        hidden = homes[chain['detour']]
        if not args.variants:
            suffix=''
            if args.entry_variant != 'published' and rank != '2':
                entry=dict(variants(entry))[args.entry_variant]
                hidden=copy.deepcopy(entry);hidden['tag']=chain['detour']
                suffix+='-'+args.entry_variant
            if args.home_transport=='reality':
                tag=chain['tag'];chain=copy.deepcopy(reality_home)
                chain['tag']=tag;chain['detour']=hidden['tag']
            run('entry-' + rank + suffix, entry)
            run('home-' + rank + ('-reality' if args.home_transport=='reality' else '') + suffix, chain, hidden, True)
        else:
            if baseline and rank not in failed_ranks: continue
            for name, variant in variants(entry):
                run('entry-' + rank + '-' + name, variant)
                hidden_variant = copy.deepcopy(variant); hidden_variant['tag'] = hidden['tag']
                run('home-' + rank + '-' + name, chain, hidden_variant, True)
    print('Completed isolated Hiddify tests; no system VPN/routing/publication changes.', flush=True)


if __name__ == '__main__': main()
