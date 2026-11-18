---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/rdagent_journey*.py
  - apps/alpha-cli/src/alpha_cli/figures/rdagent_journey_figures.py
verified: 386bf25df3abfe4c
---

# Follow one RD-Agent idea

**Reach for it when** you want to see why an idea stopped and which observations the judge used.

```text
uv run alpha ledger journey --run-dir <run-dir>
uv run alpha ledger journey --run-dir <run-dir> --factor <name> --out <directory> --theme dark
```

The command prints the path to the index. Each entry identifies an iteration, a factor name
and its full code hash. Selecting a name builds every matching iteration. The index lists
all judged ideas. Open the selected folder's `journey.json` for the seven steps and source files.

Read the quick test on the holding period the proposer declared. The cumulative line rises
when rankings favour the proposed direction. Compare years in the lower panel. The spread
compares the top and bottom thirds before costs. The trading picture shows the selected
third before and after costs against the full basket; a costed bottom third is not stored.

Each available PNG has a JSON file containing its plotted numbers. A missing picture has a
reason in the journey. Check the coverage, prior exposure and shortlist facts in step seven
before interpreting the result. The journey is an exploratory reading of stored evidence.
