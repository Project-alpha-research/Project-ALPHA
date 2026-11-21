"""A longer, plain "how to read this chart" text for each figure.

The catalogue in ``alpha_research`` holds the one-line summary and is not edited here.
These texts say what the axes are, what to look for and what the chart cannot tell you.
They describe how to read a chart; they never say what to do about it.
"""

from __future__ import annotations

from alpha_core import DataError

_TEXTS: dict[str, str] = {
    "equity_underwater": (
        "The top panel shows the growth of one unit of capital after fees and slippage; the dashed "
        "line is the highest value reached so far. The bottom panel shows how far the strategy "
        "sits below that high at each date, in percent. Look at how deep the dips go and how long "
        "they last before a new high. A deep, long dip is what holding the strategy felt like. The "
        "chart cannot say whether the next dip will be shallower or deeper than these."
    ),
    "equity_vs_passive": (
        "The top panel plots the strategy and plain buy and hold from the same start, both rebased "
        "to 1. The bottom panel shows the strategy's growth divided by buy-and-hold growth, minus "
        "one: above zero the strategy is ahead, below zero it is behind. Look for long stretches "
        "below zero, even when the final value is ahead. The strategy pays fees and slippage and "
        "buy and hold pays none. The chart cannot say how much of the gap is skill and how much is "
        "luck."
    ),
    "rolling_risk": (
        "Each panel is a rolling window that slides one session at a time: the Sharpe ratio "
        "(return per unit of volatility), the annualised volatility and the window return. The "
        "x-axis is the date at the end of each window. Look for whether the Sharpe stays on one "
        "side of zero or swings, and whether volatility jumps in certain periods. Neighbouring "
        "windows share most of their data, so the swings are smoother than independent samples "
        "would be. The chart cannot show what happens between windows."
    ),
    "monthly_heatmap": (
        "Each row is a calendar year and each column a month; the colour is that month's return, "
        "green for gains and red for losses, and the last column is the full year. Look for months "
        "or years that stand out, and for whole columns of one colour. With many years the numbers "
        "are dropped and only every few years are labelled, so read the colour. One strong month "
        "can dominate a year. The chart cannot tell you whether a seasonal pattern is real or "
        "chance."
    ),
    "price_signal": (
        "The top panel is the traded price, with the strategy's own annotations drawn on it. "
        "Triangles mark individual fills when there are few of them. With many fills the shaded "
        "blocks mark the periods when a position was held. Panels below show the strategy's "
        "indicator series on their own scale. Look at whether entries and exits sit where the rule "
        "says they should. The chart is cut to the run's own dates. It cannot show orders that "
        "were never filled."
    ),
    "trade_pnl": (
        "The top panel has one bar per closed trade, in the order the trades were entered, green "
        "for a gain and red for a loss, in thousands or millions of account currency when the "
        "amounts are large. The bottom panel is the running total. Look at whether a few large "
        "bars drive the total and how long the running total stays below its peak. Bars are not "
        "the same size in risk terms. The chart cannot show how big each trade was relative to the "
        "account."
    ),
    "trade_runs_test": (
        "Each bar is one closed trade in entry order: up for a win, down for a loss. A run is an "
        "unbroken streak of the same sign. The runs z-score compares the number of streaks with "
        "what independent trades would give: below zero means wins and losses cluster, above zero "
        "means they alternate. Look at the streak pattern and the z value together. A small number "
        "of trades makes the z-score unstable. The chart cannot show why the trades are dependent."
    ),
    "holding_period": (
        "The x-axis is how many calendar days a trade was held and the y-axis is how many trades "
        "fall in each width of days. Dark bars are trades that made money and pale bars are trades "
        "that did not. The vertical line marks the median hold. Look at whether winners and losers "
        "are held for similar times. Calendar days include weekends. The chart cannot show how "
        "much each trade made or lost."
    ),
    "return_distribution": (
        "Each bar counts sessions whose daily return fell in a narrow band. The dashed curve is a "
        "normal distribution with the same mean and spread, and the vertical line is the mean. The "
        "x-axis covers the middle 99% of daily returns, so a few extreme days sit outside the "
        "frame. Look for a taller centre, heavier tails or lopsidedness compared with the curve. "
        "The mean comes from the stored daily returns, not from the bars. The chart cannot show "
        "the order in which the returns came."
    ),
    "qq_normal": (
        "Each dot pairs one sorted daily return with the value a normal distribution would give at "
        "the same rank. The dashed line is where the dots would fall if returns were normal. Dots "
        "that bend away at either end mean heavier tails than a normal curve. Look at the far left "
        "and far right, where single days sit. The chart is about shape only. It cannot show when "
        "the extreme days happened or whether they will repeat."
    ),
    "drawdown_episodes": (
        "The strip shows the equity curve, with the first and last dates printed on it. The shaded "
        "blocks are the deepest drawdowns, numbered from the worst, from the peak before the fall "
        "to the recovery. The table gives the depth, the peak, trough and recovery dates, and the "
        "session counts. Look at how long the recoveries take, not only the depth. An episode that "
        "has not recovered shows as open. The chart cannot say whether a deeper drawdown is still "
        "to come."
    ),
    "exposure_turnover": (
        "The top panel shows gross exposure (all positions added up, ignoring direction) and net "
        "exposure (longs minus shorts) as a multiple of the account's value. The bottom panel "
        "shows how much of the account was traded in each session. Look at how often the account "
        "is fully invested and how often it trades. A panel that says a series is unavailable was "
        "not recorded; it is not zero. The chart cannot show the individual positions."
    ),
    "null_distribution": (
        "Each panel is a histogram of an out-of-sample Sharpe ratio from many paths built to have "
        "no edge, for one kind of randomisation. The vertical line is the Sharpe the strategy "
        "actually produced, and its label gives the share of no-edge paths it beat. Look at how "
        "far into the right tail the line sits in each tier. A line in the middle means the result "
        "is typical of chance. The chart cannot show how many ideas were tried before this one."
    ),
    "fold_sharpe": (
        "Each bar is one walk-forward fold: the Sharpe ratio measured on data the model did not "
        "train on. The lower panel shows the same folds' out-of-sample return in percent. The line "
        "is the mean over folds with a defined Sharpe, and hollow dots mark flat folds with no "
        "trades. Look at how many folds are above zero and how far apart they are. Folds differ in "
        "length and market. The chart cannot show how the fold boundaries were chosen."
    ),
    "confidence_intervals": (
        "Each row is one metric. The dot is its estimate and the line is a 95% bootstrap interval, "
        "which re-samples the returns many times. The vertical line at zero is the no-effect mark. "
        "Look at which intervals cross zero and how wide each one is. A wide interval means the "
        "estimate would move a lot with a different sample. Bootstrapping assumes the sampled "
        "periods are alike. The chart cannot show changes in the market over time."
    ),
    "optim_surface": (
        "Each cell is one pair of swept parameter values, coloured by the out-of-sample Sharpe "
        "ratio, with the number printed in the cell. The colour is centred on the median of the "
        "sweep: red is below it and green is above it. An x marks a configuration that failed. "
        "Look for smooth regions rather than a single bright cell. A lone peak surrounded by weak "
        "cells is a sign of fit to noise. The chart cannot show the parameters that were not "
        "swept."
    ),
    "optim_trials": (
        "Each line is the out-of-sample equity of one swept configuration, rebased to 1 at the "
        "first step. The selected configuration is gold. The next three best are coloured and "
        "named in the legend with their final values, and the others stay grey. Look at how far "
        "the selected line sits above the crowd and whether the lines fan out or stay together. "
        "The selected one was picked because it did well, so it flatters itself. The chart cannot "
        "give an unbiased estimate of its future results."
    ),
    "portfolio_weights": (
        "Each line is one sleeve's weight, as a multiple of the account's net liquidation value, "
        "through time. The lower panel shows the combined gross exposure of all sleeves on the "
        "same scale. Look for periods when one sleeve carries most of the capital and for sudden "
        "changes in weights. Weights come from the allocation rule and from what each sleeve held. "
        "The chart cannot show how the sleeves' returns relate to each other."
    ),
    "portfolio_correlations": (
        "Each cell is the correlation between two sleeves' returns over the aligned out-of- sample "
        "window, from -1 (move opposite) through 0 (unrelated) to +1 (move together). The diagonal "
        "is each sleeve with itself and is always +1. Look for pairs near +1, since they add "
        "little diversification. Correlation is measured over one window and can change in a sell- "
        "off. The chart cannot show how much each sleeve earned."
    ),
    "propfirm_outcomes": (
        "Two histograms count simulated evaluation attempts that cleared the target. The left "
        "panel is the number of days they took to pass and the right panel is the payout in "
        "account currency. Only attempts that cleared are drawn, so read the answer line for how "
        "many did. Look at the spread of the days and of the payouts. The paths are resampled from "
        "past returns, so they assume the future looks like the past. The chart cannot show the "
        "rules of any particular firm."
    ),
    "monte_carlo_equity_fans": (
        "Each panel is one way of simulating future account paths. The darker band holds the "
        "middle half of the paths at each step, the paler band holds the middle 90%, the line is "
        "the median, and the gold line is the equity actually observed out of sample. Look at "
        "whether the observed line stays inside the bands. The simulations only reshuffle or re- "
        "draw past returns, so they cannot produce a regime that never happened. The chart cannot "
        "show probabilities of rare events."
    ),
    "monte_carlo_terminal_returns": (
        "Each panel is a histogram of the final account return, in percent, over many simulated "
        "paths from one simulation family. The left line marks break-even and the other line marks "
        "the median. Look at how much of the histogram lies below zero and how wide it is. "
        "Families make different assumptions, so differences between panels show how much the "
        "answer depends on the assumption. The chart cannot show the path taken to the end."
    ),
    "monte_carlo_drawdown_ruin": (
        "Each panel is a histogram of the largest peak-to-trough fall, in percent, over many "
        "simulated paths. The line at 50% is the ruin boundary used here; paths beyond it count as "
        "ruined and the ruin rate is printed in the panel. Look at how far the histogram reaches "
        "past the observed drawdown. The simulation reuses past returns, so it understates a crash "
        "unlike any in the sample. The chart cannot show how long a fall lasts."
    ),
    "monte_carlo_regimes": (
        "The top panel counts out-of-sample sessions by return, split into calm and volatile "
        "states by a rule fixed on training data; each state has a faint fill and a stepped "
        "outline. The bottom panel is the chance of moving from one state to the next, shaded from "
        "low to high, with the number in each cell. Look at how sticky each state is. Two states "
        "are a simplification. The chart cannot show what causes a state change."
    ),
    "kronos_monte_carlo_calibration": (
        "The upper panel compares the forecast model's error (CRPS, lower is better) with two "
        "simple baselines at each forecast origin. The lower panel compares the share of outcomes "
        "that fell inside the stated intervals with the share that was promised. Look at whether "
        "the model's line sits below the baselines and whether coverage tracks the ideal. A few "
        "origins can drive the average. The chart cannot show whether a forecast edge survives "
        "costs."
    ),
    "forecast_fan": (
        "The grey line is recent price history up to the forecast origin, marked by a vertical "
        "line. After it, the bands show where sampled forecast paths fell: the inner band holds "
        "the middle 50% and the outer band holds the middle 90%, around the median line. The "
        "x-axis is the date and the y-axis is the close. Look at how quickly the bands widen, "
        "since that is how fast the model's certainty fades. The bands are only as good as the "
        "model's calibration. The chart cannot show what actually happened afterwards."
    ),
    "forecast_skill": (
        "The upper panel plots forecast error (CRPS, lower is better) at each forecast origin for "
        "the model, a random walk and a bootstrap baseline. The lower panel shows the skill score "
        "against the random walk: zero means no improvement and negative means worse. Origins "
        "marked as before the cutoff may be in the model's training data. Look at how often the "
        "score is above zero and whether gains come from a few origins. Neighbouring origins "
        "overlap. The chart cannot show trading results."
    ),
    "forecast_calibration": (
        "The x-axis is the coverage the forecast promised for an interval and the y-axis is the "
        "share of outcomes that fell inside it. The diagonal is perfect calibration. Points below "
        "the diagonal mean the intervals were too narrow; points above mean they were too wide. "
        "Look at how far the points sit from the line at each level. The chart cannot show whether "
        "the forecast centre is accurate, only its spread."
    ),
    "state_conditioned_performance": (
        "Each position on the x-axis is one market state fixed in advance. The grey dot is the raw "
        "forecast's mean error (CRPS) out of sample, and the other dot is the calibrated "
        "forecast's; lower is better. A table below gives the state counts. Look for a state where "
        "the calibrated dot sits above the raw one. Some states have few observations, so their "
        "dots are noisy. The chart cannot show why a state is harder to forecast."
    ),
    "calibrated_reliability": (
        "The x-axis names the frozen evaluation split, validation or out-of-sample. The upper "
        "panel shows the forecast error (CRPS) of the raw and the calibrated forecast, and the "
        "lower panel shows their interval coverage against the nominal level. The calibration was "
        "fitted once and then frozen. Look at whether the improvement seen on validation data "
        "carries over to out-of-sample data. A gap between the two means it did not. The chart "
        "cannot show results after costs."
    ),
    "forecast_abstention": (
        "The upper panel plots the candidate signal at each out-of-sample forecast origin. The "
        "lower panel counts the origins that were blocked, by the rule that blocked them: "
        "uncertainty, edge size or market state. Look at how often the system holds back and which "
        "rule does most of the blocking. A block is a recorded outcome, not a missing value. The "
        "chart cannot show what the blocked origins would have done."
    ),
    "ensemble_disagreement": (
        "Each dot is one candidate, placed by the percentile rank the LightGBM model gives it "
        "(x-axis) and the rank the ridge model gives it (y-axis). The diagonal is perfect "
        "agreement. A summary below gives the average distance from it. Look at dots far from the "
        "diagonal: only one model likes those. Ranks only order candidates; they say nothing about "
        "the size of a return. The chart cannot show which model is right."
    ),
    "feature_stability": (
        "Each line is one input feature, and the x-axis is the training fold. The y-axis is how "
        "much LightGBM used that feature in that fold (its gain). Only the features with the "
        "highest mean gain are drawn. Look at whether the same features stay on top in every fold. "
        "A feature that matters in one fold and not the others suggests the model fits that fold's "
        "data. Gain shows use, not benefit. The chart cannot show whether a feature has a real "
        "link to returns."
    ),
    "ml_cost_sensitivity": (
        "The x-axis is a multiple of the declared transaction costs. The upper panel shows the "
        "total return of the same signals replayed at that cost and the lower panel shows their "
        "mean turnover. Look at the multiple where the return reaches zero. Costs here are scaled "
        "copies of the declared costs, not measured ones. The chart cannot show market impact at "
        "larger sizes."
    ),
    "research_discovery_trace": (
        "The upper panel plots the recorded series for the discovery sample against bar end time. "
        "Below it, a table lists the recorded sample size, the effective sample size and the "
        "identities of the stored evidence. Look at the gap between the sample and the effective "
        "sample, since overlapping data counts less than independent data. The identities show "
        "which stored records the figure came from. The chart cannot show tests that were not "
        "recorded."
    ),
    "mcpt_null_histogram": (
        "The histogram shows the best in-sample Sharpe the optimiser found on each of many "
        "permuted price series, where any pattern was destroyed. The vertical line is the best "
        "Sharpe found on the real series. Look at how far into the right tail the real value sits. "
        "The test is in-sample, so it measures how much a sweep can find by chance. The chart "
        "cannot show out-of-sample results."
    ),
}

_TRADABLE_NOTE = (
    " This version starts when the rule could first trade, after its warm-up bars, so the "
    "first sessions that cannot hold a position are left out."
)


def how_to_read(figure_id: str) -> str:
    """The long reading text for one figure; unknown ids fail loud."""
    base = figure_id.removeprefix("tradable_")
    text = _TEXTS.get(base)
    if text is None:
        raise DataError(f"no how-to-read text for figure {figure_id!r}")
    return text + _TRADABLE_NOTE if base != figure_id else text
