# Health plan: what is still owed

The project-health plan of 2026-11-13 ran in eight milestones: M0 land everything, M1 unblock,
M2 make status visible, M3 one file system, M4 lean checks, M5 sound parts, M6 agent-sized code,
M7 stay healthy. The plan itself was kept outside git. Most of M0 to M3 and M5 landed (see git
log and pull requests). This page is the one place that lists what was not done, checked on
2026-11-16 by the file-system audit. Delete a row when its work lands.

## Still owed

| Item | Milestone | State | Where it is tracked |
|---|---|---|---|
| List the stale remote branches with a keep-or-delete recommendation; owner signs off | M0 | Missing | [stage 12](production-scope-3.md#12-health-and-hygiene) |
| Changelog generated from pull-request titles, or dropped | M2 | Missing | [stage 12](production-scope-3.md#12-health-and-hygiene) |
| Slash commands cut to four, one per delivery stage (seven remain; agents and skills done) | M3 | Missing | here |
| Measure a fresh agent's navigation before and after: bytes read, right answer | M3 | Missing | [stage 12](production-scope-3.md#12-health-and-hygiene) |
| Retire the remaining pin tests (harness skills, repo-awareness drift, documentation truth) | M3 | Missing | here |
| The owner's project documents from the cloud workspace handed over and imported | M3 | Missing (owner) | [owner questions](production-scope-3.md#questions-from-the-file-system-audit) |
| Prune dead-code tests; collapse theme and figure-theme suites | M4 | Missing | here |
| De-duplicate the three full research round-trip tests | M4 | Missing | here |
| Timing tests use an injected clock or barrier instead of sleeps | M4 | Missing | here |
| Weekly mutation sweep passing | M4 | Missing | [backlog](backlog/weekly-mutation-sweep.md) |
| Nightly report of public functions no code calls, shown on the status page | M4 | Missing | [stage 12](production-scope-3.md#12-health-and-hygiene) |
| Default feature recipe moved to the upstream one after parity and owner yes | M5 | Unproven | [capabilities](capabilities.toml) (`alpha158-v3`) |
| Dead code removed per the triage sheet (QuantPad code, funding modules, old scaffolding) | M5 | Missing | [capability map](capabilities.toml) |
| Old local folders on the Dell and the Mac archived or deleted, with owner sign-off | M5 | Missing (owner) | [owner questions](production-scope-3.md#questions-from-the-file-system-audit) |
| Refactors: JSON and hash helpers, oversized functions, control-store split, CLI subpackages | M6 | Missing | [refactors](README.md) |
| Refactor of the web app's response models | M6 | Missing | [backlog](backlog/docs-freshness-gaps.md) |
| Sixty-day process freeze: process files change only by net removal | M7 | Missing | here |
| A short definition of done for one session | M7 | Missing | here |
| Mac milestone: real-data confirmation, data migration, credentials | M7 | Missing | [stage 11](production-scope-3.md#11-paper-and-live) |

## Superseded parts of the plan

- "No new features until M5 is done" and "at most three things in progress" were replaced on
  2026-11-15 by the clean spine: golden paths one at a time, at most two streams
  ([decision](../reference/project/owner-decisions-3.md#2026-11-15-build-the-thin-spine-clean-then-switch-over)).
- Merge commits were kept because documents once pinned commit ids; documents now pin a
  fingerprint of their sources, and merge commits stay the landing rule
  ([the build team](../reference/project/components/delivery-and-agent-tooling.md)).

## Machine clean-up still owed

Material was copied off the owner's Mac on 2026-11-16 into a private bundle outside git (the
repository is public, so evidence folders and credentials are never pushed). Open: verify the
bundle against its checksums once the copy finishes; a private document backup and a market-data
transfer package were never uploaded; the owner decides keep-or-drop for unfinished local work,
an orphaned earlier trading project, and two "public gate" plans that the later CI-only gate
([ADR-0039](../adr/0039-ci-is-the-merge-gate.md)) made obsolete.
