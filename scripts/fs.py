"""The file system's command line: orientation, document search and staleness.

    uv run python scripts/fs.py orient [--component NAME] [--json]
    uv run python scripts/fs.py search "QUERY" [--kind KIND] [--limit N] [--format text|json]
    uv run python scripts/fs.py stale [--strict] [--format text|json]
    uv run python scripts/fs.py owners PATH... [--json]
    uv run python scripts/fs.py verify DOCUMENT...

``orient`` lists components, module counts and the routing documents to read first. ``search``
returns ranked excerpts of tracked documentation (path, heading, line range, kind). ``stale``
lists living documents whose ``sources`` no longer match their ``verified`` fingerprint; it
exits 0 (a report) unless ``--strict`` is given or a document's front matter cannot be checked.
``owners`` lists the living documents that describe each path. ``verify`` is the only command
that writes: after you re-read a document against its sources, it records their fingerprint.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import fs_orient
import fs_search
import fs_stale


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fs", description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--root", type=Path, help="ALPHA checkout (default: this script's)")
    sub = parser.add_subparsers(dest="command", required=True)
    orient = sub.add_parser("orient", help="components, module counts and routing documents")
    orient.add_argument("--component", help="list one component's modules")
    orient.add_argument("--json", action="store_true")
    search = sub.add_parser("search", help="ranked excerpts of tracked documentation")
    search.add_argument("query")
    search.add_argument("--kind", choices=fs_search.KINDS, default="all")
    search.add_argument("--limit", type=int, default=8, help="excerpts to show (1-20)")
    search.add_argument("--format", choices=("text", "json"), default="text")
    stale = sub.add_parser("stale", help="living documents whose sources changed since verified")
    stale.add_argument("--strict", action="store_true", help="exit 1 when any document is stale")
    stale.add_argument("--format", choices=("text", "json"), default="text")
    owners = sub.add_parser("owners", help="living documents that describe each path")
    owners.add_argument("paths", nargs="+")
    owners.add_argument("--json", action="store_true")
    verify = sub.add_parser("verify", help="record that a document matches its sources now")
    verify.add_argument("documents", nargs="+")
    return parser


def _relative(root: Path, name: str) -> str:
    """A path as git names it, whether given from the root, the current directory or absolute."""
    path = Path(name)
    if not path.is_absolute() and (root / path).exists():
        return path.as_posix()
    return path.resolve().relative_to(root.resolve()).as_posix()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root: Path = args.root if args.root is not None else Path(__file__).resolve().parents[1]
    try:
        if args.command == "orient":
            payload = fs_orient.orientation(root, component=args.component)
            print(
                json.dumps(payload, sort_keys=True)
                if args.json
                else fs_orient.render_orientation(payload)
            )
        elif args.command == "stale":
            reports = fs_stale.stale(root)
            print(
                json.dumps([r.as_dict() for r in reports], sort_keys=True, indent=2)
                if args.format == "json"
                else fs_stale.render_text(reports)
            )
            if any(r.problems for r in reports):
                return 1
            if args.strict and any(r.stale for r in reports):
                return 1
        elif args.command == "owners":
            found = fs_stale.owners(root, [_relative(root, name) for name in args.paths])
            if args.json:
                print(json.dumps(found, sort_keys=True))
            else:
                for path, documents in found.items():
                    print(f"{path}: {', '.join(documents) or 'no living document describes it'}")
        elif args.command == "verify":
            for report in fs_stale.verify(root, [_relative(root, name) for name in args.documents]):
                print(
                    f"verified {report.path}: {report.verified} -> {report.fingerprint}"
                    if report.stale
                    else f"already current {report.path}"
                )
        else:
            result = fs_search.search(root, args.query, kind=args.kind, limit=args.limit)
            print(
                json.dumps(result, sort_keys=True, indent=2)
                if args.format == "json"
                else fs_search.render_text(result)
            )
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"fs {args.command}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
