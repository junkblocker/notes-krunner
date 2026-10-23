"""Run with /usr/bin/python3 -m unittest -v (system D-Bus bindings)."""

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def load_runner():
    spec = importlib.util.spec_from_file_location(
        "notes_runner", Path(__file__).with_name("%{APPNAMELC}.py")
    )
    module = importlib.util.module_from_spec(spec)
    with (
        tempfile.TemporaryDirectory() as home,
        patch("pathlib.Path.home", return_value=Path(home)),
    ):
        spec.loader.exec_module(module)
    return module


plugin = load_runner()


class NotesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.joinpath("literal[one].org").write_text("alpha beta\n")
        self.root.joinpath("other.md").write_text("alpha beta\n")
        with (
            patch.object(plugin, "FOLDERS", [str(self.root)]),
            patch.object(plugin.dbus, "SessionBus"),
            patch.object(plugin.dbus.service, "BusName"),
            patch.object(plugin.dbus.service.Object, "__init__", return_value=None),
        ):
            self.runner = plugin.Runner()

    def test_literal_filename_and_existing_create_target(self):
        before = Path.cwd()
        results = self.runner.Match("literal[one]")
        self.assertEqual(Path.cwd(), before)
        self.assertEqual(results[0][1], "literal[one].org")
        self.assertEqual(results[0][4], 1.0)
        self.assertFalse(any(row[1].startswith("Create ") for row in results))

    def test_wox_create_label_and_action_both_include_extension_dot(self):
        with patch.object(plugin.shutil, "which", return_value=None):
            rows = self.runner.Match("wox")
        self.assertEqual(rows[0][1], f"Create {self.root}/wox.org")
        self.assertEqual(rows[0][0], f"{self.root}|wox.org")

    def test_edits_are_visible_without_rescanning_or_spawning_searches(self):
        with (
            patch.object(
                plugin.subprocess,
                "run",
                side_effect=AssertionError("unexpected search process"),
            ),
            patch.object(plugin.shutil, "which", return_value=None),
        ):
            self.assertTrue(
                any(row[1] == "other.md" for row in self.runner.Match("alpha"))
            )
            (self.root / "other.md").write_text("saved replacement\n")
            self.assertFalse(
                any(row[1] == "other.md" for row in self.runner.Match("alpha"))
            )
            self.assertTrue(
                any(row[1] == "other.md" for row in self.runner.Match("replacement"))
            )

    def test_filters_and_safe_create_paths(self):
        (self.root / "ignored.txt").write_text("alpha beta")
        (self.root / ".obsidian").mkdir()
        (self.root / ".obsidian/hidden.md").write_text("alpha beta")
        (self.root / "two\nlines.md").write_text("alpha beta")
        rows = self.runner.Match("alpha beta")
        self.assertTrue(any(row[1] == "two\nlines.md" for row in rows))
        self.assertFalse(
            any("ignored.txt" in row[0] or ".obsidian" in row[0] for row in rows)
        )
        with patch.object(plugin.shutil, "which", return_value=None):
            self.assertEqual(self.runner.Match("../escape"), [])
        create = [row for row in rows if row[1].startswith("Create ")]
        self.assertEqual(create[0][1], f"Create {self.root}/alpha-beta.org")

    def test_git_discovery_includes_untracked_notes_and_respects_ignores(self):
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
        }
        subprocess.run(["git", "init", "-q", str(self.root)], env=env, check=True)
        (self.root / ".gitignore").write_text("ignored.md\n")
        (self.root / "ignored.md").write_text("alpha beta")
        (self.root / "new.md").write_text("alpha beta")
        rows = self.runner.Match("alpha beta")
        self.assertTrue(any(row[1] == "new.md" for row in rows))
        self.assertFalse(any(row[1] == "ignored.md" for row in rows))


if __name__ == "__main__":
    unittest.main()
