"""Install the extension with private prebuilt wheels, without root access."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


PROJECT = Path(__file__).resolve().parent.parent


def install(extensions_dir, wheelhouse=None):
    extensions_dir = Path(extensions_dir).resolve()
    extensions_dir.mkdir(parents=True, exist_ok=True)
    vendor_root = extensions_dir / "_nautilus_git_branch_vendor"
    vendor_root.mkdir(exist_ok=True)
    vendor = vendor_root / f"python{sys.version_info.major}.{sys.version_info.minor}"
    # Prepare and verify everything before replacing an existing installation.
    with tempfile.TemporaryDirectory(prefix=".install-", dir=vendor_root) as temporary:
        staging = Path(temporary) / "packages"
        command = [
            sys.executable, "-m", "pip", "install", "--only-binary=:all:",
            "--ignore-installed", "--no-compile", "--no-cache-dir",
            "--disable-pip-version-check", "--no-warn-script-location",
            "--target", str(staging), "--requirement", str(PROJECT / "requirements.txt"),
        ]
        if wheelhouse is not None:
            command.extend(["--no-index", "--find-links", str(Path(wheelhouse).resolve())])
        subprocess.run(command, check=True)
        # Run outside Nautilus, with the exact Python ABI used for installation.
        subprocess.run([
            sys.executable, "-I", "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "import pygit2; "
            "print('Verified private pygit2', pygit2.__version__)", str(staging),
        ], check=True)
        plugin = Path(temporary) / "nautilus_git_branch.py"
        shutil.copyfile(PROJECT / plugin.name, plugin)
        plugin.chmod(0o644)
        backup = Path(temporary) / "previous"
        if vendor.exists():
            vendor.rename(backup)
        try:
            staging.rename(vendor)
            os.replace(plugin, extensions_dir / plugin.name)
        except OSError:
            if vendor.exists():
                shutil.rmtree(vendor)
            if backup.exists():
                backup.rename(vendor)
            raise
    print(f"Installed extension and private wheels in {extensions_dir}")
    print("Run 'nautilus -q', then reopen Files to load the update.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extensions-dir", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path, help="Install offline from pre-downloaded wheels")
    arguments = parser.parse_args()
    try:
        install(arguments.extensions_dir, arguments.wheelhouse)
    except subprocess.CalledProcessError as error:
        parser.exit(1, f"Prebuilt dependency installation failed (exit {error.returncode}). "
                    "Check connectivity and wheel availability for this Python/platform. "
                    "No source compilation is attempted.\n")


if __name__ == "__main__":
    main()
