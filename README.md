# Notes KRunner plugin

Search Markdown and Org filenames and contents. Queries are literal text, with
exact filenames ranked first and progressively weaker whole-word and partial
content matches below. Up to ten regular results are returned.

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

Creation choices stay within the configured folders. A word such as `wox`
offers `wox.org` and a phrase such as `example word` offers `example-word.org`.
An existing filename that matches the word, phrase, or its hyphenated name
blocks creation in all configured folders. The filename check ignores case.
Existing notes rank first. Valid actions appear under **Create Note**, even
when all ten note results are present.
The optional `agrepr` fuzzy fallback runs only when installed and ordinary search
has no matches. Its subprocess has a two-second timeout per folder.

### Search by meaning

Type a normal query in KRunner. When the sgrep engine and its Potion text
model are available, the Notes runner can show up to three passages under
**Related Notes**, with `Semantic:` at the start of each result title. Strong
literal matches have higher scores. Related results show the note, line number,
and excerpt. Selecting one opens the passage in Emacs when the configured
editor launcher is available. You can type `semantic: word` to search for
`word`. The Create Note suggestion uses the title `word`.

This uses the same engine and model as Emacs notes search. Run
`make related-notes` in the Emacs config to install them. The runner uses the
model offline. Set `MODELS_DIR` in `notes-krunner.py` to the directory that
contains `sgrep-models/hub`. You can use a string with `~` or a Python
`Path`. The runner checks that directory for the model before checking the
local cache. The `HF_HUB_CACHE` environment variable
overrides this lookup and points directly to the Hub cache. Set
`SEMANTIC_SEARCH = False` to use only literal search.

2026-10-23: Keep this runner independent while Wox migration proceeds separately.
The cache replaces repeated full-vault subprocess scans without adding a daemon,
watcher, dependency, or persistent index. Cold queries still read the notes;
very large vaults and slow filesystems can block the synchronous D-Bus method.
Optional sgrep searches run asynchronously and use a separate local index.

## Install

./install.sh

## Uninstall

./uninstall.sh

## Verify changes

`/usr/bin/python3 -m unittest -v test_runner` uses temporary notes and a temporary
Git repository. It requires the system D-Bus and GLib Python bindings.
Edit `%{APPNAMELC}.py`; `install.sh` renders it to `notes.py`, which the installed
D-Bus service and autostart entry execute.
