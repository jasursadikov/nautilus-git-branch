from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.install import install


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.extensions = Path(self.temporary.name) / "extensions"

    def fake_pip(self, command, **kwargs):
        if "--target" in command:
            target = Path(command[command.index("--target") + 1])
            target.mkdir()
            (target / "dependency-marker").write_text("prebuilt")

    def test_binary_only_private_install_and_offline_options(self):
        wheelhouse = Path(self.temporary.name) / "wheels"
        with patch("tools.install.subprocess.run", side_effect=self.fake_pip) as run:
            install(self.extensions, wheelhouse)
        pip = run.call_args_list[0].args[0]
        self.assertIn("--only-binary=:all:", pip)
        self.assertIn("--ignore-installed", pip)
        self.assertIn("--no-index", pip)
        self.assertIn(str(wheelhouse), pip)
        self.assertTrue((self.extensions / "nautilus_git_branch.py").is_file())
        self.assertEqual(len(list(self.extensions.glob("_nautilus_git_branch_vendor/python*/dependency-marker"))), 1)

    def test_download_failure_preserves_existing_plugin(self):
        self.extensions.mkdir()
        plugin = self.extensions / "nautilus_git_branch.py"
        plugin.write_text("old plugin")
        with patch("tools.install.subprocess.run", side_effect=subprocess.CalledProcessError(1, "pip")):
            with self.assertRaises(subprocess.CalledProcessError):
                install(self.extensions)
        self.assertEqual(plugin.read_text(), "old plugin")

    def test_import_failure_does_not_replace_working_installation(self):
        self.extensions.mkdir()
        plugin = self.extensions / "nautilus_git_branch.py"
        plugin.write_text("old plugin")

        def fail_validation(command, **kwargs):
            if "--target" in command:
                self.fake_pip(command, **kwargs)
            else:
                raise subprocess.CalledProcessError(1, command)

        with patch("tools.install.subprocess.run", side_effect=fail_validation):
            with self.assertRaises(subprocess.CalledProcessError):
                install(self.extensions)
        self.assertEqual(plugin.read_text(), "old plugin")
        self.assertFalse(list(self.extensions.glob("_nautilus_git_branch_vendor/python*")))

    def test_upgrade_replaces_previous_dependencies(self):
        with patch("tools.install.subprocess.run", side_effect=self.fake_pip):
            install(self.extensions)
            vendor = next(self.extensions.glob("_nautilus_git_branch_vendor/python*"))
            (vendor / "obsolete").write_text("old")
            install(self.extensions)
        self.assertFalse((vendor / "obsolete").exists())
        self.assertEqual((vendor / "dependency-marker").read_text(), "prebuilt")
