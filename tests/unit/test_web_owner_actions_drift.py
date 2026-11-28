"""Generated contracts carry no browser owner-action surface; owner acts stay in the trusted CLI.

This guard reads the committed OpenAPI document and the generated client instead of importing
the server, so a stale regeneration cannot bring the removed routes back unseen.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "apps/alpha-web/frontend"


def test_generated_contracts_have_no_owner_action_surface() -> None:
    openapi = json.loads((FRONTEND / "openapi.json").read_text(encoding="utf-8"))
    assert not [path for path in openapi["paths"] if "owner-auth" in path]
    schemas = openapi["components"]["schemas"]
    assert not [name for name in schemas if name.startswith(("OwnerAction", "OwnerRegistration"))]
    generated = (FRONTEND / "src/api/generated.ts").read_text(encoding="utf-8")
    assert "owner-auth" not in generated
