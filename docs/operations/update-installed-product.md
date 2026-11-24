# Update the installed product

Run one command: `uv run alpha home update`. It installs the newest release, checks it, and goes back by itself when the check fails.

## Releases

Every commit that lands on main gets a tag `r<YYYY.MM.DD>.<number>` and a GitHub Release with notes
(`.github/workflows/release.yml`). The commit already passed the full suite in the merge queue.

## The command

`alpha home update [--to TAG] [--check-only] [--service NAME] [--no-restart]` runs `scripts/update.sh`. The script is plain bash, so it does not
depend on the Python environment it replaces. Steps:

1. Refuse when tracked files have changes or less than 3 GB of disk is free.
2. Save the current commit in `.update/last-good`.
3. Check out the tag. Install the root environment, every `workers/*` folder that has a `uv.lock`, and the web app.
4. Restart the service (default `alpha-workstation.service`), unless `--no-restart`.
5. Check: `alpha --help`, `alpha next`, one environment per worker, the service on its port, the Workstation page,
   and `alpha data coverage` (reads only). Install details go to `.update/update.log`.

## "Returned to the last good version"

When any step fails, the script puts the checkout back on the commit in `.update/last-good`, installs it, restarts the service and checks again.
It then exits 1 and says so. Exit 2 means the return failed too; the message names the last good commit.

`alpha home update --check-only` changes nothing. It asks: is the installed product healthy?
