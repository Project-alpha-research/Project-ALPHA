# Plan: remove the crypto extras (m94)

Deletion-only build. Owner decision of 2026-11-22: keep basic crypto data and the neurotrader888 material; remove the rest.

1. Prove each part is unreached (grep in apps, packages, workers, tests, scripts, docs).
2. Delete the commands, web routes, Workstation parts, tests and docs that only served the removed parts.
3. Keep anything a kept command, or a protected file, still reaches. List it in `report.md`.
4. Regenerate the command reference, OpenAPI file and generated types.
5. Leave the code-size baseline to the orchestrator. `report.md` lists the entries.
