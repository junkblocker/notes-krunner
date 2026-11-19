"""Run with /usr/bin/python3 -m unittest -v (system D-Bus bindings)."""

import importlib.util
import json
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
        patch.dict(os.environ, {"XDG_CONFIG_HOME": home}),
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

    def test_semantic_prefix_is_removed_before_search_and_creation(self):
        query = " Semantic: word "
        (self.root / "Existing.org").touch()
        create, = self.runner.Match(query)
        self.assertEqual(create[0], f"{self.root}|word.org")
        self.assertEqual(create[1], f"Create {self.root}/word.org")
        note, = self.runner.Match("semantic: Existing")
        self.assertEqual(note[1], "Existing.org")
        self.assertEqual(self.runner.Match("semantic: "), [])

    def test_existing_notes_rank_ahead_of_create(self):
        rows = self.runner.Match("alpha beta")
        existing = [row for row in rows if not row[1].startswith("Create ")]
        create = [row for row in rows if row[1].startswith("Create ")]
        self.assertTrue(existing and create)
        self.assertIn(rows[0], existing)
        self.assertGreater(min(row[4] for row in existing), max(row[4] for row in create))

    def test_missing_note_can_be_created_even_with_ten_matches(self):
        for i in range(12):
            (self.root / f"Existing {i}.org").write_text("An example word appears here.\n")
        rows = self.runner.Match("example word")
        self.assertEqual(len(rows), 11)
        create = rows[-1]
        self.assertEqual(create[1], f"Create {self.root}/example-word.org")
        self.assertEqual(create[5]["category"], "Create Note")
        journals = self.root / "journal"
        journals.mkdir()
        self.runner.index.folders.append(journals)
        target = journals / "Example-WORD.ORG"
        target.touch()
        self.assertFalse(any(row[1].startswith("Create ") for row in self.runner.Match("example word")))
        target.rename(journals / "EXAMPLE WORD.ORG")
        self.assertFalse(any(row[1].startswith("Create ") for row in self.runner.Match("example word")))

    def test_short_word_can_be_created_when_the_filename_is_missing(self):
        create, = self.runner.Match("S3")
        self.assertEqual(create[1], f"Create {self.root}/s3.org")
        (self.root / "S3.ORG").touch()
        self.assertEqual(self.runner.Match("s3"), [])

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


    def test_semantic_matches_follow_literal_notes_and_open_the_line(self):
        literal = self.root / "Lake Guide.org"
        literal.write_text("A data lake holds raw data.\n")
        for i in range(12):
            (self.root / f"Literal {i}.org").write_text("data lake\n")
        related = self.root / "Object Storage.org"
        related.write_text("Cloud storage\nAmazon S3 stores files in buckets.\n")
        fake_sgrep = self.root / "sgrep"
        matches = [
            {"path": literal.name, "start": 1, "content": "A data lake holds raw data.",
             "scores": {"semantic": 0.6}},
            {"path": related.name, "start": 2, "content": "Amazon S3 stores files in buckets.",
             "scores": {"semantic": 0.3}},
            {"path": "other.md", "start": 1, "content": "An unrelated line.",
             "scores": {"semantic": 0.1}},
        ]
        fake_sgrep.write_text(
            "#!/usr/bin/python3\nimport sys\n"
            f"assert sys.argv[-2] == 'data lake'\nprint({json.dumps(matches)!r})\n",
            encoding="utf-8",
        )
        fake_sgrep.chmod(0o755)
        replies = []
        loop = plugin.GLib.MainLoop()

        def receive(rows):
            replies.append(rows)
            loop.quit()

        def stop_loop():
            loop.quit()
            return True

        with patch.object(plugin, "semantic_backend", return_value=(fake_sgrep, self.root)):
            timer = plugin.GLib.timeout_add_seconds(5, stop_loop)
            try:
                self.runner.Match("semantic: data lake", receive)
                if not replies:
                    loop.run()
            finally:
                plugin.GLib.source_remove(timer)
        rows, = replies
        self.assertEqual(
            sum(not row[0].startswith("semantic:") and not row[1].startswith("Create ") for row in rows),
            10,
        )
        self.assertTrue(any(row[1].startswith("Create ") for row in rows))
        literal_row, = (row for row in rows if row[1] == literal.name)
        related_row, = (row for row in rows if row[1] == f"Semantic: {related.name}")
        self.assertLess(rows.index(literal_row), rows.index(related_row))
        self.assertNotIn("Semantic: other.md", [row[1] for row in rows])
        self.assertIn("Object Storage.org:2", related_row[5]["subtext"])
        self.assertEqual(related_row[5]["category"], "Related Notes")
        self.assertGreater(literal_row[4], related_row[4])
        with (
            patch("pathlib.Path.home", return_value=self.root),
            patch.object(plugin.os, "access", return_value=True),
            patch.object(plugin.subprocess, "Popen") as open_note,
        ):
            self.runner.Run(related_row[0], "")
        self.assertEqual(open_note.call_args.args[0][-2:], ["+2", str(related)])

    def test_unavailable_semantic_search_keeps_literal_results(self):
        with patch.object(plugin, "semantic_backend", return_value=None):
            replies = []
            self.runner.Match("alpha beta", replies.append)
        self.assertEqual(replies, [self.runner.Match("alpha beta")])

    def test_semantic_backend_uses_configured_models_and_preserves_local_cache(self):
        program = self.root / "sgrep"
        program.touch(mode=0o755)
        cache = self.root / ".cache"
        configured = self.root / "configured"
        for directory in (cache, configured):
            snapshot = directory / "sgrep-models/hub/models--minishlab--potion-base-8M/snapshots/default"
            snapshot.mkdir(parents=True)
            (snapshot / "model.safetensors").touch()
            (snapshot / "tokenizer.json").touch()
        with (
            patch("pathlib.Path.home", return_value=self.root),
            patch.dict(os.environ, {"HOME": str(self.root), "EMACS_SGREP_DIR": str(self.root)}, clear=True),
            patch.object(plugin.shutil, "which", return_value="/usr/bin/rg"),
            patch.object(plugin, "MODELS_DIR", "~/configured"),
        ):
            self.assertEqual(plugin.semantic_backend(), (program, configured / "sgrep-models/hub"))
            with patch.object(plugin, "MODELS_DIR", "~/missing"):
                self.assertEqual(plugin.semantic_backend(), (program, cache / "sgrep-models/hub"))


if __name__ == "__main__":
    unittest.main()
