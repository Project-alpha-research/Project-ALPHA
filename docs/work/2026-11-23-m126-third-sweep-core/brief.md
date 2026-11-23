# Brief: what the third real-data sweep still found on the core path

Branch: `fix/m126-third-sweep-core`. Rules: `docs/work/2026-11-21-common-build-rules/brief.md` on main (read it first). The owner is a
retail swing trader, NOT a coder. A tester used the core path on real data a third time: 11 of 15 features pass, none fails. Fix
exactly these leftovers, each with a test first (synthetic fixtures), in the simplest way; plain short English in every message.
IMPORTANT: stored run files and stored reading words are compared by `alpha test --recheck`: change what is PRINTED or DRAWN, never
what an existing run kind stores. Do not edit protected paths (`workers/**`, `.claude/`, `.agents/`, `scripts/`, `tests/bias_guards/`,
`.github/`). Do not regenerate `STATUS.md`, `docs/roadmap/README.md` or `docs/reference/commands.md`. Net lines small: reuse the helper
that already does the job. Done = pull request ready (not draft) with a green `ci-ok`.

1. Symbol names. `alpha test --asset BTC` records the test under `BTC/USDT`, but `alpha ledger tries BTC` says "0 ideas on BTC": a
   false "nothing tried". Every command that takes a symbol must resolve it with the SAME rule `alpha test` uses (find that one
   resolver and call it), and print the resolved name when it differs from what was typed.
2. Labels. `alpha test` prints each label with its meaning; `alpha report`, `alpha results show`, the results list and
   `alpha results compare` print bare label names. Use the same label-with-meaning helper in all of them (a list view may show the
   short word and one legend line under the table).
3. Price chart of a rule test (`apps/alpha-cli/src/alpha_cli/figures/`): buy/sell triangles are too small on a long history and the
   price axis is linear. Make the markers readable at any span (size by the number of trades; when there are too many to read, draw
   them on a zoomed second panel of the last two years, or thin them and say so in the annotated note), and use a log price axis
   when the span is over five years. Keep the approved look: white, standard matplotlib, plain + annotated pair.
4. The tries paragraph shows three counts (ideas on this asset, across all assets, the adjustment count) with no reason, and a
   two-asset test shows different numbers per asset block. Keep the numbers; add half a sentence to each that says what it counts
   and why it differs ("N on this asset; M on all assets, which the luck adjustment uses plus the settings tried inside this test").
   One helper, used everywhere the paragraph is printed.
5. Bridge sentence. `alpha report` shows a luck-adjusted number near 1 beside "not clear of chance", and the toolbox shows
   "probabilistic Sharpe 99.9%" beside the same reading. Under the reading print ONE sentence that names what decided it (for
   example the random-price tests or the trade count), from the stored reading's own fields. Do not change any statistic.
6. No progress while `alpha test` runs (4 to 8 minutes on a loaded machine). Print the expected time before the run and one line
   about every 10 seconds (what stage, how far), the same way `alpha monte-carlo kronos` now does (reuse that helper). Nothing in
   the stored run changes.
7. Small wording, each one line:
   a. `results show`: gloss "inverted sharpe"; do not print "Flags raised: 3" beside "Checks: 2 flagged" without saying they differ.
   b. `results compare`: do not repeat the run id; hide the 0.00 / 1.00x self-comparison column.
   c. `trade_pnl` figure: say the account size the money axis assumes.
   d. Messages say `alpha ...`, never `uv run alpha ...`.
   e. `alpha follow start --test <id>` with a wrong kind of id says which id it wants and where to find it; `alpha tool run`
      accepts `--run <id>` as well as the positional id.
   f. `alpha idea new "text"` treats the bare text as the claim; the saved-card hint names `--idea-card`.
   g. The annotation box on pattern pictures must not cover the drawn lines (place it outside the plot area).
Report: per item the cause in one sentence, the change, the test; anything you could not fix and why.
