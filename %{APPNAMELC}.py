#!/usr/bin/python3

#import q
import os
from pathlib import Path
import subprocess

import psutil
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

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


def get_opener():
    if os.path.exists(os.path.expanduser(os.path.expandvars("~/.config/prefer_nvim"))):
        if os.path.exists("/usr/bin/nvim-qt"):
            if os.path.exists(os.environ["HOME"] + "/.local/bin/nvr"):
                return [os.environ["HOME"] + "/.local/bin/nvr", "--remote-tab"]
            return ["/usr/bin/nvim-qt"]

        if os.path.exists("/usr/bin/nvim") and os.path.exists("/usr/bin/konsole"):
            return ["/usr/bin/konsole", "-e", "/usr/bin/nvim"]

    if os.path.exists("/usr/bin/gvim"):
        return ["/usr/bin/gvim", "--remote-tab"]

    if os.path.exists("/usr/bin/nvim"):
        if os.path.exists(os.environ["HOME"] + "/.local/bin/nvr"):
            return ["/usr/bin/konsole", "-e", os.environ["HOME"] + "/.local/bin/nvr", "--remote-tab"]
        else:
            return ["/usr/bin/konsole", "-e", "/usr/bin/nvim"]
    if os.path.exists("/usr/bin/vim"):
        return ["/usr/bin/konsole", "-e", "/usr/bin/vim"]
    if os.path.exists("/usr/bin/kate"):
        return ["/usr/bin/kate"]
    if os.path.exists("/usr/bin/kwrite"):
        return ["/usr/bin/kwrite"]
    return ["/usr/bin/gedit"]


class Runner(dbus.service.Object):
    def __init__(self):
        #q("In Runner")
        notes_config = Path('~/.config/notes-krunner').expanduser()
        with open(notes_config) as conf:
            for line in conf.readlines():
                self.ndir = line.rstrip()
        #q(self.ndir)
        os.chdir(self.ndir)
        if os.path.exists('.git'):
            self.git_grep_cmd = ['/usr/bin/git', '--no-pager', 'grep']
            self.find_cmd = ['/usr/bin/git', 'ls-files', '--others']
        else:
            self.git_grep_cmd = ['/usr/bin/git', '--no-pager', 'grep', '--no-index']
            self.find_cmd = ['/usr/bin/find', '.', '-type', 'f']
        # q("In Runner at the end")
        dbus.service.Object.__init__(self, dbus.service.BusName("org.kde.%{APPNAMELC}", dbus.SessionBus()), OBJPATH)

    @dbus.service.method(IFACE, in_signature='s', out_signature='a(sssida{sv})')
    def Match(self, query: str):
        """This method is used to get the matches and it returns a list of tuples"""
        # TODO: NoMatch = 0, CompletionMatch = 10, PossibleMatch = 30, InformationalMatch = 50, HelperMatch = 70, ExactMatch = 100

        # q("In Match")
        create = f"{query}.md"
        # q(query)
        results = []
        if len(query) <= 2:
            return results

        lcquery = query.lower()

        seen = {}  # Tried to use results as a dict itself but the {'subtext': line} portion is not hashable :/
        # Exact match, ignorecase match
        expr = self.find_cmd
        result = subprocess.run(expr, capture_output=True, check=False)
        for line in str.split(result.stdout.decode("UTF-8"), "\n"):
            if line != "" and '.obsidian/' not in line:
                if lcquery == create.lower() and ((line not in seen) or seen[line] < 1.0):
                    seen[line] = 1.0
                    # q("1.0")
                    continue
                if lcquery in line.lower() and ((line not in seen) or seen[line] < 1.0):
                    seen[line] = 0.97
                    # q("0.97")
                    continue

        # All expressions word match
        expr = self.git_grep_cmd + ["-l", "-i"]

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
                    # q("0.95")
                    seen[line] = 0.95
                    continue
                if line not in seen:
                    # q("0.90")
                    seen[line] = 0.90

        # All expressions non-word match
        expr = self.git_grep_cmd + ["-l", "-i"]
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
                    # q("0.85")
                    seen[line] = 0.85
                    continue
                if line not in seen:
                    # q("0.80")
                    seen[line] = 0.80

        for item, score in seen.items():
            if '_attic/' in item:
                #q("Reducing score for " + item)
                score = score - 0.05
            # data, text, icon, type (Plasma::QueryType), relevance (0-1), properties (subtext, category and urls)
            results += [(self.ndir + "/" + item, item, "document-edit", int(score * 100), score, {'subtext': item})]

        # If a file with exact match was not found, provide a creation option
        has_file = any(line.lower() == create.lower() for line in seen)
        if not has_file:
            results += [(f"{self.ndir}/{create}", f"Create {create}", "document-edit", 85, 1.0, {'subtext': create})]

        # q("end of match")
        return results

    @dbus.service.method(IFACE, out_signature='a(sss)')
    def Actions(self):
        # pylint: enable=
        # id, text, icon
        return [("id", "Tooltip", "planetkde")]

    @dbus.service.method(IFACE, in_signature='ss')
    def Run(self, data: str, action_id: str):
        # q(os.environ["USER"])
        # q(data)  # Actually dbus.String() but a bunch of magic going on
        wraise = Path('~/bin/wraise').expanduser()
        opener = get_opener()
        try:
            # q("In Run")
            _ = subprocess.Popen(opener + [data]).pid
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
            # q(e)
            pass
        # try:
        #     for user in self.users:
        #         if user is not os.environ["USER"] and (
        #                 "/home/" + os.environ["USER"]) not in data:  # data is a dbus.String so need to do this thing
        #             otherpath = self.notesdirs_by_user[user] + data.removeprefix(
        #                 self.notesdirs_by_user[os.environ["USER"]])
        #             if os.path.exists(otherpath):
        #                 # q(otherpath + " exists")
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
        #             # else:
        #             # q(otherpath + " does not exist")
        # except Exception as e:
        #     # q(e)
        #     pass


# print(data, action_id)

runner = Runner()
loop = GLib.MainLoop()
loop.run()
