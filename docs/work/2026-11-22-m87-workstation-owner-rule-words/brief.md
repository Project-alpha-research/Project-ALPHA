# Brief: the Workstation states an owner rule in words

Branch: `feat/m87-workstation-owner-rule-words`. Rules: `docs/work/_common-rules-2026-11-21.md`.

Why: `alpha test` now runs owner rules (`[rule] kind = "owner"`, language in `docs/reference/owner-rule-language.md`). The Workstation
(backend `apps/alpha-web/src/alpha_web/_rule_test.py`; frontend rule-test report and Gates screens, `ruleTestModel`) was written for the
three fixed rule kinds. For an owner-rule run it shows a kind name at best. The owner is not a coder: they read the screen to learn what
was tested. Read `apps/alpha-web/CONTEXT.md` first. The screen is dark; charts stay white.

Build:
1. One function that turns the stored canonical RuleSpec of a run into one plain sentence, for example: "Buy at the next open when the
   14-day RSI is below 30 and the close is above the 200-day average. Sell at the next open when the 14-day RSI is above 60. Long or
   flat." It covers every operator and indicator the language has today; an operand it does not know is shown as its exact stored text
   with the words "not yet described", never dropped and never guessed.
2. Show the sentence at the top of the rule-test report page and on the Gates screen for that run, with the family
   (`owner:<12 characters>`) and the labels the run carries (for example `null-closes-for-high-low`), each label with a one-line plain
   meaning from one table.
3. The three old kinds keep their present wording. A run without a stored rule spec shows "the rule was not stored with this run".
4. The backend reads the stored run files only (bounded, read-only); it does not import the strategy package if the import rules forbid
   it (`uv run lint-imports`): then build the sentence from the stored JSON.
5. Tests: backend unit tests per operator and indicator; a frontend unit test of the model; one Playwright check on a synthetic
   owner-rule run fixture that the sentence and labels are visible with no console error. Regenerate the OpenAPI file and
   `generated.ts` if the response model changes.

Done: pull request ready with `ci-ok` green, `report.md` in this folder with two synthetic screenshots.
