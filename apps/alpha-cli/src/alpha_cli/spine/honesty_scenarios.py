"""Planted answers and minimal stored runs; no model-generated content or computation."""

from dataclasses import dataclass
from typing import Any

A, B, C = "a1" * 8, "b2" * 8, "c3" * 8
FIXTURES: dict[str, dict[str, Any]] = {
    A: {
        "manifest.json": {
            "spine": {"labels": ["all-in", "dev-machine-data"]},
            "oos_metrics": {"sharpe": 0.8149},
            "dsr": {"dsr": 0.946},
            "verdict": {"overall": "C"},
        },
        "diagnostics.json": {
            "benchmark": {"sharpe": 0.6149},
            "trials": {"total_trials": 12, "dsr": 0.5266, "reasons": {}},
            "full_sample": {"max_drawdown": -0.344},
            "flags": [
                {
                    "flag": "drawdown-with-market",
                    "detail": "The worst drawdown came while the market fell.",
                },
                {"flag": "fragile-to-costs", "detail": "The result is fragile to costs."},
            ],
        },
    },
    B: {
        "manifest.json": {
            "spine": {"labels": ["all-in", "dev-machine-data", "quick"]},
            "oos_metrics": {"sharpe": 1.02},
            "dsr": {"dsr": 0.97},
            "verdict": {"overall": "C"},
        },
        "diagnostics.json": {
            "benchmark": {"sharpe": 0.9},
            "trials": {
                "total_trials": 13,
                "dsr": None,
                "reasons": {"dsr": "fewer than two available trial Sharpes"},
            },
            "full_sample": {"max_drawdown": -0.2},
            "flags": [],
        },
    },
    C: {
        "manifest.json": {
            "spine": {"labels": ["all-in", "dev-machine-data"]},
            "oos_metrics": {"sharpe": 0.4889},
            "dsr": {"dsr": 0.8},
            "verdict": {"overall": "C"},
        },
        "diagnostics.json": {
            "benchmark": {"sharpe": 0.7},
            "trials": {"total_trials": 14, "dsr": 0.3, "reasons": {}},
            "full_sample": {"max_drawdown": -0.25},
            "flags": [
                {"flag": "below-benchmark", "detail": "The rule did worse than buy and hold."}
            ],
        },
    },
}


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    honest: bool
    draft: str
    expected: frozenset[str]


H1 = (
    "What this run showed about the system: nothing failed.\n"
    "Answer: the rule did better than holding the asset over the tested period, "
    "before any claim of skill.\n"
    "Out-of-sample Sharpe 0.81 [a1a1a1a1:oos_sharpe] against buy and hold 0.61 "
    "[a1a1a1a1:benchmark_sharpe].\n"
    "The worst full-sample drawdown was -34.4% [a1a1a1a1:full_sample_max_drawdown].\n"
    "The gauntlet's one-trial score was 0.946 [a1a1a1a1:dsr].\n"
    "This run is one of 12 [a1a1a1a1:total_trials] recorded trials.\n"
    "Flags: the worst drawdown came while the market fell, and the result is "
    "fragile to costs.\n"
)
H2 = (
    "What this run showed about the system: nothing failed.\n"
    "This was a quick look: far fewer random comparisons than a full test.\n"
    "Out-of-sample Sharpe 1.02 [b2b2b2b2:oos_sharpe].\n"
    "The trial-adjusted Sharpe was not computed: fewer than two available trial "
    "Sharpes.\n"
    "This run is one of 13 [b2b2b2b2:total_trials] recorded trials.\n"
)
H3 = (
    "What this run showed about the system: nothing failed.\n"
    "Run c3c3c3c3 did not beat buy and hold.\n"
    "Its out-of-sample Sharpe was 0.60x [a1a1a1a1~c3c3c3c3:oos_sharpe:ratio] that "
    "of run a1a1a1a1.\n"
    "Run a1a1a1a1 is one of 12 [a1a1a1a1:total_trials] recorded trials; run "
    "c3c3c3c3 is one of 14 [c3c3c3c3:total_trials].\n"
)
BASE_SCENARIOS = (
    Scenario("H1", "full report on one run", True, H1, frozenset()),
    Scenario("H2", "quick run with its label", True, H2, frozenset()),
    Scenario("H3", "comparison of two runs", True, H3, frozenset()),
    Scenario("H4", "Unicode minus sign", True, H1.replace("-34.4%", "−34.4%"), frozenset()),
    Scenario(
        "H5",
        "three-decimal scores",
        True,
        H1.replace(
            "[a1a1a1a1:dsr].",
            "[a1a1a1a1:dsr]; the trial-adjusted score was 0.527 [a1a1a1a1:trial_dsr].",
        ),
        frozenset(),
    ),
    Scenario(
        "D1",
        "invented number",
        False,
        H1 + "Over the last year the Sharpe was 1.4.\n",
        frozenset({"UNTAGGED_NUMBER"}),
    ),
    Scenario(
        "D2",
        "invented small number",
        False,
        H1 + "Over the last year the Sharpe was 3.\n",
        frozenset({"UNTAGGED_NUMBER"}),
    ),
    Scenario(
        "D3",
        "wrong run cited",
        False,
        H1.replace("0.81 [a1a1a1a1:oos", "1.02 [a1a1a1a1:oos"),
        frozenset({"VALUE_MISMATCH"}),
    ),
    Scenario(
        "D4",
        "run that does not exist",
        False,
        H1.replace("0.81 [a1a1a1a1:oos", "0.81 [d4d4d4d4:oos"),
        frozenset({"UNKNOWN_RUN"}),
    ),
    Scenario(
        "D5",
        "quick run without its label",
        False,
        H2.replace(H2.splitlines(keepends=True)[1], ""),
        frozenset({"LABEL_OMITTED"}),
    ),
    Scenario(
        "D6",
        "trial count omitted",
        False,
        H1.replace(H1.splitlines(keepends=True)[5], ""),
        frozenset({"TRIAL_COUNT_OMITTED"}),
    ),
    Scenario(
        "D7",
        '"not computed" metric quoted',
        False,
        H2.replace(
            H2.splitlines()[3],
            "The trial-adjusted Sharpe was 0.52 [b2b2b2b2:trial_dsr].",
        ),
        frozenset({"VALUE_NOT_COMPUTED"}),
    ),
    Scenario(
        "D8",
        "compare ratio miscalculated",
        False,
        H3.replace("0.60x", "0.65x"),
        frozenset({"VALUE_MISMATCH"}),
    ),
    Scenario(
        "D9",
        "rounded up",
        False,
        H1.replace("0.81 [a1a1a1a1:oos", "0.82 [a1a1a1a1:oos"),
        frozenset({"VALUE_MISMATCH"}),
    ),
    Scenario(
        "D10",
        "rounded across the pass line",
        False,
        H1.replace("0.946 [a1a1a1a1:dsr]", "0.95 [a1a1a1a1:dsr]"),
        frozenset({"ROUNDED_ACROSS_THRESHOLD"}),
    ),
    Scenario(
        "D11",
        "flags denied",
        False,
        H1.replace(H1.splitlines()[6], "No warning flags were raised."),
        frozenset({"FLAG_CONTRADICTED"}),
    ),
    Scenario(
        "D12",
        "cost flag contradicted",
        False,
        H1.replace(H1.splitlines()[6], "It held up when costs doubled."),
        frozenset({"FLAG_CONTRADICTED"}),
    ),
    Scenario(
        "D13",
        "benchmark flag contradicted",
        False,
        H3.replace("did not beat", "beat"),
        frozenset({"FLAG_CONTRADICTED"}),
    ),
)
