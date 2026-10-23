# Notes KRunner plugin

Search Markdown and Org filenames and contents. Queries are literal text, with
exact filenames ranked first and progressively weaker whole-word and partial
content matches below. Up to ten results are returned.

## Configuration

Set `FOLDERS`, `FORMATS`, and `PREFERRED_FORMAT` in the trusted Python file
`~/.config/notes-krunner.py`, for example:

```python
FOLDERS = ["~/notes"]
FORMATS = ["org", "md"]
PREFERRED_FORMAT = "org"
```

The older `~/.config/notes-krunner` file, with one directory per line, remains
supported when `FOLDERS` is not set. Missing folders are skipped. Restart the
runner after changing configuration.

Filename discovery refreshes on demand every two seconds. Git vaults include
tracked and untracked files while respecting Git ignores. Other directories
are walked directly. `.git`, `.obsidian`, `.trash`, and `.codesearch` are excluded.
Saved contents are refreshed on the next query using file timestamps and size.
The text cache retains at most 32 MiB of source bytes; Python storage uses more
memory. Large notes still work but are not retained in that cache.

Creation choices stay within the configured folders and include the extension
dot: `wox` offers `wox.org`. Existing targets do not get creation choices.
The optional `agrepr` fuzzy fallback runs only when installed and ordinary search
has no matches. Its subprocess has a two-second timeout per folder.

2026-10-23: Keep this runner independent while Wox migration proceeds separately.
The cache replaces repeated full-vault subprocess scans without adding a daemon,
watcher, dependency, or persistent index. Cold queries still read the notes;
very large vaults and slow filesystems can block the synchronous D-Bus method.

## Install

./install.sh

## Uninstall

./uninstall.sh

## Verify changes

`/usr/bin/python3 -m unittest -v test_runner` uses temporary notes and a temporary
Git repository. It requires the system D-Bus and GLib Python bindings.
Edit `%{APPNAMELC}.py`; `install.sh` renders it to `notes.py`, which the installed
D-Bus service and autostart entry execute.
