---
owner: command line application
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/**/*.py
  - apps/alpha-cli/src/alpha_cli/tool_cmds.py
  - tests/unit/test_toolbox_contract.py
  - tests/unit/test_toolbox_runner.py
verified: 02f63cfb9901fec5
---

# The toolbox

The toolbox helps the owner or assistant choose a question to ask of a recorded result. Each family declares its tools in Python.
One explicit tuple lists them. A named set fixes which questions to ask together.
The first set, `market-context`, describes market exposure, volatility regimes and changes in behaviour on one rule-test run.
See the [market family card](../../../research/tools/attribution-regimes-changepoints.md) for examples.

## Adding an entry

Give the tool a stable family-qualified id, a numeric version, a question, a kind, required inputs and typed parameters with defaults.
Declare each output's key, label, meaning and unit. A missing value needs a reason. The reading template may refer only to declared output values.
Caveats travel with the reading. Declare the cost class, seed use, time safety, look class and the reference test that checks the computation.
An entry that depends on time order names a poison test. A search declares how many evaluations each setting makes.
A builder receives resolved inputs, parameters and a random generator when needed. It calls an existing calculation and returns values,
reasons and any series, labels or figure. The runner owns persistence and the ledger. Stored gauntlet sections can later have a display-only entry.
Bump the version when a change affects numbers.

## What the record means

The target resolver identifies available inputs. The market tools share the full-sample replay used by the diagnostic pass.
A result is addressed by input hashes, parameters, seed and version. Identical requests read the stored output.
The record contains source provenance, the elapsed time, reserve date and the settings tried. The run folder stays immutable.
The ledger records an attempt before computation, followed by success or an error code. An unfinished attempt remains visible.
Every row carries the entry's kind and look class. History includes failures and unfavourable outcomes. A single tool request carries the ad-hoc label.

A non-default setting, or a seeded entry run with another seed, carries the non-default-params label.
Cite its output id and report how many settings were tried.
The results checker verifies this disclosure against the trial history, including later attempts.
Describe, test and search identify three different uses of evidence. The three market descriptions contribute zero trials for deflation.
Diagnostics, tests and controls leave grades and promotion decisions with the existing gauntlet and the owner.
The frozen gate list is empty. A future gate must point to a stored gauntlet result and accept no parameters.

The shared reserve begins on 2024-01-01. The market tools use the original run period. The reserved-period-seen label identifies runs
that have already used some reserved data. Historical regime fits and change points describe what happened across that sample.

## Delivery sequence

1. Move the three market tools to the shared runner. Preserve stored facts and their old citation names.
   Add the remaining return, risk, trade and stored diagnostics in later batches with reference tests.
2. Extend discovery to the Workstation, MCP and the generated catalogue. Render the same stored facts, caveats and series on each surface.
3. Decide which gates to freeze and when search evaluations count. Version the deflation rule before changing family counts.
4. Add the sweep and simulation tools and retire the bespoke commands they replace.
5. Add factor targets and bounded RD-Agent access. Only causal series with point-in-time tests qualify for feature export.
6. Expand one family and input adapter at a time. Require an independent reference for each new calculation.

## Owner decisions still open

- Choose a common reserve, an idea-specific held-back tail, or clipping for tool inputs. Decide who may reveal it.
- Choose when sweep evaluations enter deflation counts and which existing gauntlet results belong in the frozen gate list.
- Set the RD-Agent budget and decide whether a declared plan is required to cite evidence toward promotion.
- Assign ownership for catalogue generation and quant-tier review of new statistics.
