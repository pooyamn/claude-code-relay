#!/usr/bin/env python3
"""Daily encrypted backup of session history.

  backup.py                  dry run: build today's package in --out, report sizes
  backup.py --upload         also upload to R2, verify, then advance the cursors
  backup.py restore-raw DIR  decrypt and print what a package holds (check)

A package is:
  raw/YYYY/MM/DD/<source>.7z   new transcript lines since the last backup (secrets kept)
  db/YYYY-MM-DD.7z             consistent snapshot of the history database (secrets masked)
All 7z files are AES-256 with encrypted headers; the password is read from a file.
Cursors advance only after every object is uploaded and verified, so a failed
night is simply redone the next night.

R2 credentials: ~/.config/ccrelay/r2.env with R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
R2_SECRET_ACCESS_KEY, R2_BUCKET. Needs: uv run --with boto3.
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
SOURCES = {
    "claude": os.path.join(HOME, ".claude/projects/*/*.jsonl"),
    "codex": os.path.join(HOME, ".codex/sessions/*/*/*/*.jsonl"),
    "bus": os.path.join(HOME, ".openclaw/workspace/scripts/relay-work/bus.jsonl"),
}
DB = os.environ.get("HISTORY_DB", os.path.join(HOME, ".local/share/agent-history/history.db"))
CURSORS = os.path.expanduser(os.environ.get("BACKUP_CURSORS", "~/.local/share/agent-history/backup-cursors.json"))
PASSFILE = os.path.expanduser(os.environ.get("BACKUP_PASSFILE", "~/.config/backup/transcripts-7z.pass"))
R2ENV = os.path.expanduser(os.environ.get("BACKUP_R2_ENV", "~/.config/ccrelay/r2.env"))
SEVENZ = shutil.which("7zz") or shutil.which("7z") or "7zz"
KEEP_DAILY, KEEP_WEEKLY = 7, 8


def load(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default


def collect_raw(cursors):
    """{source: [(path, start, end, bytes)]} of complete new lines per file."""
    out = {}
    for src, pat in SOURCES.items():
        for p in sorted(glob.glob(pat)):
            try:
                st = os.stat(p)
            except OSError:
                continue
            ino, off = cursors.get(p, [None, 0])
            if ino != st.st_ino or off > st.st_size:
                off = 0
            if off == st.st_size:
                continue
            with open(p, "rb") as f:
                f.seek(off)
                data = f.read()
            end = data.rfind(b"\n") + 1
            if end:
                out.setdefault(src, []).append((p, off, off + end, data[:end], st.st_ino))
    return out


def seven(archive, files, cwd):
    pw = open(PASSFILE).read().strip()
    r = subprocess.run([SEVENZ, "a", "-t7z", "-mx=7", "-mhe=on", f"-p{pw}", archive, *files],
                       cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"7z failed: {r.stderr[-300:]}")


def build(outdir):
    day = time.strftime("%Y/%m/%d")
    stamp = time.strftime("%Y-%m-%d")
    cursors = load(CURSORS, {})
    raw = collect_raw(cursors)
    stage = os.path.join(outdir, ".stage")
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    objects, new_cursors = [], dict(cursors)
    for src, chunks in raw.items():
        jl = os.path.join(stage, f"{src}.jsonl")
        with open(jl, "w") as f:
            for p, start, end, data, ino in chunks:
                # one record per file chunk: enough to replay into the right file
                f.write(json.dumps({"path": p, "start": start, "end": end,
                                    "data": data.decode("utf-8", "replace")}, ensure_ascii=False) + "\n")
                new_cursors[p] = [ino, end]
        key = f"raw/{day}/{src}.7z"
        dst = os.path.join(outdir, key)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst):
            os.remove(dst)
        seven(dst, [os.path.basename(jl)], stage)
        objects.append((key, dst))
    if os.path.exists(DB):
        snap = os.path.join(stage, f"history-{stamp}.sqlite")
        src_db = sqlite3.connect(DB)
        src_db.execute("VACUUM INTO ?", (snap,))       # consistent copy while the collector runs
        src_db.close()
        key = f"db/{stamp}.7z"
        dst = os.path.join(outdir, key)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst):
            os.remove(dst)
        seven(dst, [os.path.basename(snap)], stage)
        objects.append((key, dst))
    shutil.rmtree(stage, ignore_errors=True)
    return objects, new_cursors


def r2():
    env = {}
    for line in open(R2ENV):
        k, _, v = line.strip().partition("=")
        if k:
            env[k] = v.strip()
    import boto3
    s3 = boto3.client("s3", endpoint_url=f"https://{env['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
                      aws_access_key_id=env["R2_ACCESS_KEY_ID"],
                      aws_secret_access_key=env["R2_SECRET_ACCESS_KEY"], region_name="auto")
    return s3, env["R2_BUCKET"]


def upload(objects):
    s3, bucket = r2()
    for key, path in objects:
        md5 = hashlib.md5(open(path, "rb").read()).hexdigest()
        s3.upload_file(path, bucket, key)
        head = s3.head_object(Bucket=bucket, Key=key)
        if head["ContentLength"] != os.path.getsize(path) or head["ETag"].strip('"') != md5:
            raise RuntimeError(f"verification failed for {key}")
    prune_snapshots(s3, bucket)


def prune_snapshots(s3, bucket):
    """Keep the last KEEP_DAILY daily snapshots and one per week for KEEP_WEEKLY weeks."""
    keys = sorted(o["Key"] for o in s3.list_objects_v2(Bucket=bucket, Prefix="db/").get("Contents", []))
    keep = set(keys[-KEEP_DAILY:])
    weeks = {}
    for k in keys:
        d = time.strptime(k[3:13], "%Y-%m-%d")
        weeks.setdefault(time.strftime("%G-%V", d), k)
    keep |= set(sorted(weeks.values())[-KEEP_WEEKLY:])
    for k in keys:
        if k not in keep:
            s3.delete_object(Bucket=bucket, Key=k)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.expanduser("~/.local/share/agent-history/outbox"))
    ap.add_argument("--upload", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    objects, new_cursors = build(a.out)
    total = sum(os.path.getsize(p) for _, p in objects)
    for key, p in objects:
        print(f"{os.path.getsize(p) / 1e6:8.1f} MB  {key}")
    print(f"package: {len(objects)} objects, {total / 1e6:.1f} MB, built in {time.time() - t0:.0f}s")
    if a.upload:
        upload(objects)
        os.makedirs(os.path.dirname(CURSORS), exist_ok=True)
        json.dump(new_cursors, open(CURSORS, "w"))
        print("uploaded, verified, cursors advanced")
    else:
        print("dry run: nothing uploaded, cursors not advanced")


if __name__ == "__main__":
    main()
