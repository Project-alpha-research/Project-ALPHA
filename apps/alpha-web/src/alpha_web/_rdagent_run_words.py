"""Fixed words of the RD-Agent run reader: status sentences and projected field names."""

from __future__ import annotations

STATUS_SENTENCES = {
    "DIAGNOSTIC": (
        "Diagnostic only: cannot pass. Choosing the sign or clock after "
        "seeing this is a new trial and will be counted."
    ),
    "refused_missing_declaration": (
        "The proposal lacked a declared direction, primary clock or "
        "economic reason and was refused before coding."
    ),
    "proposal_failed_provider_timeout": (
        "The proposal provider timed out; no trial was invented and the "
        "loop moved to the next round."
    ),
    "proposal_failed_provider_error": (
        "The proposal provider failed; no trial was invented and the loop moved to the next round."
    ),
    "NOT_RUN": "This check was not run.",
    "OK": "This stage produced usable values.",
    "PASS": "This recorded stage passed; confirmation is still required.",
    "FAIL": "This recorded stage failed.",
    "FAILED": "The factor produced no usable values; the specific reason was not recorded.",
    "critic_rejected": "The code ran, but RD-Agent's critic did not accept it.",
    "cap_reached": "The call cap stopped the coder before it produced usable values.",
    "exception": "The code raised an exception and produced no usable values.",
    "bad_output": "The code was missing or did not produce the required numeric factor column.",
    "LOOKAHEAD": "The factor changed when future data was removed, so it cannot be trusted.",
    "UNSTABLE": "The factor changed on identical inputs, so its result is not reproducible.",
    "DEGENERATE": "There were too few usable observations or too little variation to judge it.",
    "ERROR": "Evaluation failed; this factor needs investigation.",
    "SCREEN_FAIL": "The factor did not pass the ranking test.",
    "SPREAD_FAIL": "The top third did not beat the bottom third before costs.",
    "REPLAY_FAIL": "The factor did not retain positive excess returns after costs.",
    "CANDIDATE": (
        "The declared primary clock and sign passed screening, spread, "
        "replay and deflation; this is a lead for one owner-approved "
        "reserved-data confirmation check, never evidence by itself."
    ),
    "DEFLATION_FAIL": (
        "A weekly or monthly clock passed screening, the spread check and replay, but not the"
        " multiple-testing (deflated Sharpe) test."
    ),
    "FAST_ONLY": "Only the daily clock passed; this is not a swing candidate.",
    "REPEAT": "This code was already evaluated and supplies no new evidence.",
    "IMPORTED": "This is a recorded historical trial, not a new evaluation by this run.",
    "refused_closed_family": (
        "The idea family was already closed, so the proposal was refused before coding."
    ),
    "no_admissible_idea": "Repeated closed-family proposals ended this round before coding.",
    "abandoned_at_cap": "The cap stopped an unfinished round; no trial was created for it.",
    "abandoned_after_error": "An error stopped an unfinished round; no trial was created for it.",
    "coding_failed_provider_timeout": (
        "The model provider did not reply in time after the allowed attempts, so this round"
        " stopped; no trial was invented and the next round ran."
    ),
    "coding_failed_provider_error": (
        "The model provider failed after the allowed attempts, so this round stopped; no trial"
        " was invented and the next round ran."
    ),
    "coding_failed_internal_error": (
        "An internal coding error ended this round; completed factors still went to ALPHA's "
        "judge. Two consecutive rounds with this error stop the run."
    ),
    "critic_unavailable_provider_timeout": (
        "The code critic timed out; execution and value checks supplied feedback, "
        "and later code critics in this round were skipped. ALPHA's judging rules stayed the same."
    ),
    "critic_unavailable_provider_error": (
        "The code critic's provider failed; execution and value checks supplied feedback, "
        "and later code critics in this round were skipped. ALPHA's judging rules stayed the same."
    ),
}
REFUSED_STATUSES = frozenset({"refused_closed_family", "no_admissible_idea"})
SCREENED = frozenset({"SPREAD_FAIL", "REPLAY_FAIL", "PASS"})
SPREAD_CHECKED = frozenset({"REPLAY_FAIL", "PASS"})
FUNNEL = (
    "proposed",
    "refused_closed_family",
    "stopped_by_provider",
    "code_ran",
    "passed_rank_screen",
    "passed_spread_check",
    "shortlisted",
    "passed_deflation",
)
SCREEN = (
    "status",
    "mean_ic",
    "n",
    "effective_n",
    "plain_p",
    "clustered_p",
    "two_sided_p",
    "dependence_rule",
    "newey_west.effective_n",
    "newey_west.lag",
    "newey_west.long_run_variance",
    "z",
    "p",
    "direction",
    "warnings",
    "mean_ci_95.lower",
    "mean_ci_95.upper",
)
SPREAD = (
    "status",
    "reason",
    "top_third_mean_return",
    "bottom_third_mean_return",
    "mean_spread",
    "annualized_spread",
    "t",
    "decision_days",
    "top_share_changed_per_rebalance",
    "estimated_annual_cost",
    "mean_ci_95.lower",
    "mean_ci_95.upper",
)
REPLAY = (
    "status",
    "counted_only",
    "net_annual_excess",
    "gross_annual_excess",
    "net_sharpe",
    "net.annualized_return",
    "net.compounded_return",
    "net.sharpe",
    "net.max_drawdown",
    "gross.annualized_return",
    "gross.compounded_return",
    "gross.sharpe",
    "gross.max_drawdown",
    "gap_policy.delisting_haircut",
    "gap_policy.assumption",
    "mean_turnover",
    "annual_cost",
    "turnover_per_rebalance",
    "rebalances",
    "haircuts_applied",
    "writeoff_instruments",
    "written_off_at_panel_end",
)
DEFLATION = (
    "sharpe",
    "psr",
    "dsr",
    "expected_max_sharpe",
    "n_trials",
    "threshold",
    "passed",
    "deflation_n",
    "deflation_variance",
    "deflation_variance_term",
    "deflation_rule",
)
UNIVERSE = (
    "instruments",
    "universe_text",
    "universe_includes_delisted",
    "instruments_ended_early",
    "missing_instrument_days",
    "longest_gap",
    "gap_policy.delisting_haircut",
    "gap_policy.assumption",
    "identity_jump_policy.min_gap_days",
    "identity_jump_policy.ratio",
)
CACHE = (
    "cache_hit_rate",
    "prompt_tokens",
    "cached_tokens",
    "reasoning_tokens",
    "completion_tokens",
    "distinct_providers",
    "unknown_provider_calls",
    "usage_unknown_attempts",
    "router_session_sent",
)


def status_sentence(status: str, failure_reason: str | None) -> str:
    key = failure_reason if status == "FAILED" and failure_reason else status
    if key not in STATUS_SENTENCES:
        raise ValueError("Unrecognised RD-Agent factor status or failure reason.")
    return STATUS_SENTENCES[key]
