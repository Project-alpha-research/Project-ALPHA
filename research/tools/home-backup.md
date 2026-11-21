---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/home_cmds.py
  - apps/alpha-cli/src/alpha_cli/home_backup.py
  - apps/alpha-cli/src/alpha_cli/home_restore.py
verified: f94fbcd05eac0fd4
---
# Back up and restore the data home

**Reach for it when** you want a copy of everything ALPHA stores (bars, runs, the ledger, follows), or want proof that a copy is good.

**Command**
```text
uv run alpha home backup <folder outside the home> [--json]
uv run alpha home verify-backup <archive.tar> [--json]
uv run alpha home restore <archive.tar> <new empty folder> [--json]
```

**How to read it**
- `backup` writes ONE file, `alpha-home-<UTC time>.tar`, and `<name>.tar.sha256` beside it (`sha256sum -c` can read it).
- The last entry in the archive is `manifest.json`: the path, size and SHA-256 of every file, every folder, and everything left out.
- Left out, always with the reason in the manifest and on screen: symbolic links (never followed) and pipes or devices.
- Before it writes, it checks that the target disk has room (the size of the home plus a small margin) and says plainly if not.
- A second name of the same file (a hard link) is stored in full under each name. A folder it cannot read stops the backup: nothing is skipped silently.
- It refuses a folder inside the data home. Put the archive on another disk: a copy on the same disk is lost with the disk.
- It takes the nightly lock (`<home>/nightly/.lock`). If a scheduled nightly run holds it, the backup refuses: run it again later.
- If a file changes while it is read, the backup stops and keeps nothing. Stop the other command, then run it again.
- `verify-backup` reads the archive again and checks every file against the manifest. It prints the counts. It extracts nothing.
  `BACKUP CHECK FAILED` names each bad file; the exit code is 1.
- `restore` checks the archive first, then writes it into a new or empty folder. It refuses a folder with anything in it,
  and it refuses the live home. It keeps file and folder modes and times, then reads every written file again from disk and checks it
  against the manifest. A restore that fails leaves an incomplete folder: delete it. To look at the copy: `ALPHA_DATA_DIR=<folder> uv run alpha next`.

**What it cannot tell you** Whether the data inside was right when you made the backup: it copies bytes and judges nothing.
The lock stops only a nightly run started from the crontab line. Another command you start by hand is caught by the changed-file check
only if it writes while the backup reads that file. The archive is not encrypted and not compressed.
A passed check on the day of the backup says nothing about the disk a year later: check again before you rely on it.

**Next** Run `verify-backup` straight after every backup. Disk facts: [nightly failure marker and disk trend](nightly-alert.md).
