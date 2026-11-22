# Brief: core-path defects found by real use (final check, recheck, try counts, propfirm, library, nightly example)

Branch: `fix/m115-core-path-defects`. Rules: `docs/work/2026-11-21-common-build-rules/brief.md` on main (read it first). The owner is a
retail swing trader, NOT a coder. On 2026-11-22 a tester used the product on real data as he would. These are the failures on the core
path. Fix exactly these, each with a failing test first (synthetic fixtures), in the simplest way; no new options beyond those named;
plain short English in every message. Do not edit protected paths (if a fix needs one, stop that item and say so in `report.md`).
Do not regenerate `STATUS.md`, `docs/roadmap/README.md` or `docs/reference/commands.md`. Done = pull request ready, green `ci-ok`.

1. HIGH. The final check (`alpha confirm run <run>`) fails on ANY test that has an idea card: "RECHECK_MISMATCH: 1 differences:
   manifest.spine.idea_card". Idea cards are meant to be written first, so the final check is blocked for normal use. The same cause
   makes `alpha test --recheck <run>` report "a different result" unless the idea-card link is typed again. The idea-card link is a
   label on a run, not part of the test: the recheck (and the frozen-test comparison of the final check) must take it from the stored
   run and must not compare it. Find every such "label, not test" field the comparison trips on and treat them the same way; keep
   every number and every test-defining field strictly compared.
2. HIGH. In plain (non-JSON) mode a failed `confirm run` exits 1 with NO message, after printing "Spending 1 slot now" although no slot
   was spent. Print the reason in plain words; print "Spending 1 slot now" only at the moment the receipt is written.
3. HIGH. A final check on a rule that did not trade in the held-back years spent a slot and then printed "Reading: fault. Fault: the
   out-of-sample Sharpe could not be computed. Fix this first. No reading." (numpy divide warnings on stderr). No trades in the period
   is a legitimate outcome, not a fault: report it as a reading ("the rule made no trades from 2024-01-01 to <end>; nothing can be
   concluded from this period"), with no warnings on stderr. Do the same wherever a zero-trade or zero-variance out-of-sample window
   reaches the reading code in an ordinary `alpha test`. And BEFORE a slot is spent, `confirm plan` and the text `confirm run` prints
   must state how often the rule traded per year in the earlier period and warn in one sentence when fewer than about 5 trades are to
   be expected in the held-back span (computed from the earlier period only; the held-back bars are not read for this).
4. HIGH. An exact repeat of an earlier test (labelled "repeat") still wrote new ledger rows and the family count for the asset went
   from 11 to 12. A repeat must add nothing to any count. Find which row it writes (the diagnostics variants are the likely source)
   and make the repeat path write none; prove with counts before and after on a temp ledger.
5. MEDIUM. Four different "how many tries" numbers are shown (ledger families "16 trials", ledger summary 38 rows, results "Total
   trials: 34", per-test "trials total"). Define each once in plain words and show ONE headline number everywhere a count is stated:
   the number of distinct tests on this asset that the deflated Sharpe uses, with its parts on request (`alpha ledger summary` gives
   the breakdown by kind and family, and its total equals the headline number). `alpha ledger query` must list the valid question
   names when it rejects one. Add `alpha ledger tries <ASSET>` that answers "how many tries on SPY" in one sentence.
6. MEDIUM. Propfirm: there is no tool card; the default horizon is the whole history (30 years), so the output reads "pass 39.6%, bust
   100.0%, over 7657 days"; the rules used are not printed; an unknown firm name silently falls back to "custom". Print the rule set
   used (profit target, daily loss, maximum loss, time limit) at the top; default to a realistic evaluation length (the firm preset's
   own limit, or 30 trading days when the preset has none) and say so; reject an unknown preset name with the list of valid names; add
   the tool card `research/tools/propfirm.md` (at most 40 lines) with how to read pass and bust rates and what they cannot tell.
7. MEDIUM. `alpha library search` needs the network and an e-mail option; there is no offline keyword search of the seed ideas the
   product ships. Add an offline search over the stored seed ideas and imported papers (title, summary, tags), used by default; the
   network search becomes `--online`.
8. LOW. The nightly example config points to `nightly-rule.toml` / `nightly-setup.toml` that are not in `research/examples`. Ship a
   complete working example set there and a test that loads the example config and resolves every file it names.
9. LOW. `alpha follow update` could not be proven without new bars: add a test that appends synthetic bars to a temp store and checks
   that the update books exactly those sessions once.
Report: per item, the cause in one sentence, the change, the test name; anything you could not fix and why.
