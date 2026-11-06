"""Z005 self-check: the POC imports cleanly and the route registry holds exactly 11 routes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import server            # noqa: E402  (imports fastapi/uvicorn + routes)
import routes            # noqa: E402

assert len(routes.ROUTES) == 11, f"route registry has {len(routes.ROUTES)} routes, expected 11"
assert len({r["id"] for r in routes.ROUTES}) == 11, "duplicate route ids"
assert all(callable(r["fn"]) for r in routes.ROUTES), "non-callable route"
print(f"SELFCHECK PASS: server imports clean; {len(routes.ROUTES)} routes registered: "
      + ", ".join(r["name"] for r in routes.ROUTES))
