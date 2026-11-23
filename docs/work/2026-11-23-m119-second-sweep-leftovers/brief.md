# Brief: what the second real-data sweep still found on the core path

Branch: `fix/m119-second-sweep-leftovers`. Rules: `docs/work/2026-11-21-common-build-rules/brief.md` on main (read it first). The owner
is a retail swing trader, NOT a coder. A tester used the product on real data a second time: 10 of 15 features now pass; these are the
leftovers. Fix exactly these, each with a test first (synthetic fixtures), in the simplest way; plain short English in every message.
IMPORTANT: stored run files and the stored reading words are compared by `alpha test --recheck` and by the final check: do NOT change
any stored text or file content of a run; change only what is PRINTED or DRAWN. Do not edit protected paths. Do not regenerate
`STATUS.md`, `docs/roadmap/README.md` or `docs/reference/commands.md`. Done = pull request ready with a green `ci-ok`.

1. `alpha test <spec.toml> --idea-card <id>` fails with "a spec path and rule flags cannot be used together"; it works only when
   `idea_card = "<id>"` is inside the spec. `--idea-card` is a label, not a rule flag: accept it with a spec file (the flag wins over
   the file's value, and the output says which card was linked). Other rule flags with a spec keep the refusal, in plain words that
   name the flag and say what to do.
2. The price chart "promises buy and sell triangles but draws none" for a built-in rule ("the strategy emitted no chart
   annotations"). Draw the buy and sell markers from the run's stored fills for EVERY rule kind (owner rules already show them); the
   chart's reading text must only describe what is drawn. Every chart footer says "snapshot no snapshot": remove that phrase when a
   run has no snapshot (keep the run id and the source files).
3. `alpha report <run>` still prints "reading: not clear of chance (old grade: B)" and raw fields ("dsr:", "reason=None").
   `alpha diagnose` (and any diagnostics output) is raw JSON. Print a one-screen plain summary by default in both: what was checked,
   the number, one sentence each; no "old grade", no raw field names, no `None`. `--json` keeps the full machine output.
4. Jargon in the printed test result: "family counted as 13 tries", "spine:owner:45096ad611f7", labels "all-in" and
   "dev-machine-data". Print each label with its one-line plain meaning from the one labels table (the Workstation already does);
   print the rule family as "this rule shape" with the id in brackets. `alpha results compare` prints 16-digit floats: round to 2 to 4
   significant decimals with units.
5. The try count reads "Tries on SPY: 6 tries" beside "family counted as 13 tries" and "deflated Sharpe counts 12 tries ... plus 5
   nearby settings". Write ONE short paragraph, printed the same everywhere a count is shown, that states the three numbers and how
   they relate, for example: "You have tested 6 ideas on SPY. This rule shape has been tried 12 times across all assets, plus 5 nearby
   settings. The luck adjustment uses the larger count: 17." Use the real numbers; do not change how any of them is computed.
   `alpha ledger query` must accept the question "tries" (per asset).
6. `alpha chart overlays <SYMBOL> -p <pattern>`: the default window is the last two years, which lies entirely inside the held-back
   period (from 2024-01-01), with no note. Add one sentence to the summary and to the annotated picture: "This picture shows data from
   the held-back period. Looking at a chart is not a test; pattern tests in Setup Lab do not use this period."
7. `alpha next` says "16 unchecked" with no explanation: say what is unchecked (data health reports) and the one command that checks
   them.
8. The tool card `research/tools/reserved-confirmation.md` carries the placeholder `verified: 0000000000000000`: find how other
   cards carry this field and make the card valid by the project's own rule without running `scripts/fs.py verify` (if the only way
   is that script, leave it and say so).
Report: per item the cause in one sentence, the change, the test; anything you could not fix and why.
