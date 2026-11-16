# ADR-0052: Licence is never a criterion for an outside project

**Status:** Accepted
**Date:** 2026-11-16
**Deciders:** AI build agents, under the owner's decision of 2026-11-16: "this project is non
commercial and private so licensing and things DO NOT MATTER. never make a decision based off
that"
**Amends:** [ADR-0051](0051-glue-rules-for-outside-projects.md), rules 2 and 11;
[ADR-0011](0011-evidence-gated-external-integrations.md), evidence item 5

## Context

ADR-0051 rule 2 judged every candidate on five things, and licence was one of them. Rule 11
refused a project that "is not open source". ADR-0011 item 5 asked a proposal to record licence
and distribution implications, with copyleft parts isolated. Under those wording choices real
candidates were refused or delayed (scikit-survival, pypbo, Arize Phoenix, TimesFM 3.0 weights)
for a reason the owner says does not apply: ALPHA is private and non-commercial, and is public on
GitHub only because a free account requires it
([owner decisions](../reference/project/owner-decisions.md)).

## Decision

1. **Licence is not a criterion.** It is never a reason, a risk, a tie-breaker or a footnote when
   judging an outside library, model or data source.
2. **ADR-0051 rule 2 now has four things:** fit for a retail swing trader, upkeep, dependency
   weight, and conflict with ALPHA's pins. Fit, upkeep, weight and conflict stand as written.
3. **ADR-0051 rule 11** no longer refuses a project for not being open source. A project whose
   code cannot be read, pinned and tested is still refused, because that fails rule 4 on
   merit, not because of its licence.
4. **ADR-0011 item 5** (licence and distribution implications) is withdrawn; its other seven
   items stand.
5. **Records stay records.** The dependency and licence matrix, generated licence reports and the
   third-party notice files list what is installed. They are information, not a test an addition
   must pass.
6. Earlier register verdicts that rested on licence are to be judged again on merit; the first
   re-judging is in the register.

## Consequences

- Easier: a good library is no longer set aside for its licence alone.
- No code changes. ADR-0051 and ADR-0011 keep their text as the record of what was decided on
  their dates; this record changes how they are applied from 2026-11-16.
- Harder: nothing flags a licence automatically, by design. The matrix still lists them.
