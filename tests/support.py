"""Shared by the tests: the module under test and a runner for the handler."""

import contextlib
import io
import os
import signal
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import browser_selector as bs  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
PROGRAMS = ("google-chrome", "brave-browser", "firefox", "chromium")
CGROUP = "0::/user.slice/user-1000.slice/user@1000.service/app.slice/{}\n"
SLACK = CGROUP.format("app-slack-2382881.scope")
NETBIRD = CGROUP.format("app-gnome-netbird-14016.scope")
URL = "https://example.com/x"

CONFIG = r"""
[settings]
default = chrome-main

[browser chrome-main]
command = google-chrome --profile-directory="Profile 6"

[browser chrome-work]
command = google-chrome --profile-directory="Profile 9"

[browser brave-globex]
command = brave-browser --profile-directory=Default {url}

[rule cloudflare]
url = ^https://acme\.cloudflareaccess\.com/
browser = chrome-work

[rule slack-acme]
app = slack
title = - Acme - Slack$
browser = chrome-work

[rule slack-globex]
app = slack
probe = @slack-workspace
probe_match = ^Globex$
browser = brave-globex

[rule netbird-globex]
app = netbird
probe = netbird profile list
probe_match = ^globex\s+✓
browser = brave-globex
"""


def read(path):
    """Text of a file, empty when it is not there."""
    try:
        with open(path, encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        return ""


def write_script(path, text):
    """An executable script, for the fake programs the tests put on a PATH."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        file.write(text)
    os.chmod(path, 0o755)
    return path


class Blocked(BaseException):
    """The watchdog went off. Not an Exception: nothing in the handler may swallow it."""


def watchdog(case, seconds=10):
    """Fail the test when something in it blocks, on a FIFO for example."""
    def expired(*args):
        raise Blocked(f"still running after {seconds} s")

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(seconds)
    case.addCleanup(signal.alarm, 0)


class HandlerCase(unittest.TestCase):
    """Runs main() in a throwaway home with everything external replaced."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = directory.name
        self.home = os.path.join(self.tmp, "home")
        os.mkdir(self.home)
        self.env = {"HOME": self.home}
        self.started = []      # every argv handed to exec
        self.exec_envs = []    # and the environment it came with
        self.window_reads = 0
        self.probe_runs = []   # (command, timeout) of every probe that ran
        self.window_loads = 0  # how often the module with the windows was asked for
        self.picks = []        # (link, apps, browsers) of every picker shown

    def write_config(self, text, name="config.ini"):
        path = os.path.join(self.home, ".config", "browser-selector", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            file.write(text)
        return path

    @property
    def log_path(self):
        return os.path.join(self.home, ".local", "state", "browser-selector", "log")

    def log(self):
        return read(self.log_path)

    def handle(self, *argv, cgroup="", window=None, probes=None, programs=PROGRAMS, which=None,
               broken=(), exec_error=PermissionError(13, "Permission denied"), pick=None, settings=0):
        """Run the handler, return (exit code, stdout, stderr).

        window is what the window reader returns, probes maps a probe command
        to its stdout (an exception in either place is raised), programs is
        what `which` finds, broken are programs exec fails on with exec_error.
        pick is what the picker returns or raises, settings what the settings
        window returns or raises; GTK is never loaded.
        """
        case = self

        class Windows:
            @staticmethod
            def pick(link, apps, browsers):
                case.picks.append((link, apps, browsers))
                if isinstance(pick, Exception):
                    raise pick
                return pick

            @staticmethod
            def settings(path, env):
                if isinstance(settings, Exception):
                    raise settings
                return settings

        def windows():
            self.window_loads += 1
            return Windows

        def read_window(env):
            self.window_reads += 1
            if isinstance(window, Exception):
                raise window
            return window

        def run_probe(command, timeout, env):
            self.probe_runs.append((command, timeout))
            output = (probes or {}).get(command)
            if isinstance(output, Exception):
                raise output
            return output

        def execve(path, args, env):
            if path in broken:
                raise exec_error
            self.started.append(list(args))
            self.exec_envs.append(env)

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = bs.main(list(argv), env=self.env, cgroup_text=cgroup, read_window=read_window,
                           run_probe=run_probe, execve=execve, windows=windows,
                           which=which or (lambda program: program if program in programs else None))
        return code, out.getvalue(), err.getvalue()
