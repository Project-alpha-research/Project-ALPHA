"""Rule-spec context gate after review: real alias sources, null logic under `not`, identity."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from alpha_core import DataError
from tests.unit._context_attach_support import bars, daily
from tests.unit.test_rule_context_gate import _gate, _on, _spec, _store

# ---- review fixes: real alias sources, null logic, identity ----


@pytest.mark.parametrize(
    "when",
    ["not within_bars(a > 0.5, 3)", "not for_bars(a > 0.5, 3)", "not (a > 0.5)", "not a > 2"],
)
def test_a_missing_value_never_opens_the_gate_under_not(tmp_path: Path, when: str) -> None:
    _store(tmp_path)
    gate = _gate(tmp_path, when)
    assert not [d for d in _on(gate) if d < date(2023, 1, 6)]  # not-yet-known bars stay shut
    assert gate.null_reasons.get("not-yet-known", 0) >= 5


def test_six_aliases_are_allowed() -> None:
    names = [f"a{i}" for i in range(6)]
    context = {n: "cot_nc_net_oi@K" for n in names}
    spec = _spec(context=context, when=" and ".join(f"{n} > 0" for n in names))
    assert spec.when is not None


def test_a_price_source_in_when_reads_the_price(tmp_path: Path) -> None:
    _store(tmp_path)
    days = daily(date(2023, 1, 1), 59)
    frame = bars(days).with_columns(close=pl.Series([float(i) for i in range(59)]))
    gate = _gate(tmp_path, "a > 0.5 and close > 20", frame=frame)
    assert _on(gate) == [d for d in _on(_gate(tmp_path, "a > 0.5")) if d > days[20]]


def test_alias_names_do_not_change_the_identity(tmp_path: Path) -> None:
    one = _spec(context={"es": "cot_nc_net_oi@13874A"}, when="es > 0.5")
    two = _spec(context={"pos": "cot_nc_net_oi@13874A"}, when="pos > 0.5")
    assert one.spec_sha256 == two.spec_sha256
    assert one.model_dump()["context"] == {"es": "cot_nc_net_oi@13874A"}  # stored as written
    _store(tmp_path)
    fa = _gate(tmp_path, "es > 0.5", {"es": "cot_nc_net_oi@13874A"})
    fb = _gate(tmp_path, "pos > 0.5", {"pos": "cot_nc_net_oi@13874A"})
    assert fa.fingerprint == fb.fingerprint and fa.by_ts == fb.by_ts
    swapped = _spec(context={"x": "cot_nc_net_oi@13874A", "y": "cot_nc_net_oi@OTHER"}, when="x > y")
    renamed = _spec(context={"y": "cot_nc_net_oi@13874A", "x": "cot_nc_net_oi@OTHER"}, when="y > x")
    flipped = _spec(context={"x": "cot_nc_net_oi@13874A", "y": "cot_nc_net_oi@OTHER"}, when="y > x")
    assert swapped.spec_sha256 == renamed.spec_sha256 != flipped.spec_sha256


def test_when_formatting_does_not_make_a_new_test() -> None:
    context = {"a": "cot_nc_net_oi@13874A"}
    texts = ["a > 0.5", "a>0.5", "(a > 0.50)", "  a  >  .5 "]
    assert len({_spec(context=context, when=t).spec_sha256 for t in texts}) == 1
    assert (
        _spec(context=context, when="a > 0.6").spec_sha256
        != _spec(context=context, when="a > 0.5").spec_sha256
    )


def test_ten_thresholds_are_ten_tests_in_one_family() -> None:
    specs = [_spec(context={"a": "cot_nc_net_oi@13874A"}, when=f"a > {t / 10}") for t in range(10)]
    assert len({s.spec_sha256 for s in specs}) == 10
    assert {s.rule.kind for s in specs} == {"tsmom"}  # the family is spine:<rule kind>


def test_every_declared_alias_must_be_read() -> None:
    with pytest.raises(ValueError, match="does not read"):
        _spec(context={"a": "cot_nc_net_oi@K", "b": "cot_nc_net_oi@K"}, when="a > 0")


def test_used_rows_hash_is_the_setup_lab_one(tmp_path: Path) -> None:
    from alpha_cli.spine import setup_context
    from alpha_data.context.attach import Binding

    _store(tmp_path)
    gate = _gate(tmp_path, "es > 0.5", {"es": "cot_nc_net_oi@13874A"})
    lab = setup_context.attach_bindings(
        bars(daily(date(2023, 1, 1), 59)),
        {"c0": Binding("cot_nc_net_oi", "13874A")},
        calendar=None,
        home=tmp_path,
        symbol=None,
    )
    assert gate.attach.used_rows_sha256 == lab.used_rows_sha256


def test_counts_add_up_to_the_bar_count(tmp_path: Path) -> None:
    _store(tmp_path)
    gate = _gate(tmp_path, "not within_bars(a > 0.5, 3)")
    total = gate.true_bars + gate.false_bars + sum(gate.null_reasons.values())
    assert total == len(gate.by_ts) == 59


def test_a_context_spec_never_reaches_the_ungated_engine() -> None:
    from alpha_cli.spine.run import assemble_run_spec

    spec = _spec(context={"a": "cot_nc_net_oi@13874A"}, when="a > 0.5")
    with pytest.raises(DataError, match="gated engine is not built yet"):
        assemble_run_spec(spec, "SPY", 252, 500)
