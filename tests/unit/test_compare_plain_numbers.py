"""`alpha results compare` prints short numbers with units; `--json` keeps the full floats."""

from __future__ import annotations

from typing import Any

from alpha_cli.spine.compare import render_compare


def _cell(
    value: float | int | None, diff: float | int | None, ratio: float | None
) -> dict[str, Any]:
    def fact(v: float | int | None) -> dict[str, Any]:
        return {"value": v, "reason": None if v is not None else "not stored"}

    return {"value": fact(value), "diff": fact(diff), "ratio": fact(ratio)}


def test_numbers_are_rounded_with_their_units() -> None:
    result = {
        "runs": [{"run_id": "a" * 16, "labels": []}, {"run_id": "b" * 16, "labels": []}],
        "metrics": {
            "oos_sharpe": [_cell(1.9689568250869662, 0.0, 1.0), _cell(1.2345678, -0.7343, 0.627)],
            "full_sample_total_return": [
                _cell(0.39114677, 0.0, 1.0),
                _cell(0.1234567, -0.2676901, 0.3156),
            ],
            "trades": [_cell(10, 0, 1.0), _cell(12, 2, 1.2)],
            "dsr": [_cell(0.7532240448959223, 0.0, 1.0), _cell(None, None, None)],
            "performance.recovery_factor.max_drawdown_amount": [
                _cell(5000.0, 0.0, 1.0),
                _cell(2500.5, -2499.5, 0.5),
            ],
        },
        "warnings": [],
    }
    text = render_compare(result)
    assert "1.97" in text and "1.9689568250869662" not in text
    assert "39.1%" in text and "-26.8 pts" in text
    assert "75.3%" in text and "0.7532240448959223" not in text
    assert "5,000.00" in text and "-2,499.50" in text
    assert "12" in text and "0.50x" in text and "1.00x" not in text
    assert "null (not stored)" in text
    assert not any(len(word) > 8 and "." in word and word[0].isdigit() for word in text.split())
