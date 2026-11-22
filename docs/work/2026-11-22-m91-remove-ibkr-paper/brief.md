# Brief: remove IBKR paper trading

Branch: `chore/m91-remove-ibkr-paper`.

Why: the owner approved removing IBKR paper trading. No route may reach a broker.
Delete the `alpha paper` group, the IBKR provider check, the Paper screen and its web API, with their tests.
Keep `alpha follow` and propfirm.
Done: pull request ready with `ci-ok` green, and `report.md` in this folder.
