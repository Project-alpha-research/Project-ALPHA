"""Options store: research reads are cut at the held-back boundary; forward use reads on purpose."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest

from alpha_core import DataError
from alpha_core.reserve import RESERVED_DAY
from alpha_data.options import (
    ChainSnapshot,
    OptionsDataError,
    OptionsStore,
    Quote,
    SyntheticAdapter,
)
from alpha_data.options.schema import Greeks

FETCHED = datetime(2023, 3, 10, tzinfo=UTC)
BOUNDARY = datetime.combine(RESERVED_DAY, time.min, UTC)


def put(store: OptionsStore, snapshot: ChainSnapshot) -> None:
    store.write(snapshot, fetched_at=FETCHED, adapter_version="fixture-1")


def store_across_boundary(tmp_path: Path) -> tuple[OptionsStore, list[ChainSnapshot]]:
    store = OptionsStore(tmp_path)
    adapter = SyntheticAdapter(seed=4)
    snaps = [
        adapter.chain("AAA", RESERVED_DAY - timedelta(days=2)),
        adapter.chain("AAA", RESERVED_DAY - timedelta(days=1)),
        adapter.chain("AAA", RESERVED_DAY),
        adapter.chain("AAA", RESERVED_DAY + timedelta(days=3)),
    ]
    for s in snaps:
        put(store, s)
    return store, snaps


def test_research_read_is_cut_at_the_boundary_and_counts_what_it_hid(tmp_path: Path) -> None:
    store, snaps = store_across_boundary(tmp_path)
    far = BOUNDARY + timedelta(days=400)
    read = store.snapshots_as_of("fixture", "AAA", far)
    assert [s.known_at for s in read.snapshots] == [snaps[0].known_at, snaps[1].known_at]
    assert read.held_back == 2
    assert all(s.known_at < BOUNDARY for s in read.snapshots)
    chain = store.chain_as_of("fixture", "AAA", far)
    assert chain.chain is not None and chain.chain.known_at == snaps[1].known_at
    assert chain.held_back == 2
    # At the boundary instant nothing is hidden yet; later the first held-back snapshot counts.
    assert store.chain_as_of("fixture", "AAA", BOUNDARY).held_back == 0
    assert store.chain_as_of("fixture", "AAA", BOUNDARY + timedelta(hours=22)).held_back == 1
    early = store.chain_as_of("fixture", "AAA", BOUNDARY - timedelta(days=1, seconds=1))
    assert early.held_back == 0
    assert early.chain is not None and early.chain.known_at == snaps[0].known_at


def test_research_read_before_any_data_or_with_nothing_held_back(tmp_path: Path) -> None:
    store = OptionsStore(tmp_path)
    assert store.chain_as_of("fixture", "AAA", BOUNDARY + timedelta(days=9)).chain is None
    assert store.snapshots_as_of("fixture", "AAA", BOUNDARY).held_back == 0


def test_forward_read_sees_the_newest_data_with_no_cap(tmp_path: Path) -> None:
    store, snaps = store_across_boundary(tmp_path)
    got = store.forward_chain_as_of("fixture", "AAA", BOUNDARY + timedelta(days=400))
    assert got is not None and got.known_at == snaps[3].known_at
    mid = store.forward_chain_as_of("fixture", "AAA", snaps[2].known_at + timedelta(hours=1))
    assert mid is not None and mid.known_at == snaps[2].known_at


def test_naive_cutoff_is_refused_on_every_read(tmp_path: Path) -> None:
    store = OptionsStore(tmp_path)
    for read in (store.chain_as_of, store.snapshots_as_of, store.forward_chain_as_of):
        with pytest.raises(OptionsDataError) as exc:
            read("fixture", "AAA", datetime(2023, 3, 1))
        assert exc.value.field == "when"


def test_contract_expiring_after_the_boundary_is_identity_not_reserved_data(
    tmp_path: Path,
) -> None:
    """Listed before the boundary, expiring after it: known then, so a research read keeps it."""
    store = OptionsStore(tmp_path)
    day = RESERVED_DAY - timedelta(days=10)
    snap = SyntheticAdapter(seed=4).chain("AAA", day)
    put(store, snap)
    chain = store.chain_as_of("fixture", "AAA", BOUNDARY + timedelta(days=30)).chain
    assert chain is not None and chain.known_at == snap.known_at
    assert any(r.contract.expiry >= RESERVED_DAY for r in chain.rows)
    # Nothing in it is from the held-back period.
    for r in chain.rows:
        assert r.quote is not None and r.quote.quote_ts < BOUNDARY
        assert r.oi_as_of is not None and r.oi_as_of < RESERVED_DAY
    # Contracts that expired inside the held-back period are dropped by the capped cut-off day.
    assert all(r.contract.expiry >= chain.known_at.date() for r in chain.rows)


def test_research_chain_uses_the_capped_day_for_expiry_filtering(tmp_path: Path) -> None:
    store = OptionsStore(tmp_path)
    snap = SyntheticAdapter(seed=4).chain("AAA", RESERVED_DAY - timedelta(days=10))
    put(store, snap)
    late = store.chain_as_of("fixture", "AAA", BOUNDARY + timedelta(days=60)).chain
    capped = store.chain_as_of("fixture", "AAA", BOUNDARY - timedelta(seconds=1)).chain
    assert late is not None and capped is not None
    assert [r.contract.key for r in late.rows] == [r.contract.key for r in capped.rows]
    fwd = store.forward_chain_as_of("fixture", "AAA", BOUNDARY + timedelta(days=60))
    assert fwd is not None and len(fwd.rows) < len(capped.rows)


def test_read_at_t_never_returns_a_snapshot_known_after_t(tmp_path: Path) -> None:
    store = OptionsStore(tmp_path)
    adapter = SyntheticAdapter(seed=6)
    for i in range(6):
        s = adapter.chain("AAA", date(2023, 3, 1) + timedelta(days=i))
        put(store, replace(s, known_at=s.snapshot_ts + timedelta(hours=7 * i)))
    t = datetime(2023, 3, 1, 21, tzinfo=UTC)
    for step in range(0, 24 * 7, 5):
        when = t + timedelta(hours=step)
        read = store.snapshots_as_of("fixture", "AAA", when)
        assert all(s.known_at <= when for s in read.snapshots)
        chain = store.chain_as_of("fixture", "AAA", when).chain
        fwd = store.forward_chain_as_of("fixture", "AAA", when)
        assert all(c is None or c.known_at <= when for c in (chain, fwd))


def test_quote_stamped_after_known_at_is_refused_at_write(tmp_path: Path) -> None:
    store = OptionsStore(tmp_path)
    s = SyntheticAdapter(seed=2).chain("AAA", date(2023, 3, 1))
    first = s.rows[0]
    assert first.quote is not None
    late = replace(first.quote, quote_ts=s.known_at + timedelta(seconds=1))
    with pytest.raises(OptionsDataError) as exc:
        put(store, replace(s, rows=(replace(first, quote=late), *s.rows[1:])))
    assert exc.value.field == "quote_ts"
    assert not list(tmp_path.rglob("*.parquet"))


def test_labels_travel_with_the_row_through_a_read(tmp_path: Path) -> None:
    store = OptionsStore(tmp_path)
    s = SyntheticAdapter(seed=2).chain("AAA", date(2023, 3, 1))
    a, b, c = s.rows[:3]
    ts = s.snapshot_ts
    crossed = replace(a, quote=Quote(bid=2.0, ask=1.0, quote_ts=ts))
    flat = replace(b, quote=Quote(bid=1.0, ask=1.0, quote_ts=ts))
    sentinel = replace(c, provided=Greeks(source="provided", model="vendor", iv=0.0))
    put(store, replace(s, rows=(crossed, flat, sentinel, *s.rows[3:])))
    chain = store.chain_as_of("fixture", "AAA", datetime(2023, 3, 2, tzinfo=UTC)).chain
    assert chain is not None
    by_key = {r.contract.key: r for r in chain.rows}
    assert by_key[a.contract.key].labels == ("crossed",)
    assert by_key[b.contract.key].labels == ("zero_width",)
    assert by_key[c.contract.key].labels == ("iv_sentinel",)
    assert by_key[s.rows[3].contract.key].labels == ()


def test_negative_or_non_finite_values_stay_errors() -> None:
    with pytest.raises(OptionsDataError):
        Quote(bid=-1.0, ask=1.0, quote_ts=datetime(2023, 3, 1, tzinfo=UTC))
    with pytest.raises(OptionsDataError):
        Quote(bid=float("nan"), ask=1.0, quote_ts=datetime(2023, 3, 1, tzinfo=UTC))
    with pytest.raises(OptionsDataError):
        Greeks(source="provided", model="v", iv=-0.1)


def test_open_interest_date_after_known_at_is_refused() -> None:
    s = SyntheticAdapter(seed=2).chain("AAA", date(2023, 3, 1))
    bad = replace(s.rows[0], oi_as_of=s.known_at.date() + timedelta(days=1))
    with pytest.raises(OptionsDataError) as exc:
        replace(s, rows=(bad, *s.rows[1:]))
    assert exc.value.field == "oi_as_of"


def test_changed_content_is_refused_and_same_content_is_a_no_op(tmp_path: Path) -> None:
    store = OptionsStore(tmp_path)
    s = SyntheticAdapter(seed=2).chain("AAA", date(2023, 3, 1))
    put(store, s)
    put(store, s)
    tweaked = replace(s.rows[0], open_interest=(s.rows[0].open_interest or 0) + 1)
    with pytest.raises(DataError, match="different content"):
        put(store, replace(s, rows=(tweaked, *s.rows[1:])))
