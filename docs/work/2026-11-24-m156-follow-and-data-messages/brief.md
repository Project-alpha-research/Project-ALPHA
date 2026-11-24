# m156: follow and data messages

Six messages misled the owner in an acceptance run. Only wording and one default change. Nothing computed, booked or stored changes.

1. Waiting state names the stored start time (`follow_store.waiting_text`).
2. `alpha follow today` count line: up to date, behind, waiting.
3. Bare `alpha follow update` updates all; `--all` with an id is refused.
4. `follow show` explains "Idea card: none linked". No command links a card to an existing follow, so the text says "optional".
5. `alpha data update` states the newest day asked for (yesterday, UTC).
6. `alpha lookalike --today` refuses `--timeframe` and `--max-distance`.
