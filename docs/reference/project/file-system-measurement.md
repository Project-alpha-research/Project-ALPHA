---
owner: project layer
sources:
  - tests/unit/test_filesystem_contract.py
verified: 7c87af8b6fd472c6
---

# File-system measurement

The owner's test of the file system is that a reader who starts at `CLAUDE.md` can learn each part's purpose, reasons, plan and place
([owner, 2026-11-14](owner-decisions.md#2026-11-14-what-the-file-system-is-for)). This page records how that was measured, what the three rounds found and what
is still open.

## What was measured, and why

- Ten questions (under "How to re-run it"), each with a right answer checked against the code. The aim: find where a reader loses a fact.
- Three fresh readers per round. Each answers each question using only this repository, says which files it read, and says plainly what is not written down.
- A grader scores every answer against the key. **Strict full**: every required fact, with its named sub-details, and no wrong fact. **Core**: the central
  claim of each required fact is stated. **Wrong**: a fact the code or the key contradicts.
- Reading cost is bytes of documents opened (whole files, failed hops included, code excluded), against an ideal path the key names.

## Round 1 (before fixes, commit 34dca06f) and round 2 (after, commit 458503bb)

| Measure | Round 1 | Round 2 |
|---|---|---|
| Strict full answers, per reader (of 10) | 0, 0, 0 | 1, 1, 1 (all on the reserved period) |
| Core full answers, per reader (of 10) | 4, 6, 0 | 9, 8 (7 without one contaminated path), 6 |
| Core full by majority of three (of 10) | 4 | 7 (first recorded as 8) |
| Wrong facts | 2 (two readers each said Kronos runs offline) | 0 |
| Median reading per question, per reader | 40.6, 35.9, 32.0 KB | 37.3, 32.5, 32.3 KB |
| Median of the ideal paths | 23.7 KB | 19.5 KB |

Whole-file counting charges the 101 KB RD-Agent README in full; counted as actually read, round 2 medians are about 32.2, 31.5 and 31.7 KB.

By question, majority of three (strict / core):

| Q | Subject | Round 1 | Round 2 |
|---|---|---|---|
| 1 | RD-Agent thirds and ties | partial / partial | partial / partial |
| 2 | Add a toolbox test | partial / full | partial / full |
| 3 | Change the Setup Lab screen | partial / partial | partial / partial |
| 4 | Theme and UI design decisions | partial / full | partial / partial |
| 5 | Four Monte Carlo methods | partial / partial | partial / full |
| 6 | Kronos | wrong / wrong | partial / full |
| 7 | Stand-in for the owner | partial / partial | partial / full |
| 8 | The reserved period | partial / full | full / full |
| 9 | Data health | partial / full | partial / full |
| 10 | Build and land a change | partial / partial | partial / full |

## What fixed what

- The reserved-period page and its routing row: Q8 fell from about 98 KB and search fallbacks to 12 to 28 KB in two hops. The largest single gain.
- Correcting the Kronos "runs offline" line and amending ADR-0010: no wrong Kronos answers.
- `ci-ok` and the merge rule in the delivery pipeline page: every reader named both (none did in round 1).
- Naming the thirds module in the worker page and adding "Thirds and ties" with a do-not-change list: every reader found the code without searching.
- The toolbox "Adding an entry" recipe, the Setup Lab "To change this screen" section and the Monte Carlo summary: readers now state the names,
  the direct reads and the three resampling families.
- Status lines on the stand-in and data-health entries and the topic index: no reader was misled about data health; Q4 and Q7 took three hops.
- About two thirds of the fact-level gain came from changed pages, one third from the "answer fully" instruction or variance. Every flip of a majority
  rested on a changed page.

## What was still missing after round 2

The detail of what readers missed is kept outside the repository, so that it does not teach the test. The pull request that added this page answered
it with routing rows for the health card and the stand-in rule, a split of the RD-Agent README, a "From an idea to a merged change" section and
one-line summaries in the topic index. Left for the owner (protected file): `CLAUDE.md` says "One check: gate.py check" without naming `ci-ok`, and
says the web app calls the CLI as a subprocess with no exception for Setup Lab's stored-file reads.

## Round 3 (after those fixes, commit f0bfa564, 2026-11-19)

- Strict full answers per reader: 2, 3, 4 of 10. Core full: 8, 7, 9 of 10. Wrong facts: none. Median reading per question: 26.3, 19.5, 21.1 KB.
- Majority of three: strict 2 of 10, core 8 of 10. Round 2's majority core is corrected to 7 of 10.
- **Verdict:** fails the original bar (9 of 10 fully correct per reader). Fails the proposed bar narrowly: one critical fact was missed by one reader,
  and the majority core is 8 of 10. Reading cost is inside the original limit.
- The detail of what readers missed is kept outside the repository.

## Pass bar

- **Original bar:** at least 9 of 10 fully correct (strict), no wrong fact, median reading under 32 KB. **Round 2 fails it:** every reader had 1 of 10 strictly
  correct, and whole-file medians were 32.3 to 37.3 KB. Round 1 failed it too.
- **Proposed bar (proposed, owner has not decided).** Pass when all four hold, judged on the majority of three readers, with two different models:
  1. No wrong fact on any question.
  2. Every critical fact stated (those whose omission would cause a harmful act: do-not-change lists, never-allowed lists, "do not delete", "not built").
  3. Core correct on at least 9 of 10.
  4. At least 90% of required facts are present on the ideal path, within 1.5 times the ideal bytes. The grader checks the pages, not reader recall.
  Reading cost is measured as bytes actually read; any file over 30 KB on an ideal path is flagged as a defect.
- **Round 2 on the proposed bar:** part 1 passes. Part 2 almost passes (one reader missed the tie diagnostics, arguably not critical). Part 3 fails
  by two questions (7 of 10 by majority; Q1, Q3 and Q4 were partial). Part 4 failed on Q3 (the large frontend README) and Q1 (the whole RD-Agent README).
- Why a new bar: the strict count measures how much detail a reader recites as much as the file system; 26 of 29 non-full answers missed one or two
  sub-details, and reader variance was as large as the effect of the fixes.

## Honest limits

- Round-2 readers were told to answer more fully, so some gain is the instruction, not the pages.
- One path was contaminated: a reader guessed the keyword "stand-in" before seeing it in any file. It is graded for content, but left out of that majority.
- The harness auto-loads `CLAUDE.md` and some `CONTEXT.md` files for every reader in both rounds, so routing files were read for free. Three readers is
  small: 9 core answers for one and 6 for another on the same pages.

## How to re-run it
Use fresh readers with no memory of earlier rounds, and give them only the repository and these ten questions. Ask each to name every file it opens and to say
plainly when something is not written down. Keep the answer key outside the repository and do not show it to readers. Check each fact in the key against
the code at the commit you measure, grade strict and core as above, and add the round to this page.

1. Where is the code that splits RD-Agent names into a top and bottom third when values tie, what rule does it use, and what must not change?
2. Where do toolbox entries live, what must one declare, which honesty rules does the runner enforce, and what may never be written inside the toolbox?
3. Which files change for the Setup Lab screen, what follows a backend route change, and what rules apply to kept screenshots?
4. What has the owner decided about the Workstation's colour theme and about UI design work, and when?
5. Why are there four Monte Carlo methods, what does each answer, and may one be deleted?
6. What is Kronos here, is the real model running today, and may it be removed?
7. While RD-Agent is tested, what may a stand-in for the owner do, and what may it never do?
8. What is the reserved period, which commands respect it, what is decided and what is open?
9. Which command checks a dataset before a backtest, what four groups does it run, what does a clean report not say, and is its verdict attached to runs?
10. How is a change built and landed: who builds, how is a brief handed over, where do the brief and report end up, what is the required check,
    and how is a document marked re-read?
