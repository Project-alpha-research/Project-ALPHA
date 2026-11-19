---
owner: command line follow journal
sources:
  - apps/alpha-cli/src/alpha_cli/follow_journal.py
  - apps/alpha-cli/src/alpha_cli/follow_chain.py
  - apps/alpha-cli/src/alpha_cli/follow_store.py
  - apps/alpha-cli/src/alpha_cli/follow_source.py
  - apps/alpha-cli/src/alpha_cli/follow_cmds.py
  - tests/unit/test_follow_separation.py
verified: f9e95839616de75b
---

# Command line follow invariants

Rules for `alpha follow`. A tested idea is followed on paper as new bars arrive. Options are in the
[command reference](../commands.md#alpha-follow). Build F1 only: the frozen record and the journal.
No signal is computed and no trade is simulated yet. Every screen of text says "paper".

## Separation (the integrity rule)
- `<data_dir>/forward/` is one-way. Research writes nothing there and reads nothing from there.
- Only the modules on the explicit `READERS` list in `tests/unit/test_follow_separation.py` may name the follow store
  modules or open a path under `forward/`. Today that is the five `follow_*.py` modules. A new reader (the F2 nightly step,
  a Today page) is added to the list on purpose, in review.
- The guard reads source text under `apps/*/src`, `packages/*/src` and `workers/`. It also fails on the store's file names
  (`journal.jsonl`, `follow.toml`), `FOLLOW_DIR`, `AlphaFollowV1`, a name glued from parts (`"for" "ward"`), and a module that
  lists every folder of the data directory (`home` or `data_dir` with `iterdir`, `rglob`, `os.walk`, `copytree`, or a `glob` that starts with `*`).
  It proves itself with fixture strings, not an edit of real modules. It is a text guard: a path built at run time from
  other words is not caught.
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
- Changing a followed idea is never an edit. The idea is the linked idea card. Without a card, the idea is the source:
  the same rule test or setup find (`kind` and `source_id`). Two different tests without a card are two ideas, because
  nothing stored links them. Link a card to make them one idea.
- `follow start` on the same spec, assets and size of an active follow returns that follow. Nothing is written.
- A different spec, asset set or size for the same idea makes a new follow: `version` plus one and `supersedes` set.
  The old follow gets a `stop` entry. Its folder is kept. The text says the forward clock restarts.
- The new follow is written first. A crash can leave two active follows. It cannot leave none.
- Starts take one lock (`forward/.start.lock`), so two starts at once of one spec make one follow.

## The journal
- `forward/<follow_id>/journal.jsonl` is append-only. One line is one entry.
- Entry fields: `seq` (from 1), `session_date`, `written_at` (aware UTC, from an injected clock), `kind`
  (`start`, `bar`, `missed`, `late`, `stop`), `bar_hashes` (latest bar hash per asset), `payload` (free object),
  `prev_hash`, `entry_hash`. The hash is SHA-256 of the canonical entry without `entry_hash`. The first `prev_hash` is 64 zeros.
- F1 commands write only `start` and `stop`. The writer already supports the other kinds.
- The start entry's payload names its `follow_id`. A journal moved into another follow's folder fails every read.
- Append takes an exclusive lock, checks the whole chain, writes one line and syncs it. Then, under the same lock, it
  replaces `forward/<follow_id>/head.json` (`entries` and `head`, the last entry hash) atomically.
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
| `FOLLOW_SESSION_AHEAD` | a session date later than the day of `written_at`: a day cannot be recorded before it happens |

- A `stop` may share the last session date, so a follow can be replaced on the day it started. It cannot be earlier.
- A day not recorded in time can only be written as `missed`. The function that builds a `bar` entry refuses the late day.
- The allowed lateness is one calendar day (`MAX_BAR_LATENESS_DAYS`), counted from the session date to the UTC date of
  `written_at`. This is stricter than the design rule (a bar may be written up to the next session's open): a Friday
  bar written on Sunday is refused and must be `missed`. F2 may widen it only with the market calendar in
  `alpha_data.sessions`, never by a larger day count.

## Verify
- `alpha follow verify <id>` recomputes the chain and the same rules. It reports the first break by entry number and exits 1.
- A flipped byte, a removed middle line and a reordered line are each found. An unreadable line is found at its position.
- The journal is compared with `head.json`. Fewer entries than the head names is `FOLLOW_TRUNCATED` (a removed last line,
  or a shorter valid chain in place of the file). Another hash at the head number is `FOLLOW_CHAIN_BROKEN`. A missing
  `head.json` counts as a head of 0 entries.
- The head may be one entry behind: a crash after the line was synced and before the head was replaced. That verifies,
  and the next append stores the head again. More than one entry ahead of the head is `FOLLOW_TRUNCATED`.
- An entry with `written_at` later than the verifier's clock is `FOLLOW_WRITTEN_AHEAD`. A follow folder with a record and
  no start entry is `FOLLOW_NO_START`. A journal from another follow is `FOLLOW_WRONG_FOLDER`.
- Not covered: the journal and `head.json` rewritten together. A later build also stores each head in the nightly status.
- Not covered: this is not an external timestamp. The threat is an accidental back-fill, not a forger.

## Repair
A last line that was not written to its end (a crash or a full disk during an append) is `FOLLOW_PARTIAL_LINE`. Every read
and every append fails loud on it. Nothing repairs it on its own, and no data is dropped. The owner repairs it:
1. Copy the whole follow folder to a safe place. Keep the copy.
2. Open `journal.jsonl` and remove only the incomplete last line (the text after the last newline).
3. Run `alpha follow verify <id>`. The head was not replaced for the cut-off line, so the chain verifies.

## Commands
- `follow list`, `show` and `verify` are safe reads. `follow start` and `stop` are owner-only in the generic launcher.
- `follow show` prints the record, the entries by kind and the chain head. It says "waiting for its first new bar" while only `start` exists.
- Ids may be given as a unique prefix of at least four characters.
