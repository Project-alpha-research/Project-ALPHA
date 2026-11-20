"""`/api/follow/today` and `/api/follow/{id}` relay the CLI; the relay is faked here."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alpha_web.api import follow as follow_api
from alpha_web.app import create_app

TAIL = "Paper only. Forward use; not research. Not advice."
ROW: dict[str, Any] = {
    "follow_id": "d80ba9a5a0bc",
    "group": "new_signal",
    "name": "Gaps in quiet stocks close within a week",
    "kind": "rule_test",
    "card_id": "7634f180ca16",
    "asset": "AAA",
    "decision": "would buy at the next open",
    "entry_kind": "bar",
    "readings": {"fast_sma": 101.2},
    "paper": {
        "open": False,
        "units": 0.0,
        "entry_price": None,
        "equity": 10000.0,
        "equity_pct": 0.0,
    },
    "session_date": "2026-11-19",
    "sessions_ago": 0,
    "as_of_text": "as of the close of 2026-11-19; the newest session",
    "behind": False,
    "calendar": "XNYS",
    "started_at": "2026-11-09T08:00:00+00:00",
}
TODAY: dict[str, Any] = {
    "as_of": "2026-11-20T01:00:00+00:00",
    "paper": True,
    "followed": 1,
    "behind": 0,
    "markets": [{"calendar": "XNYS", "newest_closed_session": "2026-11-19"}],
    "groups": [{"key": "new_signal", "title": "NEW SIGNAL", "count": 1}],
    "rows": [ROW],
    "notice": TAIL,
}
SHOW: dict[str, Any] = {
    "record": {
        "follow_id": "d80ba9a5a0bc",
        "kind": "rule_test",
        "source_id": "a" * 16,
        "assets": ["AAA"],
        "card_id": "",
        "paper_account_percent": 10.0,
        "started_at": "2026-11-09T08:00:00Z",
        "version": 1,
        "spec_sha256": "0" * 64,
        "supersedes": "",
        "schema": "AlphaFollowV1",
    },
    "state": "active",
    "entries": {"bar": 2, "start": 1},
    "head": "1" * 64,
    "recent": [
        {
            "session": "2026-11-19",
            "kind": "bar",
            "words": "holding",
            "fills": [],
            "readings": {"fast_sma": 101.2},
            "equity_pct": 1.5,
            "replay_agrees": True,
        }
    ],
    "paper": {"start": 10000.0, "equity": 10150.0, "equity_pct": 1.5, "units": 12.5},
    "replay": {"agrees": True, "checked": 3, "differences": []},
    "reading": "open paper position",
    "long_at_start": False,
    "waiting_for_first_bar": False,
    "stop_reason": "",
    "path": "/not/shown",
}


class Relay:
    def __init__(self, answer: Any = None, error: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self.answer, self.error = answer, error

    def __call__(self, args: list[str], **kwargs: Any) -> Any:
        self.calls.append(args)
        assert kwargs["timeout_seconds"] > 0
        if self.error:
            raise RuntimeError(self.error)
        return self.answer


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relay: Relay) -> TestClient:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(follow_api, "_run_json", relay)
    return TestClient(create_app())


def test_today_relays_the_command_and_keeps_its_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    relay = Relay(TODAY)
    body = _client(tmp_path, monkeypatch, relay).get("/api/follow/today").json()
    assert relay.calls == [["follow", "today", "--json"]]
    assert body["rows"][0]["name"] == ROW["name"] and body["notice"] == TAIL
    assert body["groups"][0]["key"] == "new_signal" and body["markets"][0]["calendar"] == "XNYS"


def test_today_with_no_follows_is_an_empty_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = {**TODAY, "followed": 0, "behind": 0, "rows": [], "groups": [], "markets": []}
    body = _client(tmp_path, monkeypatch, Relay(empty)).get("/api/follow/today").json()
    assert body["rows"] == [] and body["followed"] == 0


def test_a_broken_journal_row_passes_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = {
        "follow_id": "cd8e62d019e6",
        "group": "late_or_missed",
        "name": "cd8e62d019e6",
        "asset": "",
        "decision": "the journal cannot be read: run `alpha follow verify cd8e62d019e6`",
        "behind": False,
        "calendar": None,
        "sessions_ago": None,
        "session_date": None,
        "readings": {},
        "paper": {},
        "entry_kind": "broken",
        "as_of_text": "cannot be read",
    }
    relay = Relay({**TODAY, "rows": [broken]})
    body = _client(tmp_path, monkeypatch, relay).get("/api/follow/today").json()
    assert body["rows"][0]["entry_kind"] == "broken"


def test_show_relays_one_follow_and_hides_the_server_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    relay = Relay(SHOW)
    body = _client(tmp_path, monkeypatch, relay).get("/api/follow/d80ba9a5a0bc").json()
    assert relay.calls == [["follow", "show", "d80ba9a5a0bc", "--json"]]
    assert body["record"]["assets"] == ["AAA"] and body["replay"]["agrees"] is True
    assert "path" not in body and body["recent"][0]["equity_pct"] == 1.5


@pytest.mark.parametrize(
    "bad", ["xyz", "abc", "d80ba9a5a0bcd", "D80BA9A5A0BC", "..%2Fetc", "--json", "today2"]
)
def test_a_bad_id_is_refused_before_any_command_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    relay = Relay(SHOW)
    response = _client(tmp_path, monkeypatch, relay).get(f"/api/follow/{bad}")
    assert response.status_code in {404, 422} and relay.calls == []


@pytest.mark.parametrize("good", ["abcd", "0123456789ab"])
def test_four_to_twelve_hex_characters_are_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, good: str
) -> None:
    relay = Relay(SHOW)
    assert _client(tmp_path, monkeypatch, relay).get(f"/api/follow/{good}").status_code == 200
    assert relay.calls == [["follow", "show", good, "--json"]]


def test_a_command_failure_is_plain_error_json_not_a_500(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch, Relay(error="Unknown follow id"))
    for path in ("/api/follow/today", "/api/follow/abcd"):
        response = client.get(path)
        assert response.status_code == 409
        assert response.json()["message"] == "Unknown follow id"


def test_a_timeout_is_a_504_in_plain_words(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(
        tmp_path, monkeypatch, Relay(error="alpha follow today --json timed out after 30 seconds")
    )
    response = client.get("/api/follow/today")
    assert response.status_code == 504 and "timed out" in response.json()["message"]


def test_no_route_starts_updates_or_stops_a_follow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch, Relay(TODAY))
    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)("/api/follow/today").status_code in {404, 405}
        assert getattr(client, method)("/api/follow/abcd").status_code in {404, 405}
