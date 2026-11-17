"""Plain invalid-code diagnostics; no statistical decision or threshold lives here."""

from __future__ import annotations

from typing import Any


def failure_message(row: dict[str, Any]) -> str:
    status = row["status"]
    if status == "UNSTABLE":
        message = (
            "The code gives different answers on the same data; it is not reproducible "
            "(for example a regression with as many unknowns as observations)."
        )
    else:
        message = "The factor failed the look-ahead check."
    mismatch = row.get("lookahead", {}).get("first_mismatch")
    if mismatch:
        difference = (
            "not recorded"
            if "absolute_difference" not in mismatch
            else "not computable (a missing or non-finite value)"
            if mismatch["absolute_difference"] is None
            else mismatch["absolute_difference"]
        )
        message += (
            f" First mismatch: cut {mismatch.get('cut')}, row {mismatch.get('date')}, "
            f"instrument {mismatch.get('instrument')}, "
            f"absolute difference {difference}; "
            f"{mismatch.get('reason', 'values differ')}."
        )
    return message


def writeoff_summary(row: dict[str, Any], haircut: float) -> tuple[int, str]:
    replays = [t.get("replay", {}) for t in row["clocks"].values()]
    count = sum(r.get("haircuts_applied", 0) for r in replays)
    names = sorted({name for r in replays for name in r.get("writeoff_instruments", [])})
    coins = ", ".join(names[:5]) or ("coin names not recorded" if count else "none")
    if len(names) > 5:
        coins += f" and {len(names) - 5} more"
    return count, (
        f"{row['name']}: {count} held positions were written off after their coin stopped "
        f"trading, assuming a {haircut:.0%} loss of last value (not a measured recovery), "
        f"across the evaluated holding clocks; {coins}."
    )


def replay_output(replay: dict[str, Any]) -> dict[str, Any]:
    """Read old metrics with the precise output name, without rewriting stored files."""
    result = dict(replay)
    if "missing_coin_days" in result:
        result.setdefault("unrankable_instrument_rebalances", result.pop("missing_coin_days"))
    return result
