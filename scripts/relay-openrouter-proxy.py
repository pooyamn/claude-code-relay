#!/usr/bin/env python3
"""Anthropic-compatible proxy that fails over between several OpenRouter keys.

Claude Code reads ANTHROPIC_AUTH_TOKEN once, at launch, and there is no way to
swap it mid-process -- so a key that hits its quota takes the whole session down
until someone notices and restarts it. Measured today: "Rate limit exceeded:
free-models-per-day-stealth", which is a PER-KEY DAILY quota. More keys buy more
daily quota, not a higher rate, and only if something can move between them.

This sits in front: Claude Code points at it, it holds the pool, and on a quota
error it marks that key cooling-down and retries the SAME request on the next one.
Failover happens before any bytes reach the client, so the client never sees a
partial answer torn in half.

  keys      relay-work/openrouter-keys.json  (0600, gitignored)
            [{"name": "cox", "key": "sk-or-..."}, ...]
  listen    127.0.0.1:4599        (OR_PROXY_PORT)
  upstream  https://openrouter.ai/api
  log       relay-work/openrouter-proxy.log

Order is preserved: the first key that is not cooling down wins, so adding a key
to the end of the list makes it a spare rather than changing what you use today.
"""
import http.server
import json
import os
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.request

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(SCRIPTS, "relay-work")
KEYS = os.path.join(STATE, "openrouter-keys.json")
LOG = os.path.join(STATE, "openrouter-proxy.log")
UPSTREAM = os.environ.get("OR_UPSTREAM", "https://openrouter.ai/api")
PORT = int(os.environ.get("OR_PROXY_PORT", "4599"))

# A daily quota resets at 00:00 UTC. Without a hint from the server that is the
# only honest guess; a shorter cooldown would just burn the key again immediately.
DAILY_COOLDOWN = 24 * 3600
_cool = {}                 # key name -> epoch when it may be retried
_lock = threading.Lock()


def log(msg):
    try:
        with open(LOG, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def load_keys():
    try:
        return [k for k in json.load(open(KEYS)) if k.get("key")]
    except Exception as e:
        log(f"CANNOT READ {KEYS}: {e}")
        return []


def available():
    """Keys not currently cooling down, in file order."""
    now = time.time()
    with _lock:
        return [k for k in load_keys() if _cool.get(k["name"], 0) <= now]


def cool(name, seconds):
    with _lock:
        _cool[name] = time.time() + seconds
    log(f"COOLDOWN {name} for {int(seconds)}s")


def retry_after(body, headers):
    """Seconds to wait, from the server if it says so, else a day."""
    try:
        ra = headers.get("retry-after")
        if ra:
            return float(ra)
    except Exception:
        pass
    try:
        msg = json.loads(body).get("error", {}).get("message", "")
        if "per-day" in msg or "daily" in msg:
            return DAILY_COOLDOWN
    except Exception:
        pass
    return 300.0


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _attempt(self, key, body):
        """One upstream try. Returns (status, headers, response) or raises."""
        hdrs = {k: v for k, v in self.headers.items()
                if k.lower() not in ("host", "authorization", "x-api-key",
                                     "content-length", "connection",
                                     "accept-encoding")}
        hdrs["Authorization"] = f"Bearer {key}"
        hdrs["Accept-Encoding"] = "identity"       # never gzip: it breaks streaming
        req = urllib.request.Request(UPSTREAM + self.path, data=body,
                                     method=self.command, headers=hdrs)
        return urllib.request.urlopen(req, timeout=900)

    def _proxy(self):
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else None
        pool = available()
        if not pool:
            with _lock:
                soonest = min(_cool.values()) if _cool else 0
            wait = max(0, int(soonest - time.time()))
            self._fail(429, f"all OpenRouter keys are rate-limited; "
                            f"next one frees up in about {wait // 60} min")
            return

        last = None
        for k in pool:
            try:
                r = self._attempt(k["key"], body)
            except urllib.error.HTTPError as e:
                err = e.read()
                # 429 quota / 402 out of credit: this KEY is spent, try the next.
                if e.code in (429, 402):
                    cool(k["name"], retry_after(err, e.headers))
                    last = (e.code, err)
                    log(f"{e.code} on {k['name']}, failing over")
                    continue
                self._relay_error(e, err)          # a real error: pass it through
                return
            except Exception as e:
                last = (502, str(e).encode())
                log(f"UPSTREAM ERROR on {k['name']}: {e}")
                continue
            self._stream(r, k["name"])
            return

        code, err = last or (502, b"no upstream")
        self._fail(code, err.decode("utf8", "replace")[:300])

    def _stream(self, r, name):
        """Pass the response through unbuffered -- Claude Code streams SSE, and
        buffering here would stall the whole answer until the turn ended."""
        self.send_response(r.status)
        for k, v in r.headers.items():
            if k.lower() in ("transfer-encoding", "connection", "content-length",
                             "content-encoding"):
                continue
            self.send_header(k, v)
        self.send_header("X-Relay-Key", name)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            while True:
                chunk = r.read(1024)
                if not chunk:
                    break
                self.wfile.write(b"%X\r\n" % len(chunk) + chunk + b"\r\n")
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except Exception:
            pass

    def _relay_error(self, e, body):
        self.send_response(e.code)
        self.send_header("Content-Type", e.headers.get("content-type", "application/json"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, code, message):
        payload = json.dumps({"type": "error",
                              "error": {"type": "api_error", "message": message}}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        log(f"FAIL {code}: {message}")

    do_POST = _proxy
    do_GET = _proxy


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    if not load_keys():
        print(f"no keys in {KEYS}", file=sys.stderr)
        sys.exit(2)
    log(f"START on 127.0.0.1:{PORT} with {len(load_keys())} key(s) -> {UPSTREAM}")
    Server(("127.0.0.1", PORT), Handler).serve_forever()
