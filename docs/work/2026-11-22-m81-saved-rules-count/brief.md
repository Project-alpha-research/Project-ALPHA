# Brief: saved owner rules, parameter variants and the count sentence

Branch: `feat/m81-saved-rules-count`. Rules: `docs/work/_common-rules-2026-11-21.md`.

Why: an owner rule is typed in full in each spec file today, and the reading does not say how many times this rule SHAPE was tried.
Read `docs/reference/owner-rule-language.md`, `apps/alpha-cli/src/alpha_cli/spine/spec.py` (`load_spec`), `spine/owner_rule.py`,
`spine/diagnose.py`, `spine/reading.py`, and how the trial ledger counts (`spine/trial_reader.py`, `deflation.py`).

Build:
1. Saved-rule reference: `[rule] kind = "owner"` may give `saved = "<name>"` in place of an inline `[rule.spec]`. The rule is read from
   the saved rules store that `alpha rules` already writes (reuse its reader; do not add a second store). `load_spec` resolves it to the
   full RuleSpec BEFORE hashing, so the spec hash, test key and family are those of the inline rule, and the stored run keeps the full
   rule (a later edit of the saved rule never changes an old run or its recheck). A missing or invalid saved rule fails loud with the name.
2. The count sentence on every owner-rule reading (CLI text and the JSON reading): "This rule shape: K tests on this data. All rules on
   <asset>: M tests. The deflated Sharpe uses N = max(K, M)." K comes from the family `owner:<sha12(shape)>`; M is the same-asset count
   the code already uses. Do not change how N is computed; state what it is. Repeats of the same test key count once, as now.
3. `alpha test --diagnostics` variants for an owner rule: each window and each non-zero constant times 0.8 and times 1.2 (windows rounded
   to whole bars, at least 2; skip a variant equal to the original), at most 8 variants, each counted as a trial as the existing
   diagnostics variants are. The reading shows them as a small table of readings (no best-pick, no verdict).
4. Docs: `docs/reference/owner-rule-language.md`, `docs/reference/invariants/cli-rule-readings.md` (keep it at most 200 lines: move a
   section to a sibling page when needed, do not shorten text), `research/tools/rule-test.md`.

Tests first: hash equality saved versus inline; an old run rechecks to a match after the saved rule is edited; K and M on a temp ledger
with 3 thresholds of one shape and 2 other shapes; the variant list and its cap; golden pins unchanged. Done: pull request ready with
`ci-ok` green, and `report.md` in this folder.
