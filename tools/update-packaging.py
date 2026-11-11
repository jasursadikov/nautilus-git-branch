"""Refresh local release checksums and regenerate the AUR .SRCINFO file."""

import argparse
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


PROJECT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-sources", action="store_true",
                        help="Prepare ignored source snapshots for building unpublished changes")
    arguments = parser.parse_args()
    pkgbuild = PROJECT / "PKGBUILD"
    text = pkgbuild.read_text()
    match = re.search(r"^sha256sums=\(\n(.*?)\n\)", text, re.MULTILINE | re.DOTALL)
    if match is None:
        raise SystemExit("PKGBUILD is missing its release checksum array")
    lines = match.group(1).splitlines()
    if len(lines) != 4:
        raise SystemExit("Expected three project sources followed by the pycparser wheel")
    for index, name in enumerate(("nautilus_git_branch.py", "README.md", "LICENSE")):
        digest = hashlib.sha256((PROJECT / name).read_bytes()).hexdigest()
        lines[index] = f"    '{digest}'"
    text = text[:match.start(1)] + "\n".join(lines) + text[match.end(1):]
    with tempfile.NamedTemporaryFile(mode="w", prefix=".PKGBUILD-", dir=PROJECT) as temporary:
        temporary.write(text)
        temporary.flush()
        metadata = subprocess.check_output(
            ["makepkg", "--printsrcinfo", "-p", temporary.name], text=True, cwd=PROJECT,
        )
    pkgbuild.write_text(text)
    (PROJECT / ".SRCINFO").write_text(metadata)
    if arguments.local_sources:
        version = re.search(r"^pkgver=([0-9A-Za-z._+]+)$", text, re.MULTILINE)
        if version is None:
            raise SystemExit("Expected an unquoted release pkgver in PKGBUILD")
        prefix = f"nautilus-git-branch-{version.group(1)}"
        for name, destination in (
            ("nautilus_git_branch.py", f"{prefix}.py"),
            ("README.md", f"{prefix}-README.md"),
            ("LICENSE", f"{prefix}-LICENSE"),
        ):
            shutil.copyfile(PROJECT / name, PROJECT / destination)
        print("Prepared local source snapshots for makepkg")
    print("Updated release checksums in PKGBUILD and regenerated .SRCINFO")


if __name__ == "__main__":
    main()
