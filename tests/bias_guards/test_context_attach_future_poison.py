"""Context values that were not yet published at a bar's decision instant cannot reach that bar."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import polars as pl
import pytest

from alpha_data.context.attach import AttachResult, Binding, attach_context
from alpha_data.timeframe import DAILY
from tests.unit._context_attach_support import (
    CODE,
    CUTOFF,
    bars,
    cot_rows,
    daily,
    finra_rows,
    store_cot,
    store_finra,
)

pytestmark = pytest.mark.bias_guard

POISON = 10**12
START = date(2022, 10, 4)  # a Tuesday in the stamped era: each report is public that Friday
DAYS = daily(date(2022, 10, 1), 150)
K = DAYS.index(date(2023, 1, 11))  # a Wednesday: Tuesday's report exists but is not yet public
BINDINGS = {
    "level": Binding("cot_nc_net_oi", CODE),
    "change": Binding("cot_nc_net_chg_4w", CODE),
    "short": Binding("sv_ratio", "AAA"),
}


def _decision(day: date) -> datetime:
    """A daily bar with no exchange calendar is known when its UTC day ends."""
    return datetime.combine(day, time.min, tzinfo=UTC) + timedelta(days=1)


def _cot(poison_after: datetime | None) -> pl.DataFrame:
    clean = cot_rows([dict(report_date=START + timedelta(weeks=n), nl=100 + n) for n in range(20)])
    if poison_after is None:
        return clean
    late = pl.col("known_from") > poison_after
    return clean.with_columns(
        pl.when(late).then(pl.lit(POISON)).otherwise(pl.col("noncomm_long")).alias("noncomm_long")
    ).cast(clean.schema)


def _finra(poison_after: datetime | None) -> pl.DataFrame:
    clean = finra_rows("AAA", [(day, 0.4) for day in DAYS if day.weekday() < 5])
    if poison_after is None:
        return clean
    late = pl.col("known_from") > poison_after
    return clean.with_columns(
        pl.when(late)
        .then(pl.lit(float(POISON)))
        .otherwise(pl.col("short_volume"))
        .alias("short_volume")
    ).cast(clean.schema)


def _attach(data_dir: Path, days: list[date], poison_after: datetime | None) -> AttachResult:
    store_cot(data_dir, _cot(poison_after))
    store_finra(data_dir, _finra(poison_after), "AAA")
    return attach_context(
        bars(days),
        timeframe=DAILY,
        calendar=None,
        bindings=BINDINGS,
        data_dir=data_dir,
        cutoff=CUTOFF,
        symbol="AAA",
    )


def test_poisoning_every_later_published_row_changes_no_earlier_bar(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    decision = _decision(DAYS[K])
    clean = _attach(tmp_path, DAYS[: K + 1], None)
    poisoned = _attach(tmp_path_factory.mktemp("poisoned"), DAYS[: K + 1], decision)
    assert clean.frame.equals(poisoned.frame)
    assert clean.used_rows_sha256 == poisoned.used_rows_sha256
    for alias in BINDINGS:
        assert clean.frame[f"ctx_{alias}"][-1] is not None  # the guard looks at real values


def test_poison_reaches_only_bars_decided_after_publication(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    decision = _decision(DAYS[K])
    clean = _attach(tmp_path, DAYS, None).frame
    poisoned = _attach(tmp_path_factory.mktemp("poisoned"), DAYS, decision).frame
    columns = [f"ctx_{alias}" for alias in BINDINGS]
    assert clean[: K + 1].select(columns).equals(poisoned[: K + 1].select(columns))
    assert not clean[K + 1 :].select(columns).equals(poisoned[K + 1 :].select(columns))


def test_a_join_on_the_period_would_leak(tmp_path: Path) -> None:
    """The leaky control: the same data joined on the period date does change bar K."""
    decision = _decision(DAYS[K])
    honest = _attach(tmp_path, DAYS[: K + 1], decision).frame["ctx_level"][-1]
    rows = _cot(decision).filter(pl.col("report_date") <= DAYS[K]).sort("report_date")
    leaky = rows["noncomm_long"][-1] / rows["open_interest"][-1]
    assert rows["known_from"][-1] > decision  # the newest period is not yet public at bar K
    assert leaky == pytest.approx(POISON / 1000, rel=1e-9, abs=1e-12)
    assert honest == pytest.approx(0.113, rel=1e-9, abs=1e-12)  # the report before it
    assert honest != leaky


def test_a_rule_timed_report_does_not_reach_the_bar_of_its_release_friday(tmp_path: Path) -> None:
    """Before stamps existed the release time is a rule; the real release can be after the close."""
    tuesday = date(2021, 6, 8)  # rule time: Friday 2021-06-11, 15:30 New York
    earlier = [dict(report_date=tuesday - timedelta(weeks=n), nl=50) for n in (2, 1)]
    store_cot(tmp_path, cot_rows([*earlier, dict(report_date=tuesday, nl=POISON)]))
    days = [date(2021, 6, 10), date(2021, 6, 11), date(2021, 6, 14)]
    out = (
        attach_context(
            bars(days),
            timeframe=DAILY,
            calendar="XNYS",
            bindings={"level": Binding("cot_nc_net_oi", CODE)},
            data_dir=tmp_path,
            cutoff=CUTOFF,
            symbol=None,
        )
        .frame["ctx_level"]
        .to_list()
    )
    assert out[0] == pytest.approx(0.05, rel=1e-9, abs=1e-12)
    assert out[1] == pytest.approx(0.05, rel=1e-9, abs=1e-12)  # Friday's bar: not yet usable
    assert out[2] == pytest.approx(POISON / 1000, rel=1e-9, abs=1e-12)  # Monday's bar: usable
