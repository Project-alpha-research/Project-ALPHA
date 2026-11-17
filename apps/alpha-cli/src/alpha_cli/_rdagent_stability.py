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
    # A clock was replayed when it has replay metrics; an empty replay or a replay error is not.
    clocks = [
        clock
        for clock, trial in row["clocks"].items()
        if trial.get("replay") and "error" not in trial["replay"]
    ]
    replays = [row["clocks"][clock]["replay"] for clock in clocks]
    count = sum(r.get("haircuts_applied", 0) for r in replays)
    names = sorted({name for r in replays for name in r.get("writeoff_instruments", [])})
    coins = ", ".join(names[:5]) or ("coin names not recorded" if count else "none")
    if len(names) > 5:
        coins += f" and {len(names) - 5} more"
    if not clocks:
        return count, f"{row['name']}: no holding clock was replayed, so nothing was written off."
    replayed = " and ".join(filter(None, [", ".join(clocks[:-1]), clocks[-1]]))
    positions = "held position was" if count == 1 else "held positions were"
    return count, (
        f"{row['name']}: {count} {positions} written off after their coin stopped "
        f"trading, assuming a {haircut:.0%} loss of last value (not a measured recovery), "
        f"across the replayed {replayed} holding clock{'s' if len(clocks) > 1 else ''}; {coins}."
    )


def replay_output(replay: dict[str, Any]) -> dict[str, Any]:
    """Read old metrics with the precise output name, without rewriting stored files."""
    result = dict(replay)
    if "missing_coin_days" in result:
        result.setdefault("unrankable_instrument_rebalances", result.pop("missing_coin_days"))
    return result
