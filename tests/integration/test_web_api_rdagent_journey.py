"""Read a synthetic published journey through ASGI without opening a socket."""

from __future__ import annotations

import asyncio
import json
import shlex
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image

from alpha_web.app import create_app


def test_stored_journey_and_figures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "runs"
    monkeypatch.setenv("ALPHA_RDAGENT_RUNS_DIR", str(root))
    run = root / "synthetic run"
    run.mkdir(parents=True)
    (run / "receipt.json").write_text(
        json.dumps({"schema": "AlphaRdagentFactorRunReceiptV1", "run_id": "example"})
    )
    name = "sample idea"
    first = {"iteration": 0, "name": name, "code_sha256": "a" * 64}
    second = {**first, "iteration": 1, "code_sha256": "b" * 64}
    for identity in (first, second):
        folder = run / f"evaluations/iter-{identity['iteration']}"
        folder.mkdir(parents=True)
        (folder / "result.json").write_text(
            json.dumps(
                {
                    "iteration": identity["iteration"],
                    "factors": [{**identity, "status": "SCREEN_FAIL"}],
                }
            )
        )
    stored = run / "journey/0-sample idea-aaaaaaaa"
    stored.mkdir(parents=True)
    story = {
        **first,
        "steps": [
            {"title": f"Step {i}", "figure": "signal.png" if i == 2 else None} for i in range(1, 8)
        ],
        "figures": {"signal": {"file": "signal.png", "data": "signal.json"}},
    }
    document = stored / "journey.json"
    document.write_text(json.dumps(story))
    image = BytesIO()
    Image.new("RGB", (1, 1)).save(image, format="PNG")
    (stored / "signal.png").write_bytes(image.getvalue())
    (stored / "unlisted.png").write_bytes(image.getvalue())

    async def exercise() -> None:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            base = "/api/rdagent/runs/example"
            detail = await client.get(base)
            assert detail.status_code == 200
            ideas = detail.json()["journeys"]
            assert [(i["name"], i["verdict"], i["built"]) for i in ideas] == [
                (name, "SCREEN_FAIL", True),
                (name, "SCREEN_FAIL", False),
            ]
            path = f"{base}/journeys/{ideas[0]['id']}"
            assert (await client.get(path)).json() == story
            figure = await client.get(path + "/figures/signal.png")
            assert figure.headers["content-type"] == "image/png"
            assert figure.content == image.getvalue()
            for bad in ("unlisted.png", "signal.json", "..%2Fsignal.png", "%2Ftmp%2Fsignal.png"):
                assert (await client.get(path + "/figures/" + bad)).status_code == 404
            missing = await client.get(f"{base}/journeys/{ideas[1]['id']}")
            assert missing.json()["reason"] == "Journey not built yet"
            assert shlex.split(missing.json()["command"]) == [
                "uv",
                "run",
                "alpha",
                "ledger",
                "journey",
                "--run-dir",
                str(run),
                "--factor",
                name,
            ]
            assert (await client.get(base + "/journeys/unlisted")).status_code == 404
            assert (await client.post(path)).status_code == 405
            (stored / "signal.png").unlink()
            (stored / "signal.png").symlink_to(stored / "unlisted.png")
            assert (await client.get(path + "/figures/signal.png")).status_code == 422
            document.write_text(json.dumps({**story, "code_sha256": "a" * 8 + "c" * 56}))
            assert (await client.get(path)).status_code == 422
            document.unlink()
            document.symlink_to(run / "receipt.json")
            assert (await client.get(path)).status_code == 422

    asyncio.run(exercise())
