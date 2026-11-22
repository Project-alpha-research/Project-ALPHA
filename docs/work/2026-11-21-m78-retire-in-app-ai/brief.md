# Brief: retire the in-app AI

Branch: `chore/m78-retire-in-app-ai`.

Why: the owner works with an AI partner on the command line and through the MCP front door. The AI built into the Workstation is no longer wanted.
Delete Codex Bench, the investigations, Standalone Sandbox and "Investigate this run", with their commands, routes and tests.
Keep the toolbox (`alpha tool`), stored results and the assistant backend (to retire later).
Done: pull request ready with `ci-ok` green, and `report.md` in this folder.
