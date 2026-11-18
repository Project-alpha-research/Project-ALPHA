# Research loop screen

**Status:** Scoped
**Rough size:** L

## Problem / why

The run screen gives verdicts in tables. Readers need to trace a single verdict back to
the proposal, code and dated observations.

## What "done" looks like

The Research menu opens a single document with three tabs.

- **Learn** opens with a pipeline picture and follows one idea through seven steps. Show the
  proposal, calculation, future-data check, quick test, costed trading test, feedback and limits
  of the evidence. Pair a short paragraph with up to three headline numbers and an annotated
  chart where the run supplies one.
- **Live** shows the current round, remaining budget, requests and answers, and a timeline.
  One card per step links to the original exchange. The raw log opens on demand.
- **Findings** lists every idea tried and links to its journey. Show the full trial count,
  the strength of other ideas on the same panel, survivors and any earlier use of reserved data.

Use “RD-Agent (AI)” for proposals and feedback and “ALPHA rule” for the judge's decisions.
Keep original words and code one click away. Use the Workstation's figure card and fonts,
a light default with a dark option, precise labels and restrained colour. Hatch the reserved
period wherever dates are shown.

## Dependencies

The tabs depend on linked, stored evidence. Build them in this order.

1. Record the per-period evidence, code identity, proposal, feedback and exposure history.
2. Project the run through a read-only command.
3. Apply the light theme and data-linked arrow annotations.
4. Render evidence pictures on the server side. Stage A delivers the journey command,
   seven steps, chart sidecars and reasons for missing evidence. The remaining picture
   types belong with their screens.
5. Add read-only web routes for the generated journeys.
6. Build Findings, then Learn, then Live.
7. Check the finished screen against a recorded run in an unmocked browser.

## Sources

[Journey command](../../../research/tools/rdagent-journey.md) ·
[Production checklist](../production-scope.md)
