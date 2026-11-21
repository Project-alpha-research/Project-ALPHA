# Back up the data home

The data home is the one folder where ALPHA keeps stored bars, runs, the trial ledger, idea cards and
follows (`ALPHA_DATA_DIR`). The repository does not hold it. If the disk fails and there is no backup,
that history is gone. The commands and how to read them: [tool card](../../research/tools/home-backup.md).

## A routine that is enough

1. Plug in a second disk. The backup folder must be outside the data home, and should be on another disk.
2. Make the backup: `uv run alpha home backup /path/on/other/disk`.
   If it says a nightly run is in progress, wait for that run and start the backup again.
3. Check it at once: `uv run alpha home verify-backup /path/on/other/disk/alpha-home-<time>.tar`.
   Keep the `.sha256` file next to the archive.
4. A few times a year, prove a restore: `uv run alpha home restore <archive> /path/to/new-empty-folder`,
   then `ALPHA_DATA_DIR=/path/to/new-empty-folder uv run alpha next`. Delete the test folder afterwards.

## What the commands never do

- They never write inside the live data home, except the empty lock file `nightly/.lock`.
- `restore` never overwrites the live home. To go back to a backup after a real loss, restore into a new
  folder and point `ALPHA_DATA_DIR` at it. That switch is your decision; no command makes it.
- They install no schedule, send nothing over the network, and do not encrypt. Keep the backup disk safe.

## Watch the disk

`uv run alpha nightly status` shows the size of the data home, the free space and the growth across
nightly records, and warns when free space is under your [storage reserve](storage-settings.md).
An archive is about as large as the data home: check the free space on the backup disk first.
A failed night leaves `<data home>/nightly/LAST_FAILED`:
[failure marker and disk trend](../../research/tools/nightly-alert.md).
