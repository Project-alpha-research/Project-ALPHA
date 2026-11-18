"""Canonical market-data identity across action permutations and earlier successful runs."""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta

import pytest

from alpha_cli._runner import source_fingerprint
from alpha_core import ActionType, Bar, CorporateAction

EX = date(2020, 3, 20)
BAR = Bar(
    symbol="SPY", ts=datetime(2020, 3, 20, tzinfo=UTC), open=2, high=3, low=1, close=2, volume=7
)
DIVIDEND = CorporateAction(
    symbol="SPY",
    action_type=ActionType.DIVIDEND,
    ex_date=EX,
    announce_date=EX - timedelta(days=7),
    record_date=EX,
    pay_date=EX + timedelta(days=7),
    amount=1,
)


def _digest(bars: list[Bar], actions: list[CorporateAction]) -> str:
    """The origin/main row encoding. The caller supplies the action order to check."""
    rows = [
        (
            a.symbol,
            a.action_type.value,
            a.ex_date.isoformat(),
            a.announce_date.isoformat() if a.announce_date else None,
            a.record_date.isoformat() if a.record_date else None,
            a.pay_date.isoformat() if a.pay_date else None,
            a.ratio,
            a.amount,
        )
        for a in actions
    ]
    bar_rows = sorted(
        (b.symbol, b.ts.isoformat(), b.open, b.high, b.low, b.close, b.volume) for b in bars
    )
    encoded = json.dumps(
        {"bars": bar_rows, "dividends": rows},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(b"project-alpha-observed-market-data-v1\0" + encoded.encode()).hexdigest()


@pytest.mark.parametrize("field", ["announce_date", "record_date", "pay_date"])
def test_missing_date_sorts_first_in_either_input_order(field: str) -> None:
    missing = DIVIDEND.model_copy(update={field: None, "amount": 2.0})
    expected = _digest([BAR], [missing, DIVIDEND])
    for pair in ([missing, DIVIDEND], [DIVIDEND, missing]):
        assert source_fingerprint([BAR], dividends=pair) == expected


@pytest.mark.parametrize(
    "actions",
    [
        [],
        [DIVIDEND],
        [
            DIVIDEND.model_copy(update={"pay_date": EX + timedelta(days=12)}),
            DIVIDEND,
            DIVIDEND.model_copy(update={"symbol": "QQQ"}),
            DIVIDEND.model_copy(update={"amount": 0.5}),
        ],
    ],
)
def test_fingerprint_matches_original_tuple_order(actions: list[CorporateAction]) -> None:
    ordered = sorted(
        actions,
        key=lambda a: (
            a.symbol,
            a.action_type.value,
            a.ex_date,
            a.announce_date,
            a.record_date,
            a.pay_date,
            a.ratio,
            a.amount,
        ),
    )
    bars = [BAR.model_copy(update={"ts": BAR.ts + timedelta(days=1)}), BAR]
    assert source_fingerprint(bars, dividends=actions) == _digest(bars, ordered)
