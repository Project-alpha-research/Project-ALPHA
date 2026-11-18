# Brief: RD-Agent ideas get a fixed set of toolbox checks after the verdict

**Build class:** hard

## Task

After ALPHA judges a round of RD-Agent factor ideas, run a fixed, predeclared set of two toolbox
checks on every idea whose trading replay is a shown result:
- `resampling.sharpe_interval`: how sure the Sharpe ratio is.
- `resampling.block_bootstrap_paths`: what range of final return and worst drop is plausible.

Store every attempt, append one plain sentence per check to the feedback the agent already
reads, and show the sentences in journey step 7. No verdict, threshold, cap, count, family
rule, worker file or model call changes. The checks describe; they never decide.

## Read first

| Read | Section | When |
|---|---|---|
| `apps/alpha-cli/CONTEXT.md` | whole | always |
| `docs/reference/project/components/toolbox.md` | Intended design; Never | always |
| `docs/reference/invariants/cli-investigation-tools.md` | Rules | always |
| `apps/alpha-cli/src/alpha_cli/toolbox/runner.py`, `inputs.py` (`Target`, `Inputs`), `store.py`, `sets.py` | whole | always |
| `apps/alpha-cli/src/alpha_cli/toolbox/families/resampling.py` | the two entries | always |
| `apps/alpha-cli/src/alpha_cli/rdagent_factor_eval.py` | `_write_series`, `_record_series`, `_evaluate_locked`, `evaluate` | always |
| `apps/alpha-cli/src/alpha_cli/_rdagent_judge.py` | `replay`, `_return_metrics` | always |
| `apps/alpha-cli/src/alpha_cli/_rdagent_ledger.py` | how rows of an unknown kind enter the screen family (why nothing new goes in the factor ledger) | always |
| `apps/alpha-cli/src/alpha_cli/rdagent_journey.py` (`_bound_files`, `_story`), `rdagent_journey_words.py` (`limits_step`) | — | journey item |
| `tests/unit/test_rdagent_factor_eval.py` | fixture, `evaluate` helper, planted-factor test | tests |
| `tests/unit/test_toolbox_resampling_checks.py` | fixture and parity pattern | tests |

## Decision already made

1. **Set.** Add `"rdagent-post-judge": ("resampling.sharpe_interval",
   "resampling.block_bootstrap_paths")` to `SETS` in `toolbox/sets.py`. Default settings and
   seed 0 only. No caller may pass settings.
2. **Eligibility.** A factor row in this evaluation qualifies if and only if all hold:
   `row["stage"] == "replay"`; `row["status"] != "REPEAT"`; the lead clock's replay
   (`row["clocks"][row["lead_clock"]]["replay"]`) has `"net"` and no `"counted_only"`;
   `row["evidence"]` exists. All other rows get no checks and no attempt rows. Eligibility
   comes from the verdict stage, never from a check result; the set is the same for every
   eligible idea, pass or fail.
3. **Adapter.** Create `FactorTarget(toolbox.inputs.Target)` (frozen dataclass) in the new
   module `apps/alpha-cli/src/alpha_cli/_rdagent_checks.py`:
   - Locate `rel = row["evidence"]["series_manifest"]`; it must be this iteration's
     `evaluations/iter-<n>/series/series.json`.
   - Verify hashes: sha256 of `series.json` equals `record["inputs"]["series_sha256"]` and
     `row["evidence"]["sha256"]`; the listed sha of `<code_sha256>.replay.parquet` equals the
     file's sha (mirror `rdagent_journey._bound_files`; do not import the journey module).
   - Read with polars (no pandas): filter `clock == row["lead_clock"]`, sort by `target_ts`.
     The series is the `excess_return` column: the after-cost daily return of the long-only
     top third minus the equal-weight basket. It is the same array the verdict and the
     deflated Sharpe use. Do not define any other series.
   - Require: all values finite, at least 2 rows, strictly increasing `target_ts`, last
     `exit_ts` before `RESERVED_DAY` (from `alpha_core.reserve`), else
     `SpineError("RESERVED_PERIOD", ...)`.
   - Self-check: `math.fsum(returns) / len(returns) * 365` equals
     `row["replay"]["net"]["annualized_return"]` (rel 1e-9, abs 1e-12; read the real key path
     from the code), else `SpineError("FACTOR_SERIES_CHANGED", ...)`.
   - Synthetic manifest: `{"spine": {"test_id": None, "labels": ["rdagent-factor",
     "excess-over-equal-weight-basket", "after-verdict"]}, "metadata": {"last_ts": <last
     exit_ts iso>, "periods_per_year": 365}}` so the base `ppy`, `labels`, `last_ts` and
     reserve labels work unchanged.
   - Overrides: `kinds` → `frozenset({"stored_equity"})`; `scored_returns()` → the array;
     `prepare(...)` refuses any need outside `kinds` and returns the input hashes
     (series manifest sha, replay sha, clock, code sha) for the cache key; `ledger_fields()`
     → `{"test_id": None, "name": row["name"], "symbol": "rdagent-factor-panel",
     "store": None}`.
   - Target id: `f"rdagent-iter{iteration}-{code_sha256[:16]}-{clock}"`.
4. **Runner seam.** `toolbox.runner.run` gains a keyword-only
   `source: inputs.Target | None = None`. When given, it replaces `inputs.resolve(home,
   target)`. Nothing else in the runner changes; existing callers are untouched.
5. **Storage.** For each tool in set order call `runner.run(home=<run>/"checks", tool_id,
   target=<target id>, set_name="rdagent-post-judge", source=FactorTarget(...))`. Attempt
   rows go to `<run>/checks/ledger/trials.jsonl`; outputs to
   `<run>/checks/diagnostics/<target>/`. Never write to the RD-Agent factor ledger or to the
   data directory's ledger.
6. **Placement.** In `evaluate()`, inside the existing lock, after `_evaluate_locked` returns
   and before the record is serialised, call `post_judge_checks(run, record)`. It returns
   `{"set": "rdagent-post-judge", "factors": [...]}` and a feedback suffix. Store the block as
   `record["checks"]`; append the suffix to `record["feedback_text"]`. `_evaluate_locked`,
   factor rows, the legacy result and the decision are unchanged.
7. **Failure isolation.** A failing tool is recorded by the runner as an error row; the record
   shows `{tool, error_code, message}` and the sentence "Check <id> could not run:
   <message>." Any other exception inside `post_judge_checks` sets `record["checks"] =
   {"set": ..., "note": "<Type>: <msg>"}` and is never raised. The evaluation always completes
   with the same verdict.
8. **Feedback text.** Per eligible factor append exactly: ` ALPHA checks after the verdict for
   <name> (fixed set rdagent-post-judge; they do not change the verdict), on the daily return
   above the equal-weight basket after costs: <reading 1> <reading 2>`. Each reading is the
   stored document's `reading`, unedited. If a reading contains the word "profit", report it
   (do not edit the tool).
9. **Journey.** `_story` passes this code's entry of `record.get("checks")` to `limits_step`.
   Step 7 ("How sure can we be?") appends one sentence per result: "ALPHA check after the
   verdict (does not change it): <reading>", or the "could not run" sentence. The output
   files are added to the step's sources. Steps, numbers shown (at most 3) and figures are
   unchanged. Records without `checks` read exactly as today (byte test).
10. **Determinism.** Evaluating the same request twice gives a byte-identical `result.json`;
    the second run hits the cache and adds no attempt rows.
11. **Counting.** Check rows add zero deflation trials and zero RD-Agent ledger rows. The
    factor ledger bytes are identical with checks on or off.
12. **Docs.** `toolbox.md` (≤ 200 lines): the set, the adapter's series in one sentence, the
    five honesty rules (declared before results; every attempt logged; zero trials added;
    cannot change a verdict; inputs end before the reserved date), and the next steps (agent
    names checks in its proposal before judging; discussion surface; more adapters) as not
    built. `rd-agent.md` (≤ 200 lines; it is near 191: replace, do not only add).
    `research/tools/rdagent-journey.md` is at its 40-line limit: replace a line. Capability
    record: add or update the entry for RD-Agent toolbox access (working for the fixed set;
    agent choice not built). When work lands, any page that listed it as queued or not built
    is updated in the same change. Nothing is replaced by this change: say so.

## Files

Edited:
- `apps/alpha-cli/src/alpha_cli/toolbox/runner.py`
- `apps/alpha-cli/src/alpha_cli/toolbox/sets.py`
- `apps/alpha-cli/src/alpha_cli/rdagent_factor_eval.py`
- `apps/alpha-cli/src/alpha_cli/rdagent_journey.py`
- `apps/alpha-cli/src/alpha_cli/rdagent_journey_words.py`
- `docs/reference/project/components/toolbox.md`
- `docs/reference/invariants/cli-investigation-tools.md`
- `docs/reference/project/components/rd-agent.md`
- `research/tools/rdagent-journey.md`
- `docs/roadmap/capabilities.toml`

New:
- `apps/alpha-cli/src/alpha_cli/_rdagent_checks.py`
- `tests/unit/test_rdagent_post_judge_checks.py`
- `tests/fixtures/rdagent_post_judge_checks.json`

This decision overrides the standing rule for: `tests/unit/test_rdagent_factor_eval.py`,
`tests/unit/test_rdagent_journey.py`, `tests/unit/test_toolbox_runner.py` (only to add
assertions or adapt fakes to the new keyword); `research/tools/resampling-checks.md`; generated
pages (`STATUS.md`, roadmap index, capability trace: regenerate with their scripts);
`docs/reference/project/ideas-and-considered.md` and `owner-decisions-5.md` for a dated status
line only; any living document `scripts/fs.py stale` reports because of your edits (verify with
a real text change or `--reason`). If a named file does not exist, use the real one. List each
in the report; do not stop to ask; where a rule is open choose the more cautious reading and
state it.

## Do not touch

- `workers/rdagent/**` (the judge hash must not change).
- `_rdagent_judge.py`, `_rdagent_stats.py`, `_rdagent_clocks.py`, `_rdagent_stability.py`,
  `_rdagent_ledger.py`, `_rdagent_membership.py`: verdict rules, thresholds, cutoffs,
  deflation and family closure stay as they are.
- `toolbox/contract.py`, `inputs.py`, `store.py`, `registry.py`, `reserve.py`,
  `toolbox/families/*`.
- `packages/**`, `apps/alpha-web/**`, `tests/bias_guards`, `tests/oracles`, golden files,
  `.semgrep/`, `.github/`, `.claude/`, `.agents/`, `scripts/`, `uv.lock`.
- The RD-Agent factor ledger format, the caps, the reserved date. No new command.
- No pandas in `toolbox/` or `_rdagent_checks.py`. No `nosemgrep`, `noqa`, `type: ignore`,
  `vars(`, `__doc__`, `inspect`, `.__dict__`. Functions ≤ 150 lines, files ≤ 1,500 lines
  (`rdagent_factor_eval.py` is near 1,310: keep logic in the new module); tests fully
  type-annotated; no test file named `*fixups*` or ending `_<N>.py`. Target ≤ ~600 changed
  lines including tests.

## Checks

Tests in `test_rdagent_post_judge_checks.py` compare floats with
`pytest.approx(rel=1e-9, abs=1e-12)` against the JSON fixture, never hashes, and cover:
parity (the Sharpe-interval point equals the stored replay net Sharpe; both tools' values
equal direct calls of the validated functions); eligibility (SCREEN_FAIL, counted-only
SPREAD_FAIL and REPEAT get none; REPLAY_FAIL and CANDIDATE do); verdict unchanged (factor
rows, factor ledger bytes and decision identical with `post_judge_checks` replaced by a
no-op); attempts (attempted and ok rows exist; a second `evaluate` adds none and gives the
same `result.json` bytes); failure isolation (a raising compute and a tampered Parquet give
an error entry, verdict unchanged); reserved (a target with an exit on or after the reserved
date is refused); journey (step 7 carries the sentences and sources, at most 3 numbers; a
record without checks is byte-identical to today).

- `uv run pytest -q tests/unit/test_rdagent_post_judge_checks.py tests/unit/test_rdagent_factor_eval.py tests/unit/test_rdagent_journey.py`
- `uv run pytest -q tests/unit -k "toolbox or rdagent or journey or capabilities or code_size or filesystem or docs_links or public_seams"`
- `uv run lint-imports`
- `uv run pytest -q tests/bias_guards`
- `uv run python scripts/fs.py stale`
- `uv run python scripts/gate.py check --base origin/main`

## Report

Answer first, plain words: what runs, on which ideas, where the files go. One example feedback
sentence and one example step-7 sentence from a test run. Proof that verdicts and counts are
unchanged (test names). Changed-line count per file. Every file outside the list with the
reason. Open readings chosen. What is unverified (no real loop was run).
