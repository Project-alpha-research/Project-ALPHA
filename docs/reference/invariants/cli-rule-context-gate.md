---
owner: command line runs and validation
sources:
  - apps/alpha-cli/src/alpha_cli/_context_gate.py
  - apps/alpha-cli/src/alpha_cli/_context_plan.py
  - apps/alpha-cli/src/alpha_cli/spine/setup_context.py
  - tests/unit/test_rule_context_gate.py
  - tests/unit/test_rule_context_plan.py
  - tests/unit/test_rule_context_identity.py
verified: 72c574d38aaf4ae5
---

# Command line rule context gate invariants

What must not break in the context gate of a rule spec (`alpha test --plan`). The reading of a rule test is in
[rule-test readings](cli-rule-readings.md).

## Context gate plan

- A spec may carry `context` (`{alias: "series@key"}`) and `when` (a condition over the aliases). `when` needs `context`, and
  `context` needs `when`, and `when` must read every alias. Aliases follow the Setup Lab rule (`check_aliases`): lowercase,
  never a price source or a function, so an alias cannot shadow a price. A bad alias, series, key or condition fails when the spec loads.
  A chart-pattern series (`spine/pattern_context.py`, for example `swing_low`) binds only with the key `SELF`: 1 on the bar the
  event became known, else 0, missing during warm-up.
- Canonical form (`_context_gate.canon`): each alias becomes `c0`, `c1`, ... in the sorted order of the bound `series@key`
  texts, and `when` is printed again from its parse tree. The spec hash takes this form; the stored `spec.json` keeps the text as
  written. So alias names and spacing make no new test; a new series, key, threshold or structure does. A spec without context
  hashes and dumps exactly as before (a test pins three hashes and the stored bytes, for specs that state the flat costs).
- `build_gate` attaches through `setup_context.attach_bindings` (the one call to `attach_context` for Setup Lab and the rule
  gate; daily bars; reserve cutoff) under the canonical names, then reads canonical `when` with `compile_expr` and the canonical
  names as context sources. The language is three-valued: a missing value never makes the condition true, also under `not`,
  `within_bars` and `for_bars`. A null gate is false on that bar and is counted by reason (`not-yet-known`, `stale`, a derived
  reason, `series-warm-up`, `expression-undefined`). True, false and null bars add up to the bar count. The gate is a map from
  bar timestamp to a boolean, never an index.
- `context_fp` is the sha256 of the used rows hashes (from `attach_context`, under the canonical names), the recipe, the
  staleness limits and canonical `when`. The data id is `idea_id(spec hash, sha256(source fingerprint + context_fp))`. Source
  table hashes are provenance only. Rows after the reserve or not known by the cutoff are not used rows, so adding them changes
  no test key. The family stays `spine:<rule kind>`: ten thresholds are ten tests in one family.
- `alpha test <spec> --plan [--json]` reads bars and context and prints, per asset: the context span (bars where every series has
  a value), gate true and false bars, the separate spells, null counts by reason, labels (`short-context-history` when the span is
  under 3 years), the test key and one sentence. It runs no engine and writes no ledger row, run folder or lock file; a test lists
  every path with size and mtime on each branch.
- `alpha test <spec>` without `--plan`, and `--recheck`, refuse a context spec: "the gated engine is not built yet; use --plan".
  `assemble_run_spec` also refuses a context spec, so no path runs the ungated rule. `--plan` on a spec without context is
  refused. The words are readings: no pass, fail or advice.
