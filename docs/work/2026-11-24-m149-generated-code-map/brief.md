# M149: a generated code map

Hand-written code maps go stale: 30 figure modules, `_estimate` and `_progress` had no row in the alpha-cli README.
Fix: `uv run python scripts/fs.py map WORKSPACE [--find WORDS]` prints one line per module (path, line count, first
docstring line), read with `ast`, never stored. A new module always has a home. A test keeps every `alpha_cli`
module described. The alpha-cli README table is deleted; its rules the code cannot say stay as three bullets.
