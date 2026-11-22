# Brief: a plain path to a Qlib model, with no project or experiment

Branch: `feat/m111-ml-plain-path`. Rules: `docs/work/2026-11-21-common-build-rules/brief.md` on main (read it first). The owner is a retail swing trader, NOT a coder. On
2026-11-22 testers used the product on real data as he would and wrote down what failed; this brief fixes one group of those failures.
His words: "I should just be able to use the product and it work properly like any proper software." So: fix exactly what is listed,
in the simplest way; no new options beyond those named; no shims; plain short English in every message. Tests first, on synthetic
fixtures. Do not edit protected paths. Do not regenerate `STATUS.md`, `docs/roadmap/README.md` or `docs/reference/commands.md`. Add only
your own `report.md` in this task folder. Never delete anything that greps positive for `neurotrader`. Done = pull request ready with
a green `ci-ok`.

What failed: "There is no path from plain words to an ML model. `alpha ml capabilities` works (Qlib 0.9.7, gradient-boosting models);
every other step needs a governed project and experiment that no doc explains." Qlib is a core engine of the product and must be usable.
Another change in flight (pull request #392, branch `chore/m101-no-project-ids`) removes `--project-id` from ML commands: if it is not
on main when you start, merge that branch into yours first and build on it.

Build:
1. One command, `alpha ml run <spec.toml>`: the spec names the assets, the feature set (the default Alpha158-style recipe the worker
   already has), the label horizon in days, the model (default: the gradient-boosting model the worker offers) and the train / test
   split. It runs the existing worker path end to end (export input, train, replay through the engine with costs) and stores an
   ordinary run that `alpha results`, `alpha report`, the figures and the toolbox can read. `workers/**` is protected: call the worker
   exactly as the existing commands do; do not edit it.
2. Reads are cut at the held-back boundary like every other research read (`alpha_cli.spine.reserve`); the guard
   `tests/unit/test_research_reads_are_cut.py` passes unweakened. Training never sees the test window; state the split in the output.
3. The run counts as one try in the trial ledger (family `qlib`), and the reading states it.
4. A missing worker environment gives one plain message that says exactly what to run to set it up (the documented setup script).
5. An example spec `research/examples/ml-gbm-etfs.toml`, a tool card `research/tools/ml-model.md` (at most 40 lines), and tests with
   the repo's fake or recorded worker (no real training in tests).
Report: the exact worker calls reused; what the old project/experiment path did that this path does not.
