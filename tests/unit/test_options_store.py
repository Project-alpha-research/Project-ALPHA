"""Options store: point-in-time reads, immutability, held-back cut-off, fixture and size."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from alpha_core import DataError
from alpha_core.reserve import RESERVED_DAY
from alpha_data.options import (
    ChainSnapshot,
    OptionsAdapter,
    OptionsDataError,
    OptionsStore,
    SyntheticAdapter,
    VolSurface,
)

FETCHED = datetime(2023, 3, 10, tzinfo=UTC)


def put(store: OptionsStore, snapshot: ChainSnapshot) -> Path:
    return store.write(snapshot, fetched_at=FETCHED, adapter_version="fixture-1")


def days(adapter: SyntheticAdapter, n: int, start: date = date(2023, 3, 1)) -> list[ChainSnapshot]:
    return [adapter.chain("AAA", start + timedelta(days=i)) for i in range(n)]


def test_fixture_is_an_options_adapter_and_deterministic() -> None:
    a, b = SyntheticAdapter(seed=7), SyntheticAdapter(seed=7)
    assert isinstance(a, OptionsAdapter)
    assert a.list_underlyings() == ["AAA"]
    assert a.chain("AAA", date(2023, 3, 1)) == b.chain("AAA", date(2023, 3, 1))
    assert a.chain("AAA", date(2023, 3, 1)) != SyntheticAdapter(seed=8).chain(
        "AAA", date(2023, 3, 1)
    )
    contracts = a.contracts("AAA", date(2023, 3, 1), date(2023, 3, 2))
    assert contracts and all(c.underlying_id == "AAA" for c in contracts)


def test_fixture_carries_the_known_surface_as_provided_iv_with_valid_quotes() -> None:
    surface = VolSurface(base=0.2, skew=-0.1, term=0.02)
    snapshot = SyntheticAdapter(seed=1, surface=surface).chain("AAA", date(2023, 3, 1))
    assert len(snapshot.rows) > 20
    for r in snapshot.rows:
        assert r.quote is not None and 0 <= r.quote.bid <= r.quote.ask
        assert r.provided is not None and r.computed is None
        t = (r.contract.expiry - date(2023, 3, 1)).days / 365.0
        expected = surface.iv(float(r.contract.strike), snapshot.underlying_price, t)
        assert r.provided.iv == pytest.approx(expected, rel=1e-9, abs=1e-12)


def test_round_trip_and_sidecar_hash(tmp_path: Path) -> None:
    store = OptionsStore(tmp_path)
    snapshot = SyntheticAdapter(seed=3).chain("AAA", date(2023, 3, 1))
    path = put(store, snapshot)
    assert path == tmp_path / "options" / "fixture" / "AAA" / "2023" / "20230301T210000Z.parquet"
    meta = json.loads(path.with_suffix(".json").read_text())
    assert meta["rows"] == len(snapshot.rows) and len(meta["sha256"]) == 64
    got = store.chain_as_of("fixture", "AAA", datetime(2023, 3, 2, tzinfo=UTC))
    assert got is not None
    assert got.known_at == snapshot.known_at
    assert got.underlying_price == pytest.approx(snapshot.underlying_price, rel=1e-9, abs=1e-12)
    assert sorted(r.contract.key for r in got.rows) == sorted(r.contract.key for r in snapshot.rows)
    by_key = {r.contract.key: r for r in snapshot.rows}
    for r in got.rows:
        assert r.contract == by_key[r.contract.key].contract
        assert r.quote == by_key[r.contract.key].quote
        assert r.provided == by_key[r.contract.key].provided


def test_early_read_sees_nothing_and_later_reads_see_only_known_snapshots(tmp_path: Path) -> None:
    store = OptionsStore(tmp_path)
    for s in days(SyntheticAdapter(seed=2), 3):
        put(store, s)
    first = datetime(2023, 3, 1, 21, 0, tzinfo=UTC)
    assert store.chain_as_of("fixture", "AAA", first - timedelta(seconds=1)) is None
    assert store.snapshots_as_of("fixture", "AAA", first - timedelta(days=30)) == []
    at_first = store.snapshots_as_of("fixture", "AAA", first)
    assert [s.known_at for s in at_first] == [first]
    mid = store.chain_as_of("fixture", "AAA", datetime(2023, 3, 2, 22, 0, tzinfo=UTC))
    assert mid is not None and mid.known_at == datetime(2023, 3, 2, 21, 0, tzinfo=UTC)


def test_future_snapshot_is_never_opened(tmp_path: Path) -> None:
    """Future poison: a corrupted future file must not be read by an earlier-dated read."""
    store = OptionsStore(tmp_path)
    snaps = days(SyntheticAdapter(seed=2), 2)
    paths = [put(store, s) for s in snaps]
    paths[1].write_bytes(b"poison")
    got = store.chain_as_of("fixture", "AAA", datetime(2023, 3, 1, 22, 0, tzinfo=UTC))
    assert got is not None and got.known_at == snaps[0].known_at
    with pytest.raises(DataError):
        store.chain_as_of("fixture", "AAA", datetime(2023, 3, 2, 22, 0, tzinfo=UTC))


def test_later_known_at_hides_a_snapshot_until_it_is_known(tmp_path: Path) -> None:
    store = OptionsStore(tmp_path)
    s = SyntheticAdapter(seed=2).chain("AAA", date(2023, 3, 1))
    delayed = ChainSnapshot(
        provider=s.provider,
        underlying_id=s.underlying_id,
        snapshot_ts=s.snapshot_ts,
        known_at=s.snapshot_ts + timedelta(hours=20),
        underlying_price=s.underlying_price,
        rows=s.rows,
    )
    put(store, delayed)
    assert store.chain_as_of("fixture", "AAA", s.snapshot_ts + timedelta(hours=19)) is None
    assert store.chain_as_of("fixture", "AAA", s.snapshot_ts + timedelta(hours=20)) is not None


def test_chain_as_of_drops_contracts_not_yet_listed_or_already_expired(tmp_path: Path) -> None:
    store = OptionsStore(tmp_path)
    s = SyntheticAdapter(seed=2).chain("AAA", date(2023, 3, 1))
    expiring = {r.contract.expiry for r in s.rows}
    put(store, s)
    after_first_expiry = datetime.combine(
        min(expiring) + timedelta(days=1), datetime.min.time(), UTC
    )
    got = store.chain_as_of("fixture", "AAA", after_first_expiry)
    assert got is not None
    assert min(expiring) not in {r.contract.expiry for r in got.rows}
    assert len(got.rows) < len(s.rows)


def test_naive_cutoff_is_refused(tmp_path: Path) -> None:
    with pytest.raises(OptionsDataError) as exc:
        OptionsStore(tmp_path).chain_as_of("fixture", "AAA", datetime(2023, 3, 1))
    assert exc.value.field == "when"


def test_reads_at_or_after_the_held_back_day_are_refused(tmp_path: Path) -> None:
    store = OptionsStore(tmp_path)
    reserved = datetime.combine(RESERVED_DAY, datetime.min.time(), UTC)
    with pytest.raises(OptionsDataError) as exc:
        store.chain_as_of("fixture", "AAA", reserved)
    assert exc.value.field == "when"
    with pytest.raises(OptionsDataError):
        store.snapshots_as_of("fixture", "AAA", reserved + timedelta(days=400))
    assert store.chain_as_of("fixture", "AAA", reserved - timedelta(seconds=1)) is None


def test_snapshots_are_immutable_and_same_content_rewrite_is_a_no_op(tmp_path: Path) -> None:
    store = OptionsStore(tmp_path)
    s = SyntheticAdapter(seed=2).chain("AAA", date(2023, 3, 1))
    path = put(store, s)
    before = path.read_bytes()
    assert put(store, s) == path
    assert path.read_bytes() == before
    changed = SyntheticAdapter(seed=99).chain("AAA", date(2023, 3, 1))
    with pytest.raises(DataError, match="different content"):
        put(store, changed)
    assert path.read_bytes() == before


def test_unordered_snapshot_write_is_refused(tmp_path: Path) -> None:
    store = OptionsStore(tmp_path)
    a = SyntheticAdapter(seed=2)
    put(store, a.chain("AAA", date(2023, 3, 5)))
    with pytest.raises(OptionsDataError) as exc:
        put(store, a.chain("AAA", date(2023, 3, 4)))
    assert exc.value.field == "snapshot_ts"


def test_tampered_file_fails_its_hash_check(tmp_path: Path) -> None:
    store = OptionsStore(tmp_path)
    path = put(store, SyntheticAdapter(seed=2).chain("AAA", date(2023, 3, 1)))
    meta = json.loads(path.with_suffix(".json").read_text())
    meta["sha256"] = "0" * 64
    path.with_suffix(".json").write_text(json.dumps(meta))
    with pytest.raises(DataError, match="sha256"):
        store.chain_as_of("fixture", "AAA", datetime(2023, 3, 2, tzinfo=UTC))


def test_unsafe_names_are_refused(tmp_path: Path) -> None:
    with pytest.raises(OptionsDataError) as exc:
        OptionsStore(tmp_path).chain_as_of("../x", "AAA", datetime(2023, 3, 2, tzinfo=UTC))
    assert exc.value.field == "provider"


def test_write_requires_aware_utc_fetch_time(tmp_path: Path) -> None:
    s = SyntheticAdapter(seed=2).chain("AAA", date(2023, 3, 1))
    with pytest.raises(OptionsDataError) as exc:
        OptionsStore(tmp_path).write(s, fetched_at=datetime(2023, 3, 10), adapter_version="v")
    assert exc.value.field == "fetched_at"


def test_bytes_per_row_is_measured_against_the_design_estimate(tmp_path: Path) -> None:
    """Design estimate ~35 bytes/row. Small chains pay file overhead; wide ones do not."""
    small, wide = OptionsStore(tmp_path / "small"), OptionsStore(tmp_path / "wide")
    strikes = tuple(Decimal(40) + Decimal("0.25") * k for k in range(320))
    rows = {"small": 0, "wide": 0}
    for s in days(SyntheticAdapter(seed=5), 20):
        put(small, s)
        rows["small"] += len(s.rows)
    snapshot = SyntheticAdapter(seed=5, strikes=strikes).chain("AAA", date(2023, 3, 1))
    put(wide, snapshot)
    rows["wide"] = len(snapshot.rows)
    size = {k: sum(p.stat().st_size for p in (tmp_path / k).rglob("*.parquet")) for k in rows}
    per_row = {k: size[k] / rows[k] for k in rows}
    print(f"options bytes per row: {per_row} over {rows}")
    assert 0 < per_row["small"] < 400  # measured ~227: 54 rows per file
    assert 0 < per_row["wide"] < 60  # measured ~17; synthetic data is regular
