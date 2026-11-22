# Brief: Workstation rough edges, and the Machine learning screen back on the plain path

Branch: `fix/m116-workstation-rough-edges`. Rules: `docs/work/2026-11-21-common-build-rules/brief.md` on main (read it first). The owner is
a retail swing trader, NOT a coder. He likes the Workstation's look (terminal-style frame, Light theme): do NOT restyle it. He wants it
to work like proper software: no dead controls, no raw errors, plain words. Fix exactly these, tests first on synthetic fixtures.
Regenerate the OpenAPI file, `apps/alpha-web/frontend/src/api/generated.ts` and the authority matrix when routes change. Do not edit
protected paths. Do not regenerate `STATUS.md`, `docs/roadmap/README.md` or `docs/reference/commands.md`. Done = pull request ready with
a green `ci-ok` (a web change runs `quick`, `static` and `frontend`).

1. The market view on the Overview page shows "Loading stored bars…" for about 5 seconds because the server read is slow. Find where
   the time goes (reading whole bar files per tile?) and make it fast: read only the window shown, and cache per symbol and last-bar
   date in memory. Show the tiles' frames at once with a skeleton, never the word "Loading".
2. Older runs show "not stored" in the Reading column of the tests table. When a run has no stored reading, compute the reading words
   from its stored numbers with the same function the report uses; if that is impossible, show "older run: open the report" as a link.
3. Two labels on the report have no plain meaning ("reserved-period-held-back: No explanation was saved…"). Every label a run can
   carry must have a one-line plain meaning in the one labels table; add a test that fails when a label used anywhere in
   `apps/alpha-cli/src/alpha_cli/spine` has no meaning.
4. The chart header shows an internal tag ("legacy_unqualified"), and the chart legend lists "P paper journal event" although paper
   trading was removed. Remove both.
5. The Machine learning screen was removed because it needed the old "project" machinery. Bring it back on the plain path: a
   "Machine learning" window that lists stored ML runs (made by `alpha ml run <spec>`), and for one run shows: the split sentence,
   the assets, the model, costs, the reading, the equity and drawdown charts, and the fold table as a readable table. Read-only: it
   reads stored run files through the existing run routes (add one small typed route only if the list of ML runs needs it). It
   starts no training (the owner asks his AI for that); an empty state says in one sentence how to make the first ML run.
6. The home page headline of a report reads "returned 8.5% after costs, behind 1169.6% for simply holding the market". Keep the
   sentence; make sure both numbers are over the same period and say the period.
Report: per item the cause in one sentence, the change, the test.
