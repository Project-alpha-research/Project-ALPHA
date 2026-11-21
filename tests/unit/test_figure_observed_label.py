"""The observed-value note on a null histogram stays short and runs back into the plot."""

from __future__ import annotations

from alpha_cli.figures._builders import _observed_label


def test_label_is_short_and_reads_the_percentile_once() -> None:
    label = _observed_label(0.364, 0.5, 0.14, 0.64)
    assert label.text == "observed 0.364 · pct 50"
    assert "pct pct" not in label.text and "%" not in label.text


def test_right_half_label_runs_leftwards() -> None:
    assert _observed_label(0.60, 0.9, 0.14, 0.64).ha == "right"
    assert _observed_label(0.20, 0.1, 0.14, 0.64).ha == "left"


def test_label_without_percentile_is_just_the_value() -> None:
    assert _observed_label(0.1, None, 0.0, 1.0).text == "observed 0.100"
