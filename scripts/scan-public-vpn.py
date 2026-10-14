"""Private, bounded Mac screening. Never publishes or changes system networking.

Inputs: verified HiddifyCli, private settings, and test-published-vpn.py in root.
Outputs omit credentials. A successful short test is not an uptime guarantee.
"""
import concurrent.futures
import copy
import hashlib
import importlib.util
import ipaddress
import json
import pathlib
import socket
import statistics
import subprocess
import sys
import time
import urllib.request

FEEDS = [
    'https://raw.githubusercontent.com/morpheusadam/v2ray-config/main/subs/bundles/best.txt',
    'https://raw.githubusercontent.com/barry-far/V2ray-config/main/Sub1.txt',
    'https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Sub1.txt',
    'https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main/secure/configs.txt',
    'https://raw.githubusercontent.com/mahsanet/MahsaFreeConfig/main/mci/sub_1.txt',
]


def fetch(address):
    req = urllib.request.Request(address, headers={'User-Agent': 'Hiddify/4.1.1'})
    with urllib.request.urlopen(req, timeout=15) as response:
        data = response.read(5_000_001)
    if len(data) > 5_000_000:
        raise ValueError('Feed exceeded bounded download')
    return data


def endpoint(node):
    host = node['server']
    if host.lower() in ('localhost', '1'):
        raise ValueError('Not a public server')
    try:
        addresses = socket.getaddrinfo(host, int(node['server_port']), type=socket.SOCK_STREAM)
    except OSError:
        return None
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError('Non-public server address')
    samples = []
    for _ in range(2):
        start = time.monotonic()
        try:
            with socket.create_connection((host, int(node['server_port'])), timeout=1.3):
                samples.append(round((time.monotonic() - start) * 1000, 1))
        except OSError:
            return None
    return statistics.median(samples)


def main():
    root = pathlib.Path(sys.argv[1]).resolve()
    deadline = time.monotonic() + 540
    settings = json.loads((root / 'settings.json').read_text())
    spec = importlib.util.spec_from_file_location('routecheck', root / 'test.py')
    check = importlib.util.module_from_spec(spec); spec.loader.exec_module(check)
    core = root / 'HiddifyCli'
    report = {'started_at': time.time(), 'sources': [], 'screened': [], 'finalists': [],
              'notes': ['TCP connect is not ICMP ping; HTTPS timing is not home RTT.',
                        'Short repeated checks do not establish long-term reliability.']}
    def save():
        (root / 'report.json').write_text(json.dumps(report, indent=2))
    profiles = {}
    for name in ('home', 'original', 'ava'):
        profiles[name] = json.loads(fetch(settings['urls'][name]))
    reality = next(n for n in profiles['original']['outbounds'] if n.get('tls', {}).get('reality', {}).get('enabled'))
    expected_ip = reality['server']
    template = next(n for n in profiles['home']['outbounds'] if n.get('detour') and n.get('transport', {}).get('type') == 'ws')
    nodes = []
    for index, address in enumerate(FEEDS):
        try:
            path = root / ('feed-%d.private.txt' % index)
            path.write_bytes(fetch(address)); path.chmod(0o600)
            output = root / ('feed-%d.private.json' % index)
            with (root / ('parse-%d.private.log' % index)).open('w') as log:
                parsed = subprocess.run([str(core), 'parse', str(path), '-o', str(output)], stdout=log, stderr=log, timeout=25)
            if not output.exists():
                raise ValueError('Parser produced no config')
            output.chmod(0o600)
            data = json.loads(output.read_text())
            batch = data.get('outbounds', [])
            # Spread across each source so the first large feed cannot dominate.
            nodes.extend(batch[::max(1, len(batch) // 80)][:80])
            report['sources'].append({'url': address, 'parsed': len(batch), 'parser_exit': parsed.returncode})
        except Exception as error:
            report['sources'].append({'url': address, 'error': type(error).__name__})
        save()
    seen = set(); candidates = []
    for node in nodes:
        if node.get('type') not in ('vless', 'vmess', 'trojan', 'shadowsocks') or 'server_port' not in node:
            continue
        if node.get('detour') or node.get('tls', {}).get('insecure'):
            continue
        # Four original weak routes share this frontend; find other operators.
        if 'volumeroot.com' in json.dumps(node).lower():
            continue
        public_id = (node['type'], node['server'], node['server_port'], node.get('tls', {}).get('server_name', ''), node.get('transport', {}).get('path', ''))
        if public_id in seen:
            continue
        seen.add(public_id)
        clean = copy.deepcopy(node); clean['tag'] = 'candidate-%d' % len(candidates)
        candidates.append(clean)
        if len(candidates) >= 400:
            break
    fast = []
    def tcp(node):
        try: return node, endpoint(node)
        except Exception: return node, None
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        for node, latency in pool.map(tcp, candidates):
            if latency is not None and latency < 100:
                fast.append((latency, node))
    fast.sort(key=lambda item: item[0])
    report['candidates'] = len(candidates); report['tcp_under_100ms'] = len(fast); save()
    selected = []; groups = set()
    for latency, node in fast:
        # Limit duplicates behind the same TLS frontend or endpoint.
        group = node.get('tls', {}).get('server_name') or node['server']
        if group in groups:
            continue
        groups.add(group); selected.append((latency, node))
        if len(selected) == 30:
            break
    def screen(item):
        latency, node = item
        row = {'id': node['tag'], 'protocol': node['type'], 'server': node['server'], 'tcp_connect_ms': latency}
        if time.monotonic() > deadline:
            row['skipped_deadline'] = True; return row, node, None
        entry = check.probe(core, root, node['tag'] + '-entry', node, raw=True)
        row['entry'] = entry
        if not entry.get('passed'):
            return row, node, None
        hidden = copy.deepcopy(node); hidden['tag'] += '-hidden'
        chain = copy.deepcopy(template); chain['tag'] = node['tag'] + '-home'; chain['detour'] = hidden['tag']
        home = check.probe(core, root, node['tag'] + '-home', chain, hidden, expected_ip, True)
        row['home'] = home; row['home_transport'] = 'Cloudflare'
        if not home.get('passed') and time.monotonic() < deadline:
            # Test an explicit alternative, never silently equate it to publication.
            direct_chain = copy.deepcopy(reality)
            direct_chain['tag'] = chain['tag']; direct_chain['detour'] = hidden['tag']
            alternate = check.probe(core, root, node['tag'] + '-home-reality', direct_chain, hidden, expected_ip, True)
            row['home_reality'] = alternate
            if alternate.get('passed'):
                chain = direct_chain; home = alternate; row['home_transport'] = 'Reality'
        return row, node, (chain, hidden) if home.get('passed') else None
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(screen, item) for item in selected]
        for future in concurrent.futures.as_completed(futures):
            row, node, route = future.result()
            report['screened'].append(row); save()
            print(json.dumps(row), flush=True)
            if route is not None:
                report['finalists'].append({'id': node['tag'], 'home_transport': row['home_transport'], 'repeat': []})
                private = root / (node['tag'] + '-accepted.private.json')
                private.write_text(json.dumps(node)); private.chmod(0o600)
                chain, hidden = route
                for attempt in range(3):
                    if time.monotonic() > deadline:
                        break
                    result = check.probe(core, root, node['tag'] + '-repeat-%d' % attempt, chain, hidden, expected_ip, True)
                    report['finalists'][-1]['repeat'].append(result); save()
                    if not result.get('passed'):
                        break
                final = report['finalists'][-1]
                final['repeat_passed'] = len(final['repeat']) == 3 and all(r.get('passed') for r in final['repeat'])
                save()
    report['finished_at'] = time.time(); save()
    print('SCAN_FINISHED', flush=True)


if __name__ == '__main__':
    main()
