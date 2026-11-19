---
owner: command line follow journal
sources:
  - apps/alpha-cli/src/alpha_cli/follow_journal.py
  - apps/alpha-cli/src/alpha_cli/follow_store.py
  - apps/alpha-cli/src/alpha_cli/follow_source.py
  - apps/alpha-cli/src/alpha_cli/follow_cmds.py
  - tests/unit/test_follow_separation.py
verified: 2fa0d4263cd714f8
---

# Command line follow invariants

Rules for `alpha follow`. A tested idea is followed on paper as new bars arrive. Options are in the
[command reference](../commands.md#alpha-follow). Build F1 only: the frozen record and the journal.
No signal is computed and no trade is simulated yet. Every screen of text says "paper".

## Separation (the integrity rule)
- `<data_dir>/forward/` is one-way. Research writes nothing there and reads nothing from there.
- Only the follow, today and nightly command modules (`follow_*.py`, `today_*.py`, `nightly_*.py`) may name the follow store
  modules or open a path under `forward/`. `tests/unit/test_follow_separation.py` reads source text under `apps/*/src`,
  `packages/*/src` and `workers/` and fails on a violation. It proves itself with a fixture string, not an edit of real modules.
- `follow start` writes no trial-ledger row, changes no research record and writes no file outside `forward/`.
- A follow is not a trial. Choosing what to follow is still a selection; later builds count it where the owner sees it.
- Forward use reads the newest bars on purpose, as `alpha scan check` does. F1 reads one bar per asset, only to record its hash.
  Research commands keep their cut-off. This module adds no reserved date and bypasses no cut-off helper.
- The start entry carries bar hashes and no bar dates, so no timestamp from before the start is written.

## The follow record
- `forward/<follow_id>/follow.toml` is written once and never edited. `follow_id` is the first 12 hex characters of a hash of the rest.
- Fields: `kind` (`rule_test` or `setup_find`), `source_id` (the run id or find id), `spec_sha256`, `card_id` (the idea card, if any),
  `assets`, `paper_account_percent`, `started_at` (aware UTC), `version`, `supersedes`.
- A factor is refused: "Following a factor is not built yet."
- Size is a percent of a paper account. The default is 10. It must be above 0 and at most 100.
- An edited record no longer matches its id. Every read checks this and fails loud.

## Versions
- Changing a followed idea is never an edit. The idea is the linked idea card. Without a card, each test is its own idea.
- `follow start` on the same spec, assets and size of an active follow returns that follow. Nothing is written.
- A different spec, asset set or size for the same card makes a new follow: `version` plus one and `supersedes` set.
  The old follow gets a `stop` entry. Its folder is kept. The text says the forward clock restarts.
- The new follow is written first. A crash can leave two active follows. It cannot leave none.

## The journal
- `forward/<follow_id>/journal.jsonl` is append-only. One line is one entry.
- Entry fields: `seq` (from 1), `session_date`, `written_at` (aware UTC, from an injected clock), `kind`
  (`start`, `bar`, `missed`, `late`, `stop`), `bar_hashes` (latest bar hash per asset), `payload` (free object),
  `prev_hash`, `entry_hash`. The hash is SHA-256 of the canonical entry without `entry_hash`. The first `prev_hash` is 64 zeros.
- F1 commands write only `start` and `stop`. The writer already supports the other kinds.
- Append takes an exclusive lock, checks the whole chain, writes one line and syncs it.
- The clock is passed in. Nothing in the journal sleeps or reads the wall clock.

## What the writer refuses
Each refusal is a typed error with a stable code and plain words.

| Code | Refused |
|---|---|
| `FOLLOW_SESSION_NOT_AFTER` | a session date not after the last one: no inserts, no back-fill |
| `FOLLOW_CLOCK_BACK` | `written_at` earlier than the previous entry |
| `FOLLOW_SEQ_GAP` | a missing or moved sequence number |
| `FOLLOW_CHAIN_BROKEN` | an entry that does not link to the one before, or does not match its hash |
| `FOLLOW_STOPPED` | any write after `stop` |
| `FOLLOW_SECOND_START` | a second `start` |
| `FOLLOW_NO_START` | a first entry that is not `start` |
| `FOLLOW_BAR_TOO_LATE` | a `bar` written more than one day after its session |

- A `stop` may share the last session date, so a follow can be replaced on the day it started. It cannot be earlier.
- A day not recorded in time can only be written as `missed`. The function that builds a `bar` entry refuses the late day.
- The allowed lateness is one calendar day (`MAX_BAR_LATENESS_DAYS`).

## Verify
- `alpha follow verify <id>` recomputes the chain and the same rules. It reports the first break by entry number and exits 1.
- A flipped byte, a removed middle line and a reordered line are each found. An unreadable line is found at its position.
- Not covered: a removed last line leaves a valid chain. A later build stores each chain head in the nightly status.
- Not covered: this is not an external timestamp. The threat is an accidental back-fill, not a forger.

## Commands
- `follow list`, `show` and `verify` are safe reads. `follow start` and `stop` are owner-only in the generic launcher.
- `follow show` prints the record, the entries by kind and the chain head. It says "waiting for its first new bar" while only `start` exists.
- Ids may be given as a unique prefix of at least four characters.
