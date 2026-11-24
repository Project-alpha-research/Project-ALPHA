# M166 release line

Goal: one tagged version and one command that installs it, checks it, and goes back by itself on failure.

- `.github/workflows/release.yml` tags each commit on main as `r<YYYY.MM.DD>.<run number>` and writes a GitHub Release.
- `scripts/update.sh` installs a tag with every locked environment, restarts the service and runs a smoke check.
- `alpha home update` starts that script. `--check-only` asks whether the installed product is healthy.
- The owner approved the two protected files on 2026-11-24. The way it works: `docs/operations/update-installed-product.md`.
