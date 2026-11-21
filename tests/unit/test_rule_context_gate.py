"""Rule-spec context gate: spec fields, hash parity, gate vector, poison, fingerprint."""

from __future__ import annotations

import json
import tomllib
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import polars as pl
import pytest

from alpha_cli import _context_gate
from alpha_cli.spine.spec import IdeaSpec
from alpha_core import DataError
from tests.unit._context_attach_support import CUTOFF, bars, cot_rows, daily, store_cot

SPY = {"assets": ["SPY"], "rule": {"kind": "tsmom", "lookback": 60}}
OLD_HASHES = {
    "ma_cross": "2668857e7aa7c8b17bcb3ece3f17cdfbc2f6e80fc361721a689a5b4bdf9fbb8b",
    "breakout": "cf609eb87036468a0aa9d16e732f54c84c880b72f3cc500df13153f3417b8d1e",
    "tsmom": "0f553c403e86478bde9e020c5629544862527fb753c16417c92b7ac687c88145",
}
STORED_SPEC = (
    '{"assets":["SPY","BTC/USDT"],"costs":{"fee_bps":2.0,"slippage_bps":2.0},"idea":"y",'
    '"name":"x","rule":{"kind":"tsmom","lookback":60,"skip":0}}'
)


def _spec(**extra: object) -> IdeaSpec:
    return IdeaSpec.model_validate({**SPY, **extra})


def _stamp(day: date, hour: int = 21) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=UTC)


# Releases on Fridays at 21:00 UTC (a bar of that Friday sees them); periods are the Tuesdays.
RELEASES = [(date(2023, 1, 6), 0.2), (date(2023, 1, 13), 0.6), (date(2023, 1, 20), 0.7)]
RELEASES += [(date(2023, 1, 27), 0.1), (date(2023, 2, 3), 0.9)]


def _store(home: Path, extra: list[dict[str, object]] | None = None, last: float = 0.1) -> None:
    rows = [
        dict(
            report_date=rel - timedelta(days=3),
            nl=round(v * 1000),
            known_from=_stamp(rel),
            basis="stamp",
        )
        for rel, v in RELEASES
    ]
    store_cot(home, cot_rows([*rows, *(extra or [])]))


def _gate(
    home: Path,
    when: str,
    context: dict[str, str] | None = None,
    frame: pl.DataFrame | None = None,
    cutoff: datetime = CUTOFF,
) -> _context_gate.Gate:
    return _context_gate.build_gate(
        frame if frame is not None else bars(daily(date(2023, 1, 1), 59)),  # to Feb 28
        context=context or {"a": "cot_nc_net_oi@13874A"},
        when=when,
        calendar=None,
        data_dir=home,
        cutoff=cutoff,
    )


def _on(gate: _context_gate.Gate) -> list[date]:
    return [ts.date() for ts, on in sorted(gate.by_ts.items()) if on]


# ---- spec ----


def test_old_specs_keep_their_hash_and_stored_bytes() -> None:
    rules = {
        "ma_cross": {"kind": "ma_cross", "fast": 5, "slow": 20},
        "breakout": {"kind": "breakout", "window": 20},
        "tsmom": {"kind": "tsmom", "lookback": 252, "skip": 21},
    }
    for kind, rule in rules.items():
        assert IdeaSpec(assets=["SPY"], rule=rule).spec_sha256 == OLD_HASHES[kind]
    full = IdeaSpec(
        name="x",
        idea="y",
        assets=["SPY", "BTC/USDT"],
        rule={"kind": "tsmom", "lookback": 60},
        costs={"fee_bps": 2},
    )
    assert full.spec_sha256 == "57236305e1604185d64386743cca6d4c101d4ed0b11d6b288c71167c77158def"
    dumped = json.dumps(full.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    assert dumped == STORED_SPEC  # the stored spec.json has no context or when key
    assert "context" not in full.canonical() and "when" not in full.canonical()


def test_context_spec_parses_and_has_its_own_hash(tmp_path: Path) -> None:
    text = (
        'assets = ["SPY"]\nwhen = "es_pos > 0.8"\n[rule]\nkind = "tsmom"\nlookback = 60\n'
        '[context]\nes_pos = "cot_nc_net_pct_156w@13874A"\n'
    )
    spec = IdeaSpec.model_validate(tomllib.loads(text))
    assert spec.context == {"es_pos": "cot_nc_net_pct_156w@13874A"} and spec.when == "es_pos > 0.8"
    assert spec.spec_sha256 != _spec().spec_sha256
    other = _spec(context=spec.context, when="es_pos > 0.9")
    assert other.spec_sha256 != spec.spec_sha256
    assert IdeaSpec.model_validate_json(spec.model_dump_json()) == spec


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"when": "a > 1"}, "when needs a context"),
        ({"context": {"a": "cot_nc_net_oi@K"}}, "context needs a when"),
        ({"context": {"a": "cot_nc_net_oi@K"}, "when": "b > 1"}, "unknown alias"),
        ({"context": {"a": "no_such@K"}, "when": "a > 1"}, "unknown context series"),
        ({"context": {"a": "cot_nc_net_oi"}, "when": "a > 1"}, "series@key"),
        ({"context": {"close": "cot_nc_net_oi@K"}, "when": "close > 1"}, "plain name"),
        ({"context": {"a": "cot_nc_net_oi@K"}, "when": "a + 1"}, "true/false"),
        ({"context": {"a": "cot_nc_net_oi@K"}, "when": "a >"}, "not a valid condition"),
        ({"context": {"a": "cot_nc_net_oi@K"}, "when": "__import__('os')"}, "allowed functions"),
        ({"context": {"a": "cot_nc_net_oi@K"}, "when": "a.real > 1"}, "allowed"),
    ],
)
def test_bad_context_specs_say_why(extra: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _spec(**extra)


def test_more_than_five_aliases_in_when_is_refused() -> None:
    names = [f"a{i}" for i in range(6)]
    context = {n: "cot_nc_net_oi@K" for n in names}
    with pytest.raises(ValueError, match="at most 5"):
        _spec(context=context, when=" and ".join(f"{n} > 0" for n in names))


# ---- gate vector ----


def test_known_answers_null_counts_and_spells(tmp_path: Path) -> None:
    _store(tmp_path)
    gate = _gate(tmp_path, "a > 0.5")
    expected = [*daily(date(2023, 1, 13), 14), *daily(date(2023, 2, 3), 14)]
    assert _on(gate) == expected
    assert _context_gate.spells(gate.by_ts) == 2
    assert gate.null_reasons == {"not-yet-known": 5, "stale": 12}  # Jan 1-5; Feb 17-28
    assert all(isinstance(on, bool) for on in gate.by_ts.values())
    assert gate.first_value == datetime(2023, 1, 6, tzinfo=UTC)
    assert gate.last_value == datetime(2023, 2, 16, tzinfo=UTC)
    assert _context_gate.short_history(gate)


def test_and_with_two_aliases(tmp_path: Path) -> None:
    _store(tmp_path)
    both = {"a": "cot_nc_net_oi@13874A", "b": "cot_nc_net_oi@13874A"}
    gate = _gate(tmp_path, "a > 0.5 and b < 0.8", both)
    assert _on(gate) == daily(date(2023, 1, 13), 14)
    assert _context_gate.spells(gate.by_ts) == 1


def test_keyed_by_timestamp_not_index(tmp_path: Path) -> None:
    _store(tmp_path)
    days = daily(date(2023, 1, 1), 59)
    full = _gate(tmp_path, "a > 0.5")
    late = _gate(tmp_path, "a > 0.5", frame=bars(days[17:]))
    assert all(isinstance(ts, datetime) and ts.tzinfo is not None for ts in late.by_ts)
    assert late.by_ts == {
        ts: v for ts, v in full.by_ts.items() if ts >= datetime(2023, 1, 18, tzinfo=UTC)
    }
    shuffled = bars(days).sample(fraction=1.0, shuffle=True, seed=3)
    assert _gate(tmp_path, "a > 0.5", frame=shuffled).by_ts == full.by_ts


def _naive_gate(rows: pl.DataFrame, days: list[date]) -> list[bool]:
    """A deliberately leaky join: the newest row by period, ignoring when it was known."""
    out = []
    for day in days:
        seen = rows.filter(pl.col("report_date") <= day).sort("report_date")
        out.append(seen.height > 0 and seen["noncomm_long"][-1] / 1000 > 0.5)
    return out


def test_poison_after_bar_k_changes_nothing_and_a_leaky_join_does(tmp_path: Path) -> None:
    clean, poisoned = tmp_path / "clean", tmp_path / "poison"
    _store(clean)
    rows = [
        dict(
            report_date=rel - timedelta(days=3),
            nl=-(10**15) if rel > date(2023, 1, 20) else round(v * 1000),
            known_from=_stamp(rel),
            basis="stamp",
        )
        for rel, v in RELEASES
    ]
    store_cot(poisoned, cot_rows(rows))
    k = datetime(2023, 1, 26, tzinfo=UTC)
    base, hit = _gate(clean, "a > 0.5"), _gate(poisoned, "a > 0.5")
    assert {t: v for t, v in hit.by_ts.items() if t <= k} == {
        t: v for t, v in base.by_ts.items() if t <= k
    }
    assert hit.by_ts != base.by_ts  # the poison is visible once it is known
    days = daily(date(2023, 1, 1), 40)
    leaky = _naive_gate(cot_rows(rows), days)
    honest = [base.by_ts[datetime.combine(d, time.min, tzinfo=UTC)] for d in days]
    assert leaky[:26] != honest[:26]  # the control: a leaky join moves bars before k


def test_held_back_boundary_and_fingerprint(tmp_path: Path) -> None:
    def build(home: Path, extra: list[dict[str, object]]) -> _context_gate.Gate:
        rows = [
            dict(
                report_date=date(2023, 12, 19),
                nl=800,
                known_from=_stamp(date(2023, 12, 22)),
                basis="stamp",
            )
        ]
        store_cot(home, cot_rows([*rows, *extra]))
        return _gate(home, "a > 0.5", frame=bars(daily(date(2023, 12, 20), 30)))

    base = build(tmp_path / "a", [])
    after = [
        dict(
            report_date=date(2023, 12, 26),
            nl=100,
            known_from=_stamp(date(2024, 1, 5)),
            basis="stamp",
        ),
        dict(
            report_date=date(2024, 1, 2), nl=100, known_from=_stamp(date(2024, 1, 5)), basis="stamp"
        ),
        dict(
            report_date=date(2024, 2, 6), nl=999, known_from=_stamp(date(2024, 2, 9)), basis="stamp"
        ),
    ]
    more = build(tmp_path / "b", after)
    assert max(base.by_ts) < datetime(2024, 1, 1, tzinfo=UTC)  # no bar on or after the reserve
    assert more.by_ts == base.by_ts and more.fingerprint == base.fingerprint
    assert more.attach.used_rows_sha256 == base.attach.used_rows_sha256
    with pytest.raises(DataError, match="reserved"):
        _gate(tmp_path / "a", "a > 0.5", cutoff=datetime(2024, 1, 1, tzinfo=UTC))


def test_fingerprint_moves_with_when_limits_and_rows(tmp_path: Path) -> None:
    _store(tmp_path)
    a, b = _gate(tmp_path, "a > 0.5"), _gate(tmp_path, "a > 0.6")
    assert len(a.fingerprint) == 64 and a.fingerprint != b.fingerprint
    assert a.fingerprint == _gate(tmp_path, "a > 0.5").fingerprint
    changed = _context_gate.context_fingerprint(a.attach, {"a": 99}, "a > 0.5")
    assert changed != a.fingerprint
    other = tmp_path / "other"
    _store(
        other,
        extra=[
            dict(
                report_date=date(2023, 1, 31),
                nl=5,
                known_from=_stamp(date(2023, 2, 1)),
                basis="stamp",
            )
        ],
    )
    assert _gate(other, "a > 0.5").fingerprint != a.fingerprint
