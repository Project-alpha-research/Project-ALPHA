---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/rdagent_journey*.py
  - apps/alpha-cli/src/alpha_cli/figures/rdagent_journey_figures.py
verified: 1794786e802a6d0a
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
reason in the journey. The future-data check names how many dates ALPHA checked. Step six
names the quick tests with recorded verdicts and shows the agent's feedback in its own words.
Step seven shows ideas tested so far, coins with a usable number, prior exposure and shortlist
facts. The journey is an exploratory reading of stored evidence.

In the Workstation, open Research → RD-Agent, select the run, then select an idea. The screen reads
the run's own `journey/` folder. A missing journey shows the local build command. The CLI can build
journeys for judged factors only. A loop event can have a name with no linked evaluation.
Step one shows up to four short sentences: idea type, description summary, expected direction,
and a chosen-after-seeing-the-data note. The full description stays in the agent's own words.
Code can be an excerpt. Long code lines wrap. The run summary shows only
recorded values. The final step carries the judge's exploratory label when recorded. The picker
gets the verdict from the run records.
