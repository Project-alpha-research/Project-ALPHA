# Report: core-path defects (m115)

Brief: `docs/work/2026-11-22-m115-core-path-defects/brief.md` on `origin/work/m102-briefs`.
Rules: `docs/work/2026-11-21-common-build-rules/brief.md`.

## Decisions

- Commit trailer: the commits name the model that did the work, as the session asks; the common rules name another model.

## Items

### 1. Final check and recheck blocked by the idea-card link

- Cause: the spec excludes the card link from every hash, so a recheck run has no `spine.idea_card`, but the comparison compared it.
- Change: `spine.idea_card` joins the fields the recheck does not compare (`recheck_compare.SKIPPED`); the stored link stands.
  The other fields were checked: `name` and `idea` are in the spec hash (test-defining), `test_id`, `reserve`, health labels
  and fingerprints were already skipped; every number is still compared.
- Test: `tests/unit/test_recheck_idea_card.py` (fail first: `manifest.spine.idea_card` stored `9f4a…`, recomputed `<missing>`).

### 2. `confirm run` refusal without a reason; slot line printed too early

- Cause: the command printed "Spending 1 slot now" before the recheck ran, so a refusal read as a spent slot. The silent exit could
  not be reproduced here: in every refusal tried (recheck mismatch, real CLI in a subprocess) the reason was printed on stdout.
- Change: `confirm_run(..., on_spent=...)` calls back right after the slot receipt is written; the command prints the slot line
  there, on stdout. A refusal prints only the plan and the reason ("... No slot was used.").
- Tests: `tests/unit/test_confirm_run_words.py` (fail first: the slot line was in the refused output);
  `test_reserved_confirmation_surfaces.py` now asserts the slot line is absent when the run is refused.
