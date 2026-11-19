#!/usr/bin/python3
"""A Plasma runner for Markdown and Org notes."""

import importlib.util
import json
import logging
import os
import re
import shutil
import subprocess
import time
from collections import OrderedDict
from operator import itemgetter
from pathlib import Path
from urllib.parse import quote

import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import Gio, GLib

DBusGMainLoop(set_as_default=True)

objpath = "/runner"  # Default value for X-Plasma-DBusRunner-Path metadata property
iface = "org.kde.krunner1"
config_dir = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
config_path = config_dir / "notes-krunner.py"

user_config = None
if config_path.exists():
    spec = importlib.util.spec_from_file_location("user_config", config_path)
    if spec and spec.loader:
        user_config = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(user_config)

# 2026-10-23: Keep both config formats; missing config disables this runner.
legacy_config = config_dir / "notes-krunner"
default_folders = (
    legacy_config.read_text().splitlines() if legacy_config.is_file() else []
)
FOLDERS = [
    str(Path(f).expanduser().absolute())
    for f in getattr(user_config, "FOLDERS", default_folders)
    if str(f).strip()
]
FORMATS = {extension.casefold() for extension in getattr(user_config, "FORMATS", ["org", "md"])}
PREFERRED_FORMAT = getattr(user_config, "PREFERRED_FORMAT", "org").lstrip(".")
SEMANTIC_SEARCH = getattr(user_config, "SEMANTIC_SEARCH", True)
MODELS_DIR = getattr(user_config, "MODELS_DIR", None)
LOG = logging.getLogger(__name__)


class NoteIndex:
    """Own discovery and bounded text caching; queries never change process cwd."""

    # 2026-10-23: Coalesce discovery while typing; stat text on every query so
    # saved edits are visible immediately. No background jobs or persistent index.
    def __init__(self, folders):
        self.folders = [Path(folder) for folder in folders]
        self.files = []
        self.refreshed = float("-inf")
        self.texts = OrderedDict()
        self.bytes = 0

    @staticmethod
    def allowed(name):
        parts = Path(name).parts
        return (
            Path(name).suffix.lstrip(".").casefold() in FORMATS
            and not any(
                part in {".git", ".obsidian", ".trash", ".codesearch"} for part in parts
            )
            and "|" not in name
        )

    def refresh(self):
        if time.monotonic() - self.refreshed < 2:
            return
        files = []
        for folder in self.folders:
            if not folder.is_dir():
                continue
            if (folder / ".git").exists():
                try:
                    result = subprocess.run(
                        [
                            "git",
                            "ls-files",
                            "-z",
                            "--cached",
                            "--others",
                            "--exclude-standard",
                        ],
                        cwd=folder,
                        capture_output=True,
                        check=True,
                        timeout=2,
                    )
                    names = os.fsdecode(result.stdout).split("\0")
                except (OSError, subprocess.SubprocessError) as error:
                    LOG.warning("Cannot list notes in %s: %s", folder, error)
                    continue
            else:
                names = []
                for parent, dirs, filenames in os.walk(folder):
                    dirs[:] = [
                        d
                        for d in dirs
                        if d not in {".git", ".obsidian", ".trash", ".codesearch"}
                    ]
                    names.extend(
                        str((Path(parent) / name).relative_to(folder))
                        for name in filenames
                    )
            files.extend(
                (folder, name) for name in sorted(set(names)) if self.allowed(name)
            )
        self.files = files
        live = {folder / name for folder, name in files}
        for path in list(self.texts):
            if path not in live:
                self.bytes -= self.texts.pop(path)[2]
        self.refreshed = time.monotonic()

    def text(self, path):
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)
        cached = self.texts.pop(path, None)
        if cached is not None:
            self.bytes -= cached[2]
        if cached is not None and cached[0] == stamp:
            entry = cached
        else:
            raw = path.read_bytes()
            if b"\0" in raw:
                return ""
            entry = (stamp, raw.decode("utf-8", errors="replace").lower(), len(raw))
        # Bound retained source bytes; larger individual notes are not cached.
        if entry[2] <= 32 * 1024 * 1024:
            while self.texts and self.bytes + entry[2] > 32 * 1024 * 1024:
                self.bytes -= self.texts.popitem(last=False)[1][2]
            self.texts[path] = entry
            self.bytes += entry[2]
        return entry[1]

    def name_exists(self, names, folders):
        """Check indexed subfolders and freshly saved notes at the creation roots."""
        if any(
            Path(name).name.casefold() in names and (folder / name).exists()
            for folder, name in self.files
        ):
            return True
        for folder in folders:
            try:
                with os.scandir(folder) as entries:
                    if any(entry.name.casefold() in names for entry in entries):
                        return True
            except OSError as error:
                LOG.warning("Cannot check note name in %s: %s", folder, error)
                return True
        return False


def get_opener(data: str):
    (vault, note) = data.rsplit("|")
    datapath = str(Path(vault, note))

    # Obsidian has issues opening paths with spaces in them even when URL escaped
    # Kate's preview plugin seems to be having issues
    # nvim's markdown rendering with the right plugins is really good now
    if " " in note:
        if Path(os.environ["HOME"] + "/bin/e").exists():
            return [os.environ["HOME"] + "/bin/e", datapath]
        if Path("/usr/bin/nvim-qt").exists():
            return ["/usr/bin/nvim-qt", datapath]
        elif Path("/usr/bin/kate").exists():
            return ["/usr/bin/kate", datapath]

    if (
        Path("/var/lib/flatpak/app/md.obsidian.Obsidian").exists()
        or Path(os.environ["HOME"] + "/Applications/Obsidian.AppImage").exists()
    ):
        if Path(vault, note).exists():
            return [
                "xdg-open",
                f"obsidian://open?vault=notes&file={quote(note)}",
            ]
        return [
            "xdg-open",
            f"obsidian://new?vault=notes&file={quote(note)}",
        ]

    for opt in (
        os.environ["HOME"] + "/bin/e",
        "/usr/bin/nvim-qt",
        "/usr/bin/kate",
        "/usr/bin/kwrite",
        "/usr/bin/gedit",
    ):
        if Path(opt).exists():
            return [opt, datapath]

    for opt in ("/usr/bin/nvim", "/usr/bin/vim", "/usr/bin/nano"):
        if Path(opt).exists():
            return ["/usr/bin/konsole", "-e", opt, datapath]

    return None


def semantic_backend():
    if not SEMANTIC_SEARCH or not shutil.which("rg"):
        return None
    home = Path.home()
    program = Path(os.environ.get("EMACS_SGREP_DIR") or home / ".local/libexec/emacs-sgrep") / "sgrep"
    if not os.access(program, os.X_OK):
        return None
    cache = Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache")
    override = os.environ.get("HF_HUB_CACHE")
    # 2026-11-19: A missing configured model must preserve local cache discovery.
    hubs = [Path(override)] if override else [
        Path(root).expanduser() / "sgrep-models/hub"
        for root in (MODELS_DIR, cache) if root
    ]
    for hub in hubs:
        snapshots = hub / "models--minishlab--potion-base-8M/snapshots"
        if any(
            weights.is_file() and weights.with_name("tokenizer.json").is_file()
            for weights in snapshots.glob("*/model.safetensors")
        ):
            return program, hub
    return None


def semantic_matches(folder, output, literal_ids):
    for passage in json.loads(output):
        name = passage["path"]
        similarity = passage["scores"]["semantic"]
        path = (folder / name).resolve()
        # 2026-11-18: KRunner sends app names too. Suppress weak matches and
        # keep literal search ahead of the optional passages.
        if similarity < 0.25 or f"{folder}|{name}" in literal_ids:
            continue
        if not path.is_relative_to(folder.resolve()) or not path.is_file() or not NoteIndex.allowed(name):
            continue
        line = passage["start"]
        excerpt = " ".join(passage["content"].split())[:140]
        yield (
            "semantic:" + json.dumps([str(path), line]),
            f"Semantic: {name}",
            "document-edit",
            70,
            min(0.96, 0.85 + 0.2 * similarity),
            {
                # 2026-11-18: Plasma limits rows per displayed category.
                "category": "Related Notes",
                "subtext": f"{folder.name}/{name}:{line} - {excerpt}",
            },
        )


class SemanticSearch:
    """Run each configured folder off the D-Bus event loop."""

    def __init__(self, query, folders, backend, literal, reply):
        self.processes = set()
        self.rows = []
        self.reply = reply
        self.literal = literal
        self.literal_ids = {row[0] for row in literal}
        self.timer = GLib.timeout_add(3500, self.expire)
        program, hub = backend
        launcher = Gio.SubprocessLauncher.new(
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE
        )
        launcher.setenv("HF_HUB_CACHE", str(hub), True)
        launcher.setenv("HF_HUB_OFFLINE", "1", True)
        for folder in folders:
            if not folder.is_dir():
                continue
            try:
                process = launcher.spawnv([
                    str(program), "--model", "text", "--json", "--explain",
                    "-n", "6", "--", query, str(folder),
                ])
                self.processes.add(process)
                process.communicate_utf8_async(None, None, self.finished, folder)
            except GLib.Error as error:
                LOG.warning("Cannot start sgrep: %s", error)

    def finished(self, process, result, folder):
        if process not in self.processes:
            return
        self.processes.remove(process)
        try:
            ok, stdout, _ = process.communicate_utf8_finish(result)
            if ok and process.get_successful():
                self.rows.extend(semantic_matches(folder, stdout, self.literal_ids))
        except (GLib.Error, OSError, ValueError, TypeError, KeyError) as error:
            LOG.warning("Cannot read sgrep matches: %s", error)
        if not self.processes:
            self.finish()

    def expire(self):
        self.timer = None
        self.finish()
        return GLib.SOURCE_REMOVE

    def finish(self):
        if self.timer is not None:
            GLib.source_remove(self.timer)
            self.timer = None
        for process in self.processes:
            process.force_exit()
        self.processes.clear()
        if self.reply is not None:
            reply, self.reply = self.reply, None
            unique = {}
            for row in sorted(self.rows, key=itemgetter(4), reverse=True):
                unique.setdefault(row[0], row)
            reply(self.literal + list(unique.values())[:3])


class Runner(dbus.service.Object):
    def __init__(self):
        dbus.service.Object.__init__(
            self,
            dbus.service.BusName("org.kde.%{APPNAMELC}", dbus.SessionBus()),
            objpath,
        )
        self.notes_dirs = FOLDERS
        self.index = NoteIndex(self.notes_dirs)
        self.semantic = None

    @dbus.service.method(
        iface, in_signature="s", out_signature="a(sssida{sv})",
        async_callbacks=("reply", "error"),
    )
    def Match(self, query: str, reply=None, error=None):
        if self.semantic is not None:
            self.semantic.finish()
            self.semantic = None
        # 2026-11-19: Use the same title for searching and offering creation.
        query = re.sub(r"^semantic:\s*", "", query.strip(), flags=re.IGNORECASE)
        literal = self.literal_matches(query)
        if reply is None:
            return literal
        backend = semantic_backend() if len(query.strip()) >= 3 else None
        if not backend:
            reply(literal)
        else:
            self.semantic = SemanticSearch(query, self.index.folders, backend, literal, reply)
            if not self.semantic.processes:
                self.semantic.finish()

    def literal_matches(self, query):
        query = query.strip().lower()
        if not query:
            return []
        if len(query) < 3:
            self.index.refresh()
            return self.creation_matches(query)
        words = query.split()
        # 2026-10-23: Queries are literal text, never regular expressions.
        patterns = [re.compile(r"\b" + re.escape(word) + r"\b") for word in words]
        prefixes = [re.compile(r"\b" + re.escape(word)) for word in words]
        suffixes = [re.compile(re.escape(word) + r"\b") for word in words]
        self.index.refresh()
        seen = {}
        for folder, name in self.index.files:
            path = folder / name
            try:
                if not path.is_file():
                    continue
                lowered = name.lower()
                score = 0
                if Path(name).stem.lower() == query:
                    score = 1.0
                elif all(pattern.search(lowered) for pattern in patterns):
                    score = 0.99
                elif query in lowered or re.search(
                    ".*".join(map(re.escape, words)), lowered
                ):
                    score = 0.98
                if not score:
                    for line in self.index.text(path).splitlines():
                        if all(word in line for word in words):
                            if all(pattern.search(line) for pattern in patterns):
                                score = max(score, 0.97)
                                break
                            if all(pattern.search(line) for pattern in prefixes):
                                score = max(score, 0.95)
                            elif all(pattern.search(line) for pattern in suffixes):
                                score = max(score, 0.93)
                            else:
                                score = max(score, 0.91)
                if score:
                    seen[f"{folder}|{name}"] = score
            except OSError as error:
                LOG.warning("Cannot read note %s: %s", path, error)

        # Preserve the optional fuzzy fallback without requiring agrepr.
        if not seen and shutil.which("agrepr"):
            for folder in self.index.folders:
                if not folder.is_dir():
                    continue
                try:
                    result = subprocess.run(
                        ["agrepr", "-i", "-l", "--", query],
                        cwd=folder,
                        capture_output=True,
                        check=False,
                        timeout=2,
                    )
                    for name in os.fsdecode(result.stdout).splitlines():
                        if self.index.allowed(name) and (folder / name).is_file():
                            seen[f"{folder}|{name}"] = 0.89
                except (OSError, subprocess.SubprocessError) as error:
                    LOG.warning("Fuzzy note search failed: %s", error)
        results = []
        for item, score in seen.items():
            if "_attic/" in item:
                score -= 0.05
            if ".stversions/" in item:
                score -= 0.10
            results.append(
                (
                    item,
                    item.split("|", 1)[1],
                    "document-edit",
                    100,
                    score,
                    {"subtext": item},
                )
            )

        results.sort(key=itemgetter(4), reverse=True)
        # Plasma limits rows per category. Keep valid creation actions outside
        # the ten-note limit so a full Notes category cannot hide them.
        return results[:10] + self.creation_matches(query)

    def creation_matches(self, query):
        stem = query.replace(" ", "-")
        # A create result must stay inside the configured vault.
        if any(char in stem for char in "/\\|\0") or any(ord(char) < 32 for char in stem):
            return []
        name = f"{stem}.{PREFERRED_FORMAT}"
        names = {name.casefold(), f"{query}.{PREFERRED_FORMAT}".casefold()}
        folders = [folder for folder in self.index.folders if folder.is_dir()]
        if self.index.name_exists(names, folders):
            return []
        return [
            (
                f"{folder}|{name}",
                f"Create {folder / name}",
                "document-edit",
                30,
                0.4,
                {"category": "Create Note", "subtext": stem},
            )
            for folder in folders
        ]

    @dbus.service.method(iface, out_signature="a(sss)")
    def Actions(self):
        # id, text, icon
        return []

    @dbus.service.method(iface, in_signature="ss")
    def Run(self, data: str, action_id: str):
        try:
            if data.startswith("semantic:"):
                path, line = json.loads(data.removeprefix("semantic:"))
                path = Path(path).resolve()
                if not isinstance(line, int) or line < 1 or not path.is_file() or not any(
                    path.is_relative_to(folder.resolve()) for folder in self.index.folders
                ):
                    return
                editor = Path.home() / "bin/e"
                opener = (
                    [str(editor), "--editor=emacs", f"+{line}", str(path)]
                    if os.access(editor, os.X_OK) else ["xdg-open", str(path)]
                )
            else:
                opener = get_opener(data)
            if opener:
                _ = subprocess.Popen(opener).pid
        except (OSError, TypeError, ValueError) as error:
            LOG.warning("Cannot open note: %s", error)


if __name__ == "__main__":
    runner = Runner()
    loop = GLib.MainLoop()
    loop.run()
