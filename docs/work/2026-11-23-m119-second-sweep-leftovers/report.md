# Report: second real-data sweep leftovers

Each item: cause, change, test. Tests were written first (the first run of each failed).

1. `--idea-card` with a spec file.
   - Cause: `load_spec` counted `idea_card` as a rule flag.
   - Change: `spine/spec.py` takes the flag beside a spec file; the flag wins over the file. `alpha test` prints "Linked to idea card <id>."
     Other flags with a spec now name the flag and the fix ("--fee-bps cannot be used with a spec file. Put it in the spec file...").
   - Test: `tests/unit/test_spec_idea_card_flag.py`.
2. Price chart markers and footer.
   - Cause: with more than 60 fills the chart drew shaded periods only. The footer printed "snapshot no snapshot" and "emitted no chart annotations".
   - Change: buy and sell triangles are always drawn from stored fills (small when many; `fills.parquet` is the fallback when there is no trace).
     The footer drops both phrases. The reading text no longer promises coloured strategy lines.
   - Test: `test_rule_period_figures.py` (2 new), `test_figure_pack.py` (old "many fills become shading" test changed).
3. `alpha report` and `alpha diagnose`.
   - Cause: both printed raw stored fields.
   - Change: new `spine/report_plain.py`. One sentence per check; no "old grade", field names or `None`. `--json` is unchanged. Stored files are unchanged.
     Existing tests that pinned the raw lines were changed. Stored diagnostic flag details are not printed: they hold the word "profit", which the owner-text guard forbids.
   - Test: `test_report_readings.py`.
4. Jargon.
   - Cause: stored words and raw labels were printed.
   - Change: new `spine/label_meaning.py` (same words as `LABEL_MEANING` in the Workstation file; `test_label_meaning.py` fails if they differ).
     `alpha test` prints each label with its meaning. The rule family prints as "This rule shape [id]". `results compare` prints 2 decimals, percent with one decimal, and "x" for ratios.
   - Test: `test_label_meaning.py`, `test_compare_plain_numbers.py`.
5. One count paragraph.
   - Change: `tries.reading_count_sentence` is the one paragraph. `alpha test` and `alpha report` print it. The stored "Ledger entry..., family counted as..." tail is cut at print time only.
     `alpha ledger query tries` returns the count per asset. No count is computed differently.
   - Test: `test_tries_headline.py`.
6. Chart overlays. One sentence is added to the summary and to the annotated picture when the picture's last day is after 2023-12-31. Test: `test_chart_pattern_picture.py`.
7. `alpha next`: "N not checked" plus a line that names the reports and `alpha data health <asset>`. Test: `test_next_cmd.py`.
8. Not fixed. The only way to set `verified:` is `scripts/fs.py verify`, which the brief forbids. `research/tools/chart-patterns.md` has the same placeholder.

## Decisions and things not done
- Commit trailer: I used the trailer lines the session gave me, not "Claude Fable 5.2", because I am not that model.
- `class-default-costs` has no meaning in the labels table (the Workstation table lacks it too); it prints by name. `results show` and `results compare` still list labels by name.
- `alpha test` table column now says "N labels, below" instead of the raw list.
- The full suite was too slow to run here; a targeted set of about 500 test files was run (see the pull request for CI).
