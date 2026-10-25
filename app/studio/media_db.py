"""The ever-growing media database (owner, 2026-10-25): every item of the owner's media we have looked at, downloaded or not.

One row per item, keyed by its Google Photos URL (or a local path for footage already on F:): date / time, place and map pin,
what it shows, whether it is usable, the search that found it, the local copy if downloaded. Searched FIRST whenever a
video needs footage of something; Google Photos only when nothing here fits.

The database lives on F: (media_db_path, default F:/code/media_db/media.db). backup() writes an AES-256-GCM encrypted copy
into the repo (backups/media_db.enc); the key is MEDIA_DB_KEY in the repo's .env, which git never sees."""
import base64
import json
import math
import os
import sqlite3
import time
from pathlib import Path

COLS = ["url", "file_name", "kind", "date", "time", "place", "lat", "lon", "description", "text_in_picture", "usable",
        "found_by", "label", "group_date", "local_path", "topic", "info", "first_seen", "updated"]
REPO = Path(__file__).resolve().parents[2]


def path(cfg):
    return Path(cfg.get("media_db_path") or "F:/code/media_db/media.db")


def connect(cfg):
    p = path(cfg); p.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(p))
    db.execute("CREATE TABLE IF NOT EXISTS items (" + ", ".join(f"{c} {'TEXT PRIMARY KEY' if c == 'url' else 'TEXT'}" for c in COLS) + ")")
    db.commit()
    return db


def canon(url):
    """One URL per item: a Google Photos link seen inside a search or an album -> https://photos.google.com/photo/<id>."""
    if "photos.google.com" in url and "/photo/" in url: return "https://photos.google.com/photo/" + url.split("/photo/", 1)[1].split("?")[0].strip("/")
    return url


def dedupe(db):
    """Merge rows whose URLs are the same item (made before canon())."""
    rows = [dict(zip(COLS, r)) for r in db.execute("SELECT * FROM items").fetchall()]
    db.execute("DELETE FROM items"); db.commit()
    for r in rows: upsert(db, r)


def upsert(db, row):
    """Merge: a field already filled is only replaced by a non-empty new value; found_by collects every search."""
    row = {k: v for k, v in row.items() if k in COLS}
    if not row.get("url"): return
    row["url"] = canon(row["url"])
    cur = db.execute("SELECT * FROM items WHERE url=?", (row["url"],)).fetchone()
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    if cur:
        old = dict(zip(COLS, cur))
        for k, v in row.items():
            if v in (None, ""): continue
            if k == "found_by" and old.get("found_by") and v not in old["found_by"].split(" | "): v = old["found_by"] + " | " + v
            old[k] = str(v)
        old["updated"] = now
        db.execute("UPDATE items SET " + ", ".join(f"{c}=?" for c in COLS[1:]) + " WHERE url=?", [old[c] for c in COLS[1:]] + [old["url"]])
    else:
        row.update(first_seen=now, updated=now)
        db.execute(f"INSERT INTO items ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", [str(v) if v is not None else "" for v in row.values()])
    db.commit()


def find(db, words=(), lat=None, lon=None, radius_m=150.0, usable_only=True):
    """Rows matching any of the words (place, description, text, label, search) and/or within radius of a pin."""
    rows = [dict(zip(COLS, r)) for r in db.execute("SELECT * FROM items").fetchall()]
    out = []
    for r in rows:
        if usable_only and r.get("usable") == "no": continue
        hay = " ".join(str(r.get(k) or "") for k in ("place", "description", "text_in_picture", "label", "found_by", "file_name")).lower()
        hit = any(w.lower() in hay for w in words if w)
        if lat is not None and r.get("lat") not in (None, "", "None"):
            try:
                d = 6371000 * math.hypot(math.radians(float(r["lat"]) - lat), math.radians(float(r["lon"]) - lon) * math.cos(math.radians(lat)))
                hit = hit or d <= radius_m
            except ValueError: pass
        if hit: out.append(r)
    return out


def _key():
    k = os.environ.get("MEDIA_DB_KEY", "")
    if not k:
        envf = REPO / ".env"
        if envf.exists():
            for line in envf.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip().startswith("MEDIA_DB_KEY="): k = line.split("=", 1)[1].strip().strip('"'); break
    if not k: raise RuntimeError("MEDIA_DB_KEY is not in the repo's .env")
    return base64.urlsafe_b64decode(k)


def backup(cfg, log=print):
    """Readable JSON-lines copy beside the db (on F:, never committed) + encrypted copy of the db into backups/ for git."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    db = connect(cfg)
    rows = [dict(zip(COLS, r)) for r in db.execute("SELECT * FROM items ORDER BY url").fetchall()]
    db.close()
    p = path(cfg)
    p.with_suffix(".jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    nonce = os.urandom(12)
    blob = nonce + AESGCM(_key()).encrypt(nonce, p.read_bytes(), b"media_db")
    out = REPO / "backups" / "media_db.enc"; out.parent.mkdir(exist_ok=True)
    out.write_bytes(blob)
    log(f"  media db: {len(rows)} row(s); encrypted backup {out}")
    return out


def restore(cfg, enc=None):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    blob = Path(enc or REPO / "backups" / "media_db.enc").read_bytes()
    path(cfg).write_bytes(AESGCM(_key()).decrypt(blob[:12], blob[12:], b"media_db"))
