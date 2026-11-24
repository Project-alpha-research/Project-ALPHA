"""The suite vocabulary imports without loading orchestration."""

import subprocess
import sys


def test_suite_catalog_import_does_not_load_orchestration() -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import alpha_cli.suite_catalog; "
            "assert not any(name in sys.modules for name in "
            "('alpha_cli._suite', 'alpha_cli.control_store', 'numpy', 'nautilus_trader'))",
        ],
        check=True,
    )
