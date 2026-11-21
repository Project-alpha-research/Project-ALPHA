# Report: the Workstation states an owner rule in words

## Result
The rule-test report and the Gates screen now show an owner rule as one plain sentence, with its family and each label's meaning.
Screenshots (synthetic run): `report-owner-rule.png`, `gates-owner-rule.png`.

## What changed
1. `apps/alpha-web/src/alpha_web/_owner_rule_words.py` (new, 112 lines): `owner_rule_sentence(spec)` builds the sentence from the stored JSON.
   It does not import the strategy package. Every operator and indicator of the language is covered (sma, ema, rsi, atr, bbands, macd,
   hawkes, cmma, runs_z, perm_entropy, vg_path, reversibility, sources with lag, constants). Anything else shows its stored text and
   "(not yet described)". `vsa` is refused by the language, so it takes this path.
2. `_rule_test.py` uses it for `rule.kind = "owner"` and adds `rule_family` (stored `spine.family`). The response model has one new
   optional field; OpenAPI file and `generated.ts` are regenerated.
3. Frontend: `ruleWords()` and the label `null-closes-for-high-low` in `ruleTestModel.ts` (the one label table); new `RuleWords.tsx`,
   shown at the top of `RuleTestReport.tsx` and in `Gates.tsx`. Old kinds are unchanged. A run with no stored rule reads
   "the rule was not stored with this run".
4. Docs: `web-run-detail.md` and `apps/alpha-web/README.md` code map.

## Decisions
- The language has no exit conditions today (long while all conditions hold). The sentence therefore reads "Sell at the next open when
  that stops being true", not a separate exit such as "RSI above 60" from the brief's example. It says only what the stored rule does.
- A stored non-empty `short_when` adds "The stored short side is not run by alpha test."
- Lags and day counts say "days", as the language reads daily bars.
- Commit trailer: the session's attribution instruction (Claude Sonnet 5.5) was used instead of the Fable line in the common rules.
- The report headline also quotes the sentence when the run has no idea text (existing behaviour of `summaryHeadline`); left as is.
- The Playwright spec ignores the three 404 resource loads that its own fixture causes (missing series, nulls, prices); any other
  console error or page error fails it.

## Fail-first
- `tests/unit/test_web_owner_rule_words.py`: first run failed at import (module absent); then 41 pass.
- `ruleTestModel.test.ts`: with `ruleTestModel.ts` stashed, 10 tests failed; with it, all pass.

## Checks
- `uv run lint-imports`: 13 kept. `gate.py check --base origin/main`: all passed.
- `test_code_size`, `test_research_reads_are_cut`, `test_follow_separation`, OpenAPI route tests: pass, unweakened.
- Frontend: `oxlint --deny-warnings` clean; vitest 868 pass; Playwright `owner-rule-words.spec.ts` (chromium-reference) passes.
- Not run locally: the other Playwright specs and the 1280/1920 viewports; CI runs them.

## Lines
Added about 330 (code 112 + 100 frontend + tests), removed 4. No baseline entry needs lowering. No protected path touched.
