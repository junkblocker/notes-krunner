#!/usr/bin/python3
"""A Plasma runner."""
# import q
import os
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import Dict, List

import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

DBusGMainLoop(set_as_default=True)

OBJPATH = "/%{APPNAMELC}"
IFACE = "org.kde.krunner1"
SERVICE = "org.kde.%{APPNAMELC}"


def get_openers(data: str, action_id: str) -> List[List[str]]:
    openers: List[List[str]] = [[]]

    (vault, note) = data.rsplit("|")
    datapath = str(Path(vault, note))

    if (
        Path("/var/lib/flatpak/app/md.obsidian.Obsidian").exists()
        or Path(os.environ["HOME"] + "/Applications/Obsidian.AppImage").exists()
    ):
        if Path(vault, note).exists():
            openers = [
                [
                    "xdg-open",
                    "obsidian://open?vault=notes&file=" + note.replace(" ", "%20"),
                ]
            ]
        else:
            openers = [
                [
                    "xdg-open",
                    "obsidian://new?vault=notes&file=" + note.replace(" ", "%20"),
                ]
            ]
        return openers

    if Path(os.path.expanduser(os.path.expandvars("~/.config/prefer_nvim"))).exists():
        if Path("/usr/bin/nvim-qt").exists():
            if Path(os.environ["HOME"] + "/.local/bin/nvr").exists():
                openers += [
                    [os.environ["HOME"] + "/.local/bin/nvr", "--remote-tab", datapath]
                ]
            else:
                openers += [["/usr/bin/nvim-qt", datapath]]
        elif Path("/usr/bin/nvim").exists() and Path("/usr/bin/konsole").exists():
            openers += [["/usr/bin/konsole", "-e", "/usr/bin/nvim", datapath]]
    # elif Path("/usr/bin/gvim").exists():
    #     openers += [["/usr/bin/gvim", "--remote-tab", datapath]]
    elif Path("/usr/bin/nvim").exists():
        if Path(os.environ["HOME"] + "/.local/bin/nvr").exists():
            openers += [
                [
                    "/usr/bin/konsole",
                    "-e",
                    os.environ["HOME"] + "/.local/bin/nvr",
                    "--remote-tab",
                    datapath,
                ]
            ]
        else:
            openers += [["/usr/bin/konsole", "-e", "/usr/bin/nvim", datapath]]
    elif Path("/usr/bin/vim").exists():
        openers += [["/usr/bin/konsole", "-e", "/usr/bin/vim", datapath]]
    elif Path("/usr/bin/kate").exists():
        openers += [["/usr/bin/kate", datapath]]
    elif Path("/usr/bin/kwrite").exists():
        openers += [["/usr/bin/kwrite", datapath]]
    else:
        openers += [["/usr/bin/gedit", datapath]]
    return openers


class Runner(dbus.service.Object):
    def __init__(self):
        self.notes_dirs = []
        notes_config = Path("~/.config/notes-krunner").expanduser()
        with open(notes_config) as conf:
            for line in conf.readlines():
                self.notes_dirs += [line.rstrip()]
        dbus.service.Object.__init__(
            self,
            dbus.service.BusName(SERVICE, dbus.SessionBus()),
            OBJPATH,
        )

    @dbus.service.method(IFACE, in_signature="s", out_signature="a(sssida{sv})")
    def Match(self, query: str):
        """This method is used to get the matches and it returns a list of tuples"""
        # TODO: NoMatch = 0, CompletionMatch = 10, PossibleMatch = 30, InformationalMatch = 50, HelperMatch = 70, ExactMatch = 100

        # Tried to use results as a dict itself but the {'subtext': line} portion is not hashable :/
        seen: Dict[str, float] = {}
        results = []

        pwd = Path.cwd()
        found = False

        processing = 0
        for ndir in self.notes_dirs:
            processing += 1
            os.chdir(pwd)
            os.chdir(ndir)
            if Path(".git").exists():
                grep_cmd = ["/usr/bin/git", "--no-pager", "grep"]
                find_cmd = ["/usr/bin/git", "ls-files"]
            else:
                grep_cmd = ["/usr/bin/git", "--no-pager", "grep", "--no-index"]
                find_cmd = ["/usr/bin/find", ".", "-type", "f"]
            create = f"{ndir}/{query}.md"
            if len(query) <= 2:
                return results

            lcquery = query.lower()

            # Exact match, ignorecase match
            expr = find_cmd
            result = subprocess.run(expr, capture_output=True, check=False)
            for line in str.split(result.stdout.decode("UTF-8"), "\n"):
                if line != "" and ".obsidian/" not in line:
                    if lcquery == create.lower() and (
                        (line not in seen) or seen[line] < 1.0
                    ):
                        seen[f"{ndir}|{line}"] = 1.0
                        found = True
                        continue
                    if lcquery in line.lower() and (
                        (line not in seen) or seen[line] < 1.0
                    ):
                        seen[f"{ndir}|{line}"] = 0.97
                        found = True
                        continue

            # We already have enough good results
            if len(seen.keys()) >= processing * 10:
                # q("enough")
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
                        (line not in seen) or (seen[line] < 0.95)
                    ):
                        seen[f"{ndir}|{line}"] = 0.95
                        found = True
                        continue
                    if line not in seen:
                        found = True
                        seen[f"{ndir}|{line}"] = 0.93

            # We already have enough good results
            if len(seen.keys()) >= processing * 10:
                # q("enough")
                continue

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
                        (line not in seen) or (seen[line] < 0.90)
                    ):
                        seen[f"{ndir}|{line}"] = 0.90
                        found = True
                        continue
                    if line not in seen:
                        seen[f"{ndir}|{line}"] = 0.87
                        found = True

            # We already have enough good results
            if len(seen.keys()) >= processing * 10:
                # q("enough")
                break

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
                        (line not in seen) or (seen[line] < 0.85)
                    ):
                        seen[f"{ndir}|{line}"] = 0.85
                        found = True
                        continue
                    if line not in seen:
                        seen[f"{ndir}|{line}"] = 0.83
                        found = True

            # We already have enough good results
            if len(seen.keys()) >= processing * 10:
                # q("enough")
                break

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
                        (line not in seen) or (seen[line] < 0.80)
                    ):
                        seen[f"{ndir}|{line}"] = 0.80
                        found = True
                        continue
                    if line not in seen:
                        seen[f"{ndir}|{line}"] = 0.77
                        found = True

            # We already have enough good results
            if len(seen.keys()) >= processing * 10:
                # q("enough")
                break

        if not found:
            for ndir in self.notes_dirs:
                os.chdir(pwd)
                os.chdir(ndir)
                expr = ["agrepr", "-i", "-l", query]

                result = subprocess.run(expr, capture_output=True, check=False)
                for line in str.split(result.stdout.decode("UTF-8"), "\n"):
                    if line != "" and ".obsidian/" not in line:
                        if lcquery in line.lower() and (
                            (line not in seen) or (seen[line] < 0.75)
                        ):
                            seen[f"{ndir}|{line}"] = 0.75
                            continue
                        if line not in seen:
                            seen[f"{ndir}|{line}"] = 0.73

        for item, score in seen.items():
            if "_attic/" in item:
                score = score - 0.05
            if ".stversions/" in item:
                score = score - 0.10
            # data, text, icon, type (Plasma::QueryType), relevance (0-1), properties (subtext, category and urls)
            results += [
                (
                    item,
                    item.rsplit("|")[-1],
                    "document-edit",
                    int(score * 100),
                    score,
                    {"subtext": item},
                )
            ]

        # If a file with exact match was not found, provide a creation option
        has_file = any(line.lower().endswith(f"/{create.lower()}") for line in seen)
        if not has_file:
            for ndir in self.notes_dirs:
                create = f"{ndir}|{query}.md"
                results += [
                    (
                        f"{create}",
                        f"Create {ndir}/{query}.md",
                        "document-edit",
                        85,
                        1.0,
                        {"subtext": create},
                    )
                ]

        return results

    @dbus.service.method(IFACE, out_signature="a(sss)")
    def Actions(self):
        # pylint: enable=
        # id, text, icon
        return [("id", "Tooltip", "planetkde")]

    @dbus.service.method(IFACE, in_signature="ss")
    def Run(self, data: str, action_id: str):
        wraise = Path("~/bin/wraise").expanduser()
        openers = get_openers(data, action_id)
        for opener in openers:
            with suppress(Exception):
                _ = subprocess.Popen(opener).pid
                if wraise.exists():
                    _ = subprocess.Popen([wraise, "-f", "gvim"]).pid
                elif os.environ["XDG_SESSION_TYPE"] == "x11":
                    result = subprocess.run(
                        ["/usr/bin/xdotool", "search", "--classname", "gvim"],
                        check=False,
                        capture_output=True,
                    )
                    for line in str.split(result.stdout.decode("UTF-8"), "\n"):
                        if line != "":
                            _ = subprocess.Popen(
                                ["xdotool", "windowactivate", line]
                            ).pid


# print(data, action_id)

runner = Runner()
loop = GLib.MainLoop()
loop.run()
