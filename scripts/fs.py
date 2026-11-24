"""The file system's command line: orientation and document search.

    uv run python scripts/fs.py orient [--component NAME] [--json]
    uv run python scripts/fs.py search "QUERY" [--kind KIND] [--limit N] [--format text|json]
    uv run python scripts/fs.py map WORKSPACE [--find WORDS...]
    uv run python scripts/fs.py see CAPABILITY_ID [--run]

``orient`` lists components, module counts and the routing documents to read first. ``search``
returns ranked excerpts of tracked documentation (path, heading, line range, kind). ``map`` prints
one line per module of a workspace (path, lines, docstring line), made from the code. Nothing here
writes: pages are checked by a weekly sweep, not by a stored stamp.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import fs_map
import fs_orient
import fs_search
import fs_see


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
    code = sub.add_parser("map", help="one line per module of a workspace, made from the code")
    code.add_argument("workspace", help="for example apps/alpha-cli")
    code.add_argument("--find", nargs="+", metavar="WORD", help="keep lines holding all words")
    see = sub.add_parser("see", help="a capability card's see_it lines; --run runs alpha commands")
    see.add_argument("capability_id")
    see.add_argument("--run", action="store_true", help="run lines that are one alpha command")
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
        elif args.command == "map":
            print(fs_map.code_map(root, _relative(root, args.workspace), args.find))
        elif args.command == "see":
            text, code = fs_see.see(root, args.capability_id, run=args.run)
            print(text)
            return code
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
