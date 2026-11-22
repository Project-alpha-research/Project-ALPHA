"""The numbers in a chart's reading text match the marks it explains."""

from __future__ import annotations

from alpha_cli.figures.spec_facts import panel_plan
from alpha_research.figures import FigureSpec, Panel
from alpha_research.figures.spec import BarMark, RuleMark, ScatterMark, ValueLabel


def _fold_spec() -> FigureSpec:
    # Four folds: two flat ones drawn at 0 (no Sharpe) and two with a Sharpe of 1.0 and 0.5.
    mean = 0.75
    panel = Panel(
        panel_id="sharpe",
        y_label="Fold OOS Sharpe (sharpe)",
        y_unit="sharpe",
        marks=(
            BarMark(x=(0.0, 1.0, 2.0, 3.0), y=(0.0, 1.0, 0.0, 0.5), signed_colour=True),
            RuleMark(
                orientation="horizontal",
                position=mean,
                role="feature",
                annotate=ValueLabel(text=f"mean {mean:.2f}"),
            ),
            ScatterMark(x=(0.0, 2.0), y=(0.0, 0.0), hollow=True, role="neutral", label="Flat"),
        ),
    )
    return FigureSpec(
        figure_id="fold_sharpe",
        title="t",
        subtitle="s",
        x_label="Walk-forward fold",
        x_kind="numeric",
        panels=(panel,),
        question="q",
        plain_language_answer="a",
        uncertainty="u",
        caveat="c",
        caption="c",
    )


def test_a_bar_chart_with_a_marked_mean_states_that_mean_not_another() -> None:
    spec = _fold_spec()
    text = " ".join(panel_plan(spec, spec.panels[0]).sentences)
    # The bar mean with the flat folds counted as zero (0.375) contradicts the drawn line.
    assert "0.375" not in text
    assert "mean 0.75" in text


def test_a_split_histogram_counts_every_bar_in_its_reading() -> None:
    from alpha_research.figures.spec import HistogramMark

    edges = (0.0, 1.0, 2.0, 3.0)
    panel = Panel(
        panel_id="holding",
        y_label="Trades (count)",
        y_unit="count",
        marks=(
            HistogramMark(
                edges=edges,
                counts=(3.0, 0.0, 1.0),
                role="categorical",
                palette_index=0,
                label="Profitable",
            ),
            HistogramMark(
                edges=edges,
                counts=(4.0, 1.0, 0.0),
                role="categorical",
                palette_index=0,
                label="Unprofitable",
            ),
        ),
    )
    spec = FigureSpec(
        figure_id="holding_period",
        title="t",
        subtitle="s",
        x_label="Holding period (calendar days)",
        x_kind="numeric",
        panels=(panel,),
        question="q",
        plain_language_answer="a",
        uncertainty="u",
        caveat="c",
        caption="c",
    )
    text = " ".join(panel_plan(spec, panel).sentences)
    # Nine trades in all; the profitable ones alone are four.
    assert "hold 9 observations" in text
    assert "holds 7" in text
