"""Add (merge) rows into the local media database with media_db.upsert (sqlite on F: is written by the PC's own Python).
Run: python scripts/media_db_add.py <rows.json>   (a JSON list of row dicts; columns as media_db.COLS) -> prints the result"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import config, media_db  # noqa: E402


def main():
    rows = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    cfg = config.load(); db = media_db.connect(cfg)
    before = db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    for r in rows: media_db.upsert(db, r)
    after = db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    for r in rows:
        got = db.execute("SELECT url, local_path, topic, place FROM items WHERE url=?", (media_db.canon(r["url"]),)).fetchone()
        print("row:", got)
    print(f"items: {before} -> {after}")


if __name__ == "__main__":
    main()
