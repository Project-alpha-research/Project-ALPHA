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
