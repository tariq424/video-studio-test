"""Flow still rung (owner, 2026-11-07): route r14 makes one still through Flow's agent and never approves a quote above 0
credits; it sits after the fast free services (Cloudflare, Hugging Face) and before the paid / slow ones."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from studio import config, imagegen  # noqa: E402
from studio.routelib import routes  # noqa: E402


def test_route_registered():
    r = next(x for x in routes.ROUTES if x["id"] == "r14")
    assert r["fn"] is routes.r14_flow_image and "0 credits" in r["proves"]
    assert "not a grid" in routes.FLOW_IMAGE_ASK and "No text" in routes.FLOW_IMAGE_ASK


def test_provider_order_cheapest_first():
    assert "flow" in imagegen.PROVIDERS
    order = config.DEFAULTS["imagegen_providers"]
    assert order.index("cloudflare") < order.index("hf") < order.index("flow") < order.index("chatgpt")
    assert "flow" not in imagegen.GOOGLE_IMAGE_PROVIDERS   # it keeps its place; Gemini alone is pushed last


def test_flow_off_is_skipped(tmp_path):
    with pytest.raises(imagegen.Skip):
        imagegen._session_flow({"flow_on": False}, {"vo": "x"}, "9:16", tmp_path / "o.jpg", 60, print, None)


def test_never_spends_credits():
    src = (Path(__file__).resolve().parents[1] / "app" / "studio" / "routelib" / "routes.py").read_text(encoding="utf-8")
    body = src[src.index("def r14_flow_image"):src.index("# ------------------------------------------------------------------ local/GPU\n")]
    assert "if cost == 0:" in body and "Reject" in body and "Always approve" not in body
