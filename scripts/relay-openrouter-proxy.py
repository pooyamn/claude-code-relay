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
partial answer torn in half -- and since 2026-08-23 "before any bytes" is enforced
literally: the first body chunk is read and judged BEFORE the 200 is forwarded, so
an upstream that accepts the request and then dies (or answers 200 with an error
envelope) fails over instead of reaching the session as a corrupt reply.

  keys      relay-work/openrouter-keys.json  (0600, gitignored)
            [{"name": "cox", "key": "sk-or-..."}, ...]
  listen    127.0.0.1:4599        (OR_PROXY_PORT)
  upstream  https://openrouter.ai/api
  log       relay-work/openrouter-proxy.log

Each CONVERSATION sticks to one key so its prompt cache keeps working; new
conversations are handed out round-robin so several sessions still spread across
the pool. On a quota error the request walks the rest of the pool.
"""
import hashlib
import http.server
import json
import os
import socketserver
import subprocess
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


DUD_COOLDOWN = 120   # a key that answered 200-then-died; brief, it is usually a blip

_rr = 0            # cursor, used only when a NEW conversation needs a key
_affinity = {}     # conversation fingerprint -> key name


def fingerprint(body):
    """Stable id for a conversation, from the parts that do not change turn to turn.

    The system prompt plus the first user message are fixed for the life of a Claude
    Code session, so they identify it without needing a header the client does not
    send.
    """
    try:
        d = json.loads(body or b"{}")
    except Exception:
        return "default"
    sys_p = d.get("system")
    if isinstance(sys_p, list):
        sys_p = "".join(x.get("text", "") for x in sys_p if isinstance(x, dict))
    first = ""
    for m in d.get("messages") or []:
        if m.get("role") == "user":
            c = m.get("content")
            first = c if isinstance(c, str) else "".join(
                x.get("text", "") for x in c or [] if isinstance(x, dict))
            break
    return hashlib.sha1(((sys_p or "")[:4000] + first[:400]).encode()).hexdigest()[:16]


def available(body=None):
    """Keys for this request: the conversation's OWN key first, then the rest.

    Round-robin per request was wrong. Prompt caches are per-key, so sending
    consecutive turns of one conversation to different keys re-pays the entire
    prefix every time -- measured 2427 input tokens against 59 for a cache hit, ~40x.
    On a per-DAY quota that spends the allowance far faster, so balancing made the
    limit arrive SOONER than not balancing at all.

    Affinity instead: a conversation sticks to one key and keeps its cache, while
    NEW conversations are handed out round-robin, so several sessions still spread
    across the pool. The rest of the pool follows as failover, so a spent key still
    moves the conversation on (losing its cache once, not every turn).
    """
    global _rr
    now = time.time()
    with _lock:
        live = [k for k in load_keys() if _cool.get(k["name"], 0) <= now]
        if not live:
            return []
        fp = fingerprint(body)
        name = _affinity.get(fp)
        chosen = next((k for k in live if k["name"] == name), None)
        if chosen is None:
            _rr = (_rr + 1) % len(live)
            chosen = live[_rr]
            _affinity[fp] = chosen["name"]
        return [chosen] + [k for k in live if k["name"] != chosen["name"]]


# Where to tell you a key ran out. Silence is the wrong default here: a spent key
# is invisible until a session fails, and the fix (add another key) is something
# only you can do.
NOTIFY_TO = os.environ.get("OR_NOTIFY_TO", "-1003550185469:topic:816")


def notify(text):
    try:
        subprocess.Popen(
            ["openclaw", "message", "send", "--channel", "telegram",
             "--target", NOTIFY_TO.split(":topic:")[0],
             *(["--thread-id", NOTIFY_TO.split(":topic:")[1]] if ":topic:" in NOTIFY_TO else []),
             "--message", text],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception as e:
        log(f"NOTIFY FAILED: {e}")


def cool(name, seconds, quiet=False):
    """Mark a key cooling. quiet=True for transient duds -- worth a log line and
    nothing more; only quota exhaustion justifies pinging Telegram."""
    with _lock:
        _cool[name] = time.time() + seconds
        live = [k for k in load_keys() if _cool.get(k["name"], 0) <= time.time()]
    log(f"COOLDOWN {name} for {int(seconds)}s")
    hrs = max(1, int(seconds // 3600))
    if quiet:
        return
    if live:
        notify(f"🔑 OpenRouter key `{name}` hit its quota — failing over. "
               f"{len(live)} key(s) still good. It frees up in ~{hrs}h.")
    else:
        notify(f"🚨 OpenRouter: ALL keys are rate-limited (`{name}` was the last). "
               f"Sessions on `cox` will fail until ~{hrs}h from now.\n"
               f"Add another key to relay-work/openrouter-keys.json — it is picked "
               f"up per request, no restart needed.")


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


def _classify(r):
    """Read the first body chunk and judge whether the response is real.

    Returns (verdict, first_chunk). 'ok' means forwardable, with the first chunk
    in tow so _stream need not re-read it. Anything else describes WHY the
    response is a dud -- and because nothing has been sent downstream yet, the
    caller can simply fail over to the next key.

    This exists because OpenRouter sometimes ACCEPTS a request (HTTP 200) and
    then hands back nothing: the connection closes before one body byte, or it
    wraps a provider failure as 200 + {"error": ...}. Forwarding first and
    reading after is what produced "API returned an empty or malformed response
    (HTTP 200)" in the DUT session on 2026-08-23/24 -- its many background agents
    just rolled these dice more often than lighter sessions.
    """
    ctype = (r.headers.get("content-type") or "").lower()
    try:
        read1 = getattr(r, "read1", None) or r.read
        first = read1(65536) or b""
    except Exception as e:
        return f"connection died before body: {e}", b""
    if not first:
        return "connection closed before body (0 bytes)", b""
    # A 200 carrying a JSON error envelope instead of a Message / SSE stream.
    # Error envelopes are tiny so one chunk holds them whole; a large real body
    # that merely STARTS with '{' fails json.loads here and falls through as fine.
    if "event-stream" not in ctype and first.lstrip()[:1] == b"{":
        try:
            d = json.loads(first)
        except Exception:
            d = None
        if isinstance(d, dict) and "error" in d:
            return f"HTTP 200 carried an error body: {json.dumps(d['error'])[:200]}", b""
    return "ok", first


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def handle_one_request(self):
        """Claude Code cancels streams and reuses connections; both surface here as
        a reset. Left unhandled they printed a traceback per event and killed the
        handler mid-response -- 22 of them in one session."""
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

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
        pool = available(body)
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
            # Judge the response BEFORE forwarding anything. Nothing has reached
            # the client yet, so a dud still fails over invisibly -- the same
            # guarantee the 429 path already had.
            verdict, first = _classify(r)
            if verdict != "ok":
                try:
                    r.close()
                except Exception:
                    pass
                cool(k["name"], DUD_COOLDOWN, quiet=True)
                last = (502, verdict.encode())
                log(f"DUD on {k['name']}: {verdict}, failing over")
                continue
            ctype = (r.headers.get("content-type") or "").split(";")[0]
            log(f"OK {k['name']} {r.status} {ctype} {self.command} {self.path}")
            with _lock:
                _affinity[fingerprint(body)] = k["name"]   # stick to whoever served
            self._stream(r, k["name"], first)
            return

        code, err = last or (502, b"no upstream")
        self._fail(code, err.decode("utf8", "replace")[:300])

    def _stream(self, r, name, first=b""):
        """Forward the response as it arrives.

        Two faults here took down a live session (Claude Code reported "0 stream
        events received" and named the proxy):

        1. read(1024) BLOCKS until it has a full 1024 bytes. SSE events are small,
           so a slow turn produced nothing on the wire until the buffer happened to
           fill -- the client gave up first. read1() returns whatever one syscall
           yields, so each event leaves immediately. A synthetic fast reply hid this
           because it filled the buffer at once; a real turn does not.
        2. Manual chunked framing. Re-encoding a body we do not need to touch is
           pure risk, and a malformed frame is what made the client see "JSON but
           not a Message" on its non-streaming retry. Connection: close ends the
           body at EOF instead -- one extra TCP setup per request on loopback, in
           exchange for no framing of our own to get wrong.

        `first` is the chunk _classify already read; by the time we are called the
        response has proven itself real, and re-reading would drop that data.
        """
        self.send_response(r.status)
        for k, v in r.headers.items():
            if k.lower() in ("transfer-encoding", "connection", "content-length",
                             "content-encoding", "keep-alive"):
                continue
            self.send_header(k, v)
        self.send_header("X-Relay-Key", name)
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        read1 = getattr(r, "read1", None) or r.read
        try:
            chunk = first
            while chunk:
                self.wfile.write(chunk)
                self.wfile.flush()
                chunk = read1(65536)
        except (BrokenPipeError, ConnectionResetError):
            pass          # the client hung up mid-answer; nothing to salvage
        except Exception as e:
            log(f"STREAM ERROR on {name}: {e}")

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
