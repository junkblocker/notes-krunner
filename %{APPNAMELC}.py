#!/usr/bin/python3

#import q
import os
from pathlib import Path
import subprocess

import psutil
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

from typing import List

DBusGMainLoop(set_as_default=True)

OBJPATH = '/%{APPNAMELC}'

IFACE = "org.kde.krunner1"

# def findProcessInfoByName(processName):
#     # Here is the list of all the PIDs of all the running process
#     # whose name contains the given string processName
#     listOfProcessObjects = []
#     # Iterating over the all the running process
#     for proc in psutil.process_iter():
#         try:
#             pinfo = proc.as_dict(attrs=['pid', 'name', 'create_time'])
#             # Checking if process name contains the given name string.
#             if processName.lower() == pinfo['name'].lower():
#                 listOfProcessObjects.append(pinfo)
#         except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
#             pass
#     return listOfProcessObjects

# def processExists(processName):
#     return len(findProcessInfoByName(processName)) > 0


def get_openers(data: str, action_id: str) -> List[List[str]]:
    openers: List[List[str]] = [[
        'xdg-open', 'obsidian://open?vault=notes&file=' + os.path.basename(data.rsplit("|")[-1]).replace(' ', '%20')
    ]]

    data = data.replace("|", "/")
    if os.path.exists(os.path.expanduser(os.path.expandvars("~/.config/prefer_nvim"))):
        if os.path.exists("/usr/bin/nvim-qt"):
            if os.path.exists(os.environ["HOME"] + "/.local/bin/nvr"):
                openers += [[os.environ["HOME"] + "/.local/bin/nvr", "--remote-tab", data]]
            else:
                openers += [["/usr/bin/nvim-qt", data]]
        elif os.path.exists("/usr/bin/nvim") and os.path.exists("/usr/bin/konsole"):
            openers += [["/usr/bin/konsole", "-e", "/usr/bin/nvim", data]]
    elif os.path.exists("/usr/bin/gvim"):
        openers += [["/usr/bin/gvim", "--remote-tab", data]]
    elif os.path.exists("/usr/bin/nvim"):
        if os.path.exists(os.environ["HOME"] + "/.local/bin/nvr"):
            openers += [["/usr/bin/konsole", "-e", os.environ["HOME"] + "/.local/bin/nvr", "--remote-tab", data]]
        else:
            openers += [["/usr/bin/konsole", "-e", "/usr/bin/nvim", data]]
    elif os.path.exists("/usr/bin/vim"):
        openers += [["/usr/bin/konsole", "-e", "/usr/bin/vim", data]]
    elif os.path.exists("/usr/bin/kate"):
        openers += [["/usr/bin/kate", data]]
    elif os.path.exists("/usr/bin/kwrite"):
        openers += [["/usr/bin/kwrite", data]]
    else:
        openers += [["/usr/bin/gedit", data]]
    return openers


class Runner(dbus.service.Object):
    def __init__(self):
        self.notes_dirs = []
        notes_config = Path('~/.config/notes-krunner').expanduser()
        with open(notes_config) as conf:
            for line in conf.readlines():
                self.notes_dirs += [line.rstrip()]
        dbus.service.Object.__init__(self, dbus.service.BusName("org.kde.%{APPNAMELC}", dbus.SessionBus()), OBJPATH)

    @dbus.service.method(IFACE, in_signature='s', out_signature='a(sssida{sv})')
    def Match(self, query: str):
        """This method is used to get the matches and it returns a list of tuples"""
        # TODO: NoMatch = 0, CompletionMatch = 10, PossibleMatch = 30, InformationalMatch = 50, HelperMatch = 70, ExactMatch = 100

        seen = {}  # Tried to use results as a dict itself but the {'subtext': line} portion is not hashable :/
        results = []

        pwd = os.getcwd()
        for ndir in self.notes_dirs:
            os.chdir(pwd)
            os.chdir(ndir)
            if os.path.exists('.git'):
                git_grep_cmd = ['/usr/bin/git', '--no-pager', 'grep']
                find_cmd = ['/usr/bin/git', 'ls-files', '--others']
            else:
                git_grep_cmd = ['/usr/bin/git', '--no-pager', 'grep', '--no-index']
                find_cmd = ['/usr/bin/find', '.', '-type', 'f']
            create = f"{ndir}/{query}.md"
            if len(query) <= 2:
                return results

            lcquery = query.lower()

            # Exact match, ignorecase match
            expr = find_cmd
            result = subprocess.run(expr, capture_output=True, check=False)
            for line in str.split(result.stdout.decode("UTF-8"), "\n"):
                if line != "" and '.obsidian/' not in line:
                    if lcquery == create.lower() and ((line not in seen) or seen[line] < 1.0):
                        seen[f"{ndir}|{line}"] = 1.0
                        continue
                    if lcquery in line.lower() and ((line not in seen) or seen[line] < 1.0):
                        seen[f"{ndir}|{line}"] = 0.97
                        continue

            # All expressions word match
            expr = git_grep_cmd + ["-l", "-i"]

            for fragment in query.split():
                expr += ["-e"]
                expr += [r'\b' + fragment + r'\b']
                expr += ["--and"]
            if expr[-1] == "--and":
                expr = expr[0:-1]

            result = subprocess.run(expr, capture_output=True, check=False)
            for line in str.split(result.stdout.decode("UTF-8"), "\n"):
                if line != "" and '.obsidian/' not in line:
                    if lcquery in line.lower() and ((line not in seen) or (seen[line] < 0.95)):
                        seen[f"{ndir}|{line}"] = 0.95
                        continue
                    if line not in seen:
                        seen[f"{ndir}|{line}"] = 0.90

            # All expressions non-word match
            expr = git_grep_cmd + ["-l", "-i"]
            for fragment in query.split():
                expr += ["-e"]
                expr += [fragment]
                expr += ["--and"]
            if expr[-1] == "--and":
                expr = expr[0:-1]

            result = subprocess.run(expr, capture_output=True, check=False)
            for line in str.split(result.stdout.decode("UTF-8"), "\n"):
                if line != "" and ".obsidian/" not in line:
                    if lcquery in line.lower() and ((line not in seen) or (seen[line] < 0.85)):
                        seen[f"{ndir}|{line}"] = 0.85
                        continue
                    if line not in seen:
                        seen[f"{ndir}|{line}"] = 0.80

        for item, score in seen.items():
            if '_attic/' in item:
                score = score - 0.05
            # data, text, icon, type (Plasma::QueryType), relevance (0-1), properties (subtext, category and urls)
            results += [(item, item.rsplit("|")[-1], "document-edit", int(score * 100), score, {'subtext': item})]

        # If a file with exact match was not found, provide a creation option
        has_file = any(line.lower().endswith(f"/{create.lower()}") for line in seen)
        if not has_file:
            results += [(f"{ndir}/{create}", f"Create {ndir}/{create}", "document-edit", 85, 1.0, {'subtext': create})]

        return results

    @dbus.service.method(IFACE, out_signature='a(sss)')
    def Actions(self):
        # pylint: enable=
        # id, text, icon
        return [("id", "Tooltip", "planetkde")]

    @dbus.service.method(IFACE, in_signature='ss')
    def Run(self, data: str, action_id: str):
        wraise = Path('~/bin/wraise').expanduser()
        for opener in get_openers(data, action_id):
            try:
                _ = subprocess.Popen(opener).pid
                if wraise.exists():
                    _ = subprocess.Popen([wraise, '-f', 'gvim']).pid
                elif os.environ["XDG_SESSION_TYPE"] == "x11":
                    result = subprocess.run(['/usr/bin/xdotool', 'search', '--classname', 'gvim'],
                                            check=False,
                                            capture_output=True)
                    for line in str.split(result.stdout.decode("UTF-8"), "\n"):
                        if line != "":
                            _ = subprocess.Popen(['xdotool', 'windowactivate', line]).pid
            except Exception as e:
                pass
            # try:
            #     for user in self.users:
            #         if user is not os.environ["USER"] and (
            #                 "/home/" + os.environ["USER"]) not in data:  # data is a dbus.String so need to do this thing
            #             otherpath = self.notesdirs_by_user[user] + data.removeprefix(
            #                 self.notesdirs_by_user[os.environ["USER"]])
            #             if os.path.exists(otherpath):
            #                 _ = subprocess.Popen(opener + [otherpath]).pid
            #                 if wraise.exists():
            #                     _ = subprocess.Popen([wraise, '-f', 'gvim']).pid
            #                 elif os.environ["XDG_SESSION_TYPE"] == "x11":
            #                     result = subprocess.run(['/usr/bin/xdotool', 'search', '--classname', 'gvim'],
            #                                             check=False,
            #                                             capture_output=True)
            #                     for line in str.split(result.stdout.decode("UTF-8"), "\n"):
            #                         if line != "":
            #                             _ = subprocess.Popen(['xdotool', 'windowactivate', line]).pid
            # except Exception as e:
            #     pass


# print(data, action_id)

runner = Runner()
loop = GLib.MainLoop()
loop.run()
