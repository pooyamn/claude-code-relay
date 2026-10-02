#!/usr/bin/env python3
"""Session history: ingest Claude/Codex transcripts and the agent bus into one
local SQLite database with full-text (FTS5) and vector (sqlite-vec) search.

Run with uv so sqlite can load extensions (macOS system Python cannot):

  uv run --python 3.12 --with sqlite-vec --with fastembed history.py ingest
  uv run ... history.py embed [--limit N]
  uv run ... history.py search "query" [--limit 10] [--mode hybrid|text|vector]
  uv run ... history.py stats

Ingest is incremental: a per-file (inode, offset) cursor means nothing is read
twice and a stopped collector catches up. Transcripts are only READ; nothing
here deletes or rewrites them (pruning is a separate, later step).
"""
import argparse
import glob
import json
import os
import re
import sqlite3
import sys
import time

HOME = os.path.expanduser("~")
DB = os.environ.get("HISTORY_DB", os.path.join(HOME, ".local/share/agent-history/history.db"))
MODEL = os.environ.get("HISTORY_EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
DIM = int(os.environ.get("HISTORY_EMBED_DIM", "384"))
TOOL_CAP = 2048          # tool outputs: the full text stays in the raw files
TEXT_CAP = 20000
SOURCES = {
    "claude": os.path.join(HOME, ".claude/projects/*/*.jsonl"),
    "codex": os.path.join(HOME, ".codex/sessions/*/*/*/*.jsonl"),
    "bus": os.path.join(HOME, ".openclaw/workspace/scripts/relay-work/bus.jsonl"),
}

# --- secret masking ----------------------------------------------------------
_SECRETS = [
    (re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{30,}"), "[telegram-token]"),
    (re.compile(r"\bsk-(?:ant-|proj-|or-)?[A-Za-z0-9_-]{20,}"), "[api-key]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"), "[github-token]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[aws-key]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[private-key]"),
    (re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token|bearer)\b(\s*[:=]\s*|\s+)([\"']?)([A-Za-z0-9_\-./+=]{12,})\3"),
     lambda m: f"{m.group(1)}{m.group(2)}[masked]"),
]


# Random secrets (an archive password, an R2 secret) match no pattern, so the
# exact values are also read from the files that hold them and replaced
# wherever they appear. Measured 2026-10-01: the transcript-archive password
# reached 3 messages unmasked under patterns alone.
SECRET_FILES = [p for p in os.environ.get("HISTORY_SECRET_FILES", "").split(":") if p] or [
    "~/.config/backup/transcripts-7z.pass",
    "~/.config/ccrelay/env-test", "~/.config/ccrelay/env-prod", "~/.config/ccrelay/r2.env",
    "~/.openclaw/workspace/scripts/relay-claude-settings-*.json",
    "~/.openclaw/openclaw.json",
]
_KNOWN = None


def _known_secrets():
    global _KNOWN
    if _KNOWN is None:
        vals = set()
        for pat in SECRET_FILES:
            for p in glob.glob(os.path.expanduser(pat)):
                try:
                    raw = open(p, errors="ignore").read()
                except OSError:
                    continue
                if p.endswith(".json"):
                    # values of keys that look secret
                    vals.update(re.findall(r'"(?:[A-Za-z_]*(?:TOKEN|KEY|SECRET|PASSWORD|token|key|secret|password)[A-Za-z_]*)"\s*:\s*"([^"]{12,})"', raw))
                else:
                    for line in raw.splitlines():
                        v = line.split("=", 1)[-1].strip().strip("'\"")
                        if len(v) >= 12:
                            vals.add(v)
        _KNOWN = sorted(vals, key=len, reverse=True)
    return _KNOWN


def mask(text):
    for v in _known_secrets():
        if v in text:
            text = text.replace(v, "[secret]")
    for rx, rep in _SECRETS:
        text = rx.sub(rep, text)
    return text


# --- database ----------------------------------------------------------------
def connect(load_vec=True):
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    db = sqlite3.connect(DB)
    db.execute("PRAGMA journal_mode=WAL")
    if load_vec:
        import sqlite_vec
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
    db.executescript(f"""
    CREATE TABLE IF NOT EXISTS cursors(path TEXT PRIMARY KEY, inode INTEGER, offset INTEGER);
    CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, tool TEXT, project TEXT, cwd TEXT,
        title TEXT, started TEXT, ended TEXT);
    CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, session TEXT, ts TEXT, role TEXT,
        kind TEXT, text TEXT, src TEXT);
    CREATE INDEX IF NOT EXISTS messages_session ON messages(session, ts);
    CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(text, content='messages', content_rowid='id',
        tokenize='unicode61 remove_diacritics 2');
    CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
        INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text); END;
    CREATE TABLE IF NOT EXISTS embedded(id INTEGER PRIMARY KEY);
    """)
    if load_vec:
        db.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS messages_vec USING vec0(embedding float[{DIM}])")
    return db


# --- parsers -----------------------------------------------------------------
def _blocks_text(content):
    """Claude content: str or list of blocks -> [(kind, text)]."""
    if isinstance(content, str):
        return [("text", content)]
    out = []
    for b in content or []:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "text":
            out.append(("text", b.get("text") or ""))
        elif t == "tool_use":
            out.append(("tool_call", f"{b.get('name')}: {json.dumps(b.get('input'), ensure_ascii=False)}"))
        elif t == "tool_result":
            c = b.get("content")
            if isinstance(c, list):
                c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
            out.append(("tool_result", str(c or "")))
    return out


def parse_claude(rec, path):
    sid = os.path.basename(path)[:-6]
    t = rec.get("type")
    if t not in ("user", "assistant"):
        return sid, None, []
    msg = rec.get("message") or {}
    rows = [(rec.get("timestamp", ""), msg.get("role") or t, k, x) for k, x in _blocks_text(msg.get("content"))]
    meta = {"cwd": rec.get("cwd"), "project": os.path.basename(os.path.dirname(path))}
    return sid, meta, rows


def parse_codex(rec, path):
    m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", os.path.basename(path))
    sid = m.group(1) if m else os.path.basename(path)
    ts, p = rec.get("timestamp", ""), rec.get("payload") or {}
    t = p.get("type")
    if rec.get("type") == "session_meta":
        return sid, {"cwd": p.get("cwd"), "project": os.path.basename(p.get("cwd") or "")}, []
    if t == "message" and p.get("role") in ("user", "assistant"):
        txt = "".join(c.get("text", "") for c in p.get("content", []) if isinstance(c, dict))
        if p.get("role") == "user" and txt.startswith("<"):        # environment/context blocks
            return sid, None, []
        return sid, None, [(ts, p["role"], "text", txt)]
    if t in ("function_call", "custom_tool_call"):
        return sid, None, [(ts, "assistant", "tool_call", f"{p.get('name')}: {p.get('arguments') or p.get('input') or ''}")]
    if t in ("function_call_output", "custom_tool_call_output"):
        out = p.get("output")
        if isinstance(out, dict):
            out = out.get("content") or json.dumps(out)
        return sid, None, [(ts, "tool", "tool_result", str(out or ""))]
    return sid, None, []


def parse_bus(rec, path):
    return "bus", None, [(rec.get("ts", ""), "agent", "bus",
                          f"{rec.get('from')} → {rec.get('to')} (hop {rec.get('hop')}, {rec.get('state')}): {rec.get('text', '')}")]


PARSERS = {"claude": parse_claude, "codex": parse_codex, "bus": parse_bus}


# --- ingest ------------------------------------------------------------------
def ingest(db):
    added = 0
    for src, pattern in SOURCES.items():
        parse = PARSERS[src]
        for path in sorted(glob.glob(pattern)):
            try:
                st = os.stat(path)
            except OSError:
                continue
            row = db.execute("SELECT inode, offset FROM cursors WHERE path=?", (path,)).fetchone()
            offset = row[1] if row and row[0] == st.st_ino and row[1] <= st.st_size else 0
            if offset == st.st_size:
                continue
            with open(path, "rb") as f:
                f.seek(offset)
                data = f.read()
            # only complete lines; a partly written last line is read next time
            end = data.rfind(b"\n") + 1
            if end == 0:
                continue
            for line in data[:end].decode("utf-8", "replace").splitlines():
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                sid, meta, rows = parse(rec, path)
                if meta or rows:
                    db.execute("INSERT OR IGNORE INTO sessions(id, tool, project) VALUES (?,?,?)",
                               (sid, src, (meta or {}).get("project")))
                if meta and meta.get("cwd"):
                    db.execute("UPDATE sessions SET cwd=COALESCE(cwd, ?) WHERE id=?", (meta["cwd"], sid))
                for ts, role, kind, text in rows:
                    text = (text or "").strip()
                    if not text:
                        continue
                    cap = TOOL_CAP if kind.startswith("tool") else TEXT_CAP
                    db.execute("INSERT INTO messages(session, ts, role, kind, text, src) VALUES (?,?,?,?,?,?)",
                               (sid, ts, role, kind, mask(text[:cap]), src))
                    db.execute("UPDATE sessions SET started=COALESCE(started, ?), ended=? WHERE id=?",
                               (ts, ts, sid))
                    if role == "user" and kind == "text":
                        db.execute("UPDATE sessions SET title=COALESCE(title, ?) WHERE id=?",
                                   (text[:120].replace("\n", " "), sid))
                    added += 1
            db.execute("INSERT OR REPLACE INTO cursors VALUES (?,?,?)", (path, st.st_ino, offset + end))
            db.commit()
    return added


# --- embeddings --------------------------------------------------------------
_model = None


def embedder():
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(MODEL)
    return _model


def embed(db, limit=None, batch=64):
    """Vectors for user/assistant text and bus lines (not tool output: noisy, huge)."""
    import sqlite_vec
    q = ("SELECT m.id, m.text FROM messages m LEFT JOIN embedded e ON e.id=m.id "
         "WHERE e.id IS NULL AND m.kind IN ('text','bus') AND length(m.text) > 20 ORDER BY m.id")
    if limit:
        q += f" LIMIT {int(limit)}"
    rows = db.execute(q).fetchall()
    done = 0
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        vecs = list(embedder().embed([t[:2000] for _, t in chunk]))
        for (mid, _), v in zip(chunk, vecs):
            db.execute("INSERT INTO messages_vec(rowid, embedding) VALUES (?, ?)",
                       (mid, sqlite_vec.serialize_float32(list(map(float, v)))))
            db.execute("INSERT INTO embedded(id) VALUES (?)", (mid,))
        db.commit()
        done += len(chunk)
    return done


# --- search ------------------------------------------------------------------
def _fts_query(q):
    words = re.findall(r"\w+", q, flags=re.U)
    return " OR ".join(f'"{w}"' for w in words) if words else '""'


def search(db, query, limit=10, mode="hybrid"):
    """Reciprocal-rank fusion of BM25 and vector neighbours."""
    import sqlite_vec
    scores, k = {}, 60
    if mode in ("hybrid", "text"):
        for rank, (mid,) in enumerate(db.execute(
                "SELECT rowid FROM messages_fts WHERE messages_fts MATCH ? ORDER BY bm25(messages_fts) LIMIT 50",
                (_fts_query(query),))):
            scores[mid] = scores.get(mid, 0) + 1 / (k + rank)
    if mode in ("hybrid", "vector"):
        v = list(embedder().embed([query]))[0]
        for rank, (mid, _d) in enumerate(db.execute(
                "SELECT rowid, distance FROM messages_vec WHERE embedding MATCH ? AND k = 50 ORDER BY distance",
                (sqlite_vec.serialize_float32(list(map(float, v))),))):
            scores[mid] = scores.get(mid, 0) + 1 / (k + rank)
    best = sorted(scores, key=scores.get, reverse=True)[:limit]
    out = []
    for mid in best:
        r = db.execute("SELECT m.session, m.ts, m.role, m.kind, m.text, s.tool, s.project, s.cwd "
                       "FROM messages m JOIN sessions s ON s.id=m.session WHERE m.id=?", (mid,)).fetchone()
        out.append(dict(id=mid, session=r[0], ts=r[1], role=r[2], kind=r[3], text=r[4],
                        tool=r[5], project=r[7] or r[6], score=round(scores[mid], 4)))
    return out


def stats(db):
    return {
        "db": DB, "size_mb": round(os.path.getsize(DB) / 1e6, 1),
        "sessions": db.execute("SELECT count(*) FROM sessions").fetchone()[0],
        "messages": db.execute("SELECT count(*) FROM messages").fetchone()[0],
        "embedded": db.execute("SELECT count(*) FROM embedded").fetchone()[0],
        "by_source": dict(db.execute("SELECT src, count(*) FROM messages GROUP BY src").fetchall()),
    }


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest")
    e = sub.add_parser("embed"); e.add_argument("--limit", type=int)
    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--limit", type=int, default=10)
    s.add_argument("--mode", default="hybrid", choices=["hybrid", "text", "vector"])
    sub.add_parser("stats")
    a = ap.parse_args()
    db = connect()
    t0 = time.time()
    if a.cmd == "ingest":
        print(f"ingested {ingest(db)} messages in {time.time() - t0:.1f}s")
    elif a.cmd == "embed":
        print(f"embedded {embed(db, a.limit)} messages in {time.time() - t0:.1f}s")
    elif a.cmd == "search":
        for r in search(db, a.query, a.limit, a.mode):
            print(f"{r['score']:.4f} {r['ts'][:16]} {r['tool']:<6} {(r['project'] or '')[-40:]:<40} "
                  f"{r['role']:<9} {r['text'][:140].replace(chr(10), ' ')}")
    elif a.cmd == "stats":
        print(json.dumps(stats(db), indent=2))


if __name__ == "__main__":
    main()
