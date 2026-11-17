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
    positions = "position" if count == 1 else "positions"
    coin_word = "coin" if len(names) == 1 else "coins"
    verb = "was" if count == 1 else "were"
    return count, (
        f"{row['name']}: {count} {positions} in {len(names)} {coin_word} "
        f"{verb} written off after their coin stopped "
        f"trading, assuming a {haircut:.0%} loss of last value (not a measured recovery), "
        f"across the replayed {replayed} holding clock{'s' if len(clocks) > 1 else ''}; {coins}."
    )


def replay_output(replay: dict[str, Any]) -> dict[str, Any]:
    """Read old metrics with the precise output name, without rewriting stored files."""
    result = dict(replay)
    if "missing_coin_days" in result:
        result.setdefault("unrankable_instrument_rebalances", result.pop("missing_coin_days"))
    return result


def deflation_note(replay: dict[str, Any]) -> str:
    result = replay.get("deflated_sharpe", {})
    value, threshold, count = (result.get(k) for k in ("dsr", "threshold", "n_trials"))
    if value is None or threshold is None:
        return "deflated Sharpe not recorded; multiple-testing test not passed"
    suffix = (
        ""
        if result.get("deflation_rule") == "family-looks-x2-floor-1"
        else "; old rule (fewer looks counted)"
    )
    return f"deflated Sharpe {value:.4g} against {threshold:.4g} over {count} trials{suffix}"


def deflation_passes(trial: dict[str, Any]) -> bool:
    result = trial.get("replay", {}).get("deflated_sharpe", {})
    value, threshold = result.get("dsr"), result.get("threshold")
    return value is not None and threshold is not None and bool(value >= threshold)


def recorded_status(row: dict[str, Any]) -> str:
    """Derive an old candidate's rejection from its recorded verdict, without mutation."""
    trial = row.get("clocks", {}).get(row.get("lead_clock", "daily"), row)
    result = trial.get("replay", {}).get("deflated_sharpe", {})
    if (
        row["status"] == "CANDIDATE"
        and result.get("dsr") is not None
        and result.get("threshold") is not None
        and not deflation_passes(trial)
    ):
        return "DEFLATION_FAIL"
    return str(row["status"])


def status_reason(row: dict[str, Any]) -> str:
    status = recorded_status(row)
    if status == "DEFLATION_FAIL":
        trial = row.get("clocks", {}).get(row.get("lead_clock", "daily"), row)
        message = (
            "passed the checks but not the multiple-testing test ("
            + deflation_note(trial.get("replay", {}))
            + ")"
        )
        return message + (
            "; derived from recorded CANDIDATE" if row["status"] == "CANDIDATE" else ""
        )
    if status in {"LOOKAHEAD", "UNSTABLE"}:
        return failure_message(row)
    return str(
        row.get("reason")
        or {
            "CANDIDATE": (
                "passed the swing screen, spread, replay and multiple-testing test; "
                "confirmation is still required"
            ),
            "FAST_ONLY": "passed the fast screen only; the slower clocks failed",
            "SCREEN_FAIL": "failed the rank screen",
            "SPREAD_FAIL": "stopped by the spread check",
            "REPLAY_FAIL": "failed to retain positive excess after costs",
            "DEGENERATE": "insufficient signal coverage or variation",
            "ERROR": "evaluation failed; inspect the recorded clock errors",
            "FAILED": ": ".join(
                str(row[k]) for k in ("failure_reason", "failure_detail") if row.get(k)
            )
            or "factor coding or execution failed",
            "REPEAT": "this code was already evaluated; no new evidence",
            "IMPORTED": "historical result imported without re-evaluation",
        }.get(status, "recorded " + status.lower())
    )


def plain_name(name: str) -> str:
    """Expand owner-facing stems in one table, retaining the existing general glossary."""
    from alpha_cli._rdagent_judge import plain_name as original

    stems = {"ltr": "long-term reversal", "mdd": "max drawdown", "vwap": "VWAP distance"}
    # Expand after the old formatter so its capitalization cannot lowercase VWAP.
    placeholders = {stem: f"expand{stem}token" for stem in stems}
    text = original("_".join(placeholders.get(token, token) for token in name.lower().split("_")))
    for stem, placeholder in placeholders.items():
        replacement = stems[stem]
        text = text.replace(placeholder.capitalize(), replacement[0].upper() + replacement[1:])
        text = text.replace(placeholder, replacement)
    return text
