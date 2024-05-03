#!/usr/bin/python3
"""A Plasma runner."""

import os
import re
import subprocess
from contextlib import suppress
from functools import cache
from pathlib import Path
from urllib.parse import quote

import dbus.service
# import q
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

# from urllib.parse import quote


DBusGMainLoop(set_as_default=True)

OBJPATH = "/%{APPNAMELC}"
IFACE = "org.kde.krunner1"
SERVICE = "org.kde.%{APPNAMELC}"


@cache
def get_opener(data: str) -> list[str] | None:
    (vault, note) = data.rsplit("|")
    datapath = str(Path(vault, note))

    # Obsidian has issues opening paths with spaces in them even when URL escaped
    # and kate has a previewer
    if " " in note and Path("/usr/bin/kate").exists():
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
        "/usr/bin/kate",
        "/usr/bin/kwrite",
        "/usr/bin/nvim-qt",
        "/usr/bin/gedit",
    ):
        if Path(opt).exists():
            return [opt, datapath]

    for opt in ("/usr/bin/nvim", "/usr/bin/vim", "/usr/bin/nano"):
        if Path(opt).exists():
            return ["/usr/bin/konsole", "-e", opt, datapath]

    return None


class Runner(dbus.service.Object):
    def __init__(self):
        # self.notes_dirs = []
        # notes_config = Path("~/.config/notes-krunner").expanduser()
        # with open(notes_config) as conf:
        #     for line in conf.readlines():
        #         self.notes_dirs += [line.rstrip()]
        self.notes_dirs = [Path("~/Sync-Now/Portable/notes").expanduser().as_posix()]
        dbus.service.Object.__init__(
            self,
            dbus.service.BusName(SERVICE, dbus.SessionBus()),
            OBJPATH,
        )

    @cache
    @dbus.service.method(IFACE, in_signature="s", out_signature="a(sssida{sv})")
    def Match(self, query: str):
        """This method is used to get the matches and it returns a list of tuples"""
        # NoMatch = 0, CompletionMatch = 10, PossibleMatch = 30, InformationalMatch = 50, HelperMatch = 70, ExactMatch = 100

        results: list[tuple[str, str, str, int, float, dict[str, str]]] = []

        if len(query) <= 2:
            return results

        pwd = Path.cwd()
        found = False

        lcquery: str = query.lower()
        # q(lcquery)
        hyphenated_lcq: str = lcquery.replace(" ", "-")
        # q(hyphenated_lcq)
        rfind1regex = str.join(".", ("\\b" + x + "\\b" for x in lcquery.split()))

        rfind2regex = str.join(".*", lcquery.split())

        # Tried to use results as a dict itself but the {'subtext': line} portion is not hashable :/
        seen: dict[str, float] = {}

        for ndir in self.notes_dirs:
            # q(ndir)
            os.chdir(pwd)
            os.chdir(ndir)

            if Path(".git").exists():
                grep_cmd = ["/usr/bin/git", "--no-pager", "grep"]
                find_cmd = ["/usr/bin/git", "ls-files"]
            else:
                grep_cmd = ["/usr/bin/git", "--no-pager", "grep", "--no-index"]
                find_cmd = ["/usr/bin/find", ".", "-type", "f"]
                # + [
                # f"--iname '*{fragment}*'" for fragment in query.split()
                # ]

            expr = find_cmd

            result = subprocess.run(expr, capture_output=True, check=False)
            for line in str.split(result.stdout.decode("UTF-8"), "\n"):
                # q(line)
                if (
                    line == ""
                    or ".obsidian/" in line
                    or "_attic/" in line
                    or ".trash" in line
                    or line.endswith("/tags")
                ):
                    continue
                with suppress(Exception):
                    if lcquery == line.lower().rsplit("/", 2)[1].rsplit(".", 2)[0] and (
                        (line not in seen) or seen[line] < 1.0
                    ):
                        seen[f"{ndir}|{line}"] = 1.0
                        found = True
                        continue
                    if re.match(rfind1regex, line, re.IGNORECASE):
                        seen[f"{ndir}|{line}"] = 0.99
                        found = True
                        continue
                    if lcquery in line.lower() and (
                        (line not in seen) or seen[line] < 1.0
                    ):
                        seen[f"{ndir}|{line}"] = 0.98
                        found = True
                        continue
                    if re.match(rfind2regex, line, re.IGNORECASE):
                        seen[f"{ndir}|{line}"] = 0.98
                        found = True
                        continue

            # All expressions word match
            expr = grep_cmd + ["-l", "-i"]

            for fragment in query.split():
                expr += ["-e"]
                expr += [r"\b" + fragment + r"\b"]
                expr += ["--and"]
            if expr[-1] == "--and":
                expr = expr[0:-1]

            result = subprocess.run(expr, capture_output=True, check=False)
            for line in str.split(result.stdout.decode("UTF-8"), "\n"):
                if line != "" and ".obsidian/" not in line:
                    if lcquery in line.lower() and (
                        (line not in seen) or (seen[line] < 0.98)
                    ):
                        seen[f"{ndir}|{line}"] = 0.98
                        found = True
                        continue
                    if line not in seen:
                        found = True
                        seen[f"{ndir}|{line}"] = 0.97

            # All expressions non-word match
            expr = grep_cmd + ["-l", "-i"]
            for fragment in query.split():
                expr += ["-e"]
                expr += [r"\b" + fragment]
                expr += ["--and"]
            if expr[-1] == "--and":
                expr = expr[0:-1]

            result = subprocess.run(expr, capture_output=True, check=False)
            for line in str.split(result.stdout.decode("UTF-8"), "\n"):
                if line != "" and ".obsidian/" not in line:
                    if lcquery in line.lower() and (
                        (line not in seen) or (seen[line] < 0.96)
                    ):
                        seen[f"{ndir}|{line}"] = 0.96
                        found = True
                        continue
                    if line not in seen:
                        seen[f"{ndir}|{line}"] = 0.95
                        found = True

            # All expressions non-word match
            expr = grep_cmd + ["-l", "-i"]
            for fragment in query.split():
                expr += ["-e"]
                expr += [fragment + r"\b"]
                expr += ["--and"]
            if expr[-1] == "--and":
                expr = expr[0:-1]

            result = subprocess.run(expr, capture_output=True, check=False)
            for line in str.split(result.stdout.decode("UTF-8"), "\n"):
                if line != "" and ".obsidian/" not in line:
                    if lcquery in line.lower() and (
                        (line not in seen) or (seen[line] < 0.94)
                    ):
                        seen[f"{ndir}|{line}"] = 0.94
                        found = True
                        continue
                    if line not in seen:
                        seen[f"{ndir}|{line}"] = 0.93
                        found = True

            # All expressions non-word match
            expr = grep_cmd + ["-l", "-i"]
            for fragment in query.split():
                expr += ["-e"]
                expr += [fragment]
                expr += ["--and"]
            if expr[-1] == "--and":
                expr = expr[0:-1]

            result = subprocess.run(expr, capture_output=True, check=False)
            for line in str.split(result.stdout.decode("UTF-8"), "\n"):
                if line != "" and ".obsidian/" not in line:
                    if lcquery in line.lower() and (
                        (line not in seen) or (seen[line] < 0.92)
                    ):
                        seen[f"{ndir}|{line}"] = 0.92
                        found = True
                        continue
                    if line not in seen:
                        seen[f"{ndir}|{line}"] = 0.91
                        found = True

        if not found:
            for ndir in self.notes_dirs:
                os.chdir(pwd)
                os.chdir(ndir)
                expr = ["agrepr", "-i", "-l", query]

                result = subprocess.run(expr, capture_output=True, check=False)
                for line in str.split(result.stdout.decode("UTF-8"), "\n"):
                    if line != "" and ".obsidian/" not in line:
                        if lcquery in line.lower() and (
                            (line not in seen) or (seen[line] < 0.90)
                        ):
                            seen[f"{ndir}|{line}"] = 0.90
                            continue
                        if line not in seen:
                            seen[f"{ndir}|{line}"] = 0.89

        for item, relevance in seen.items():
            # q(item, relevance)
            if "_attic/" in item:
                relevance = relevance - 0.05
            if ".stversions/" in item:
                relevance = relevance - 0.10
            # data, text, icon, type (Plasma::QueryType), relevance (0-1), properties (subtext, category and urls)
            results += [
                (
                    item,
                    item.rsplit("|")[-1],
                    "document-edit",
                    100,
                    relevance,
                    {"subtext": item},
                )
            ]

        for ndir in self.notes_dirs:
            has_file = False
            create_path = Path(ndir, hyphenated_lcq).as_posix() + ".md"
            for line in seen:
                if Path(*line.rsplit("|", 2)).as_posix() == create_path:
                    has_file = True
                    break

            # If a file with exact match was not found, provide a creation option
            if not has_file:
                # q(1)
                results += [
                    (
                        f"{ndir}|{hyphenated_lcq}.md",
                        f"Create {create_path}",
                        "document-edit",
                        100,
                        1.0,
                        {"subtext": hyphenated_lcq},  # XXX
                    )
                ]

        results.sort(key=lambda x: x[4], reverse=True)
        return results[:10]

    @dbus.service.method(IFACE, out_signature="a(sss)")
    def Actions(self):
        # pylint: enable=
        # id, text, icon
        return [("id", "Tooltip", "planetkde")]

    @dbus.service.method(IFACE, in_signature="ss")
    def Run(self, data: str, action_id: str):
        with suppress(Exception):
            opener = get_opener(data)
            if opener:
                _ = subprocess.Popen(opener).pid


# print(data, action_id)

runner = Runner()
loop = GLib.MainLoop()
loop.run()
