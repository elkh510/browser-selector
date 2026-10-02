#!/usr/bin/env python3
"""A fake application for the stand.

It looks like a real one from where the handler stands: a window with a given
WM_CLASS and title (or no window at all), a cgroup named like the systemd
unit of the application, CHROME_DESKTOP in the environment the way Chromium
and Electron export it. A link is opened the way a real application does it:
`xdg-open URL` as a child process.

    fake-app.py --ctl DIR [--instance slack --class Slack --title TEXT]
                [--unit app-slack-2382881.scope] [--desktop slack.desktop]
                [--no-display]

Without --class there is no window, with --no-display there is no DISPLAY in
the environment either. The application is driven through the FIFO DIR/ctl,
one command per line:

    title TEXT      change the title of the window
    focus           ask the window manager for the focus
    open URL        take the focus, wait until the window manager names the
                    window as the active one, then open the URL
    open-now URL    open the URL right away, focused or not
    quit

Every command leaves one line in DIR/events when it is done, `ready` is the
first one.
"""

import argparse
import os
import re
import select
import subprocess
import sys
import time

FOCUS_TIMEOUT = 10
OPEN_TIMEOUT = 20


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ctl", required=True)
    parser.add_argument("--instance")
    parser.add_argument("--class", dest="cls")
    parser.add_argument("--title", default="")
    parser.add_argument("--unit")
    parser.add_argument("--desktop")
    parser.add_argument("--no-display", action="store_true")
    return parser.parse_args()


def join_cgroup(unit, ctl):
    """Move this process into a cgroup with the name of a systemd unit."""
    if os.environ.get("CGROUP_MODE", "real") == "real":
        path = os.path.join(os.environ["CGROUP_APP_SLICE"], unit)
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "cgroup.procs"), "w") as procs:
            procs.write(str(os.getpid()))
        os.environ.pop("BROWSER_SELECTOR_CGROUP_FILE", None)
        return
    # No writable cgroup tree: the unit name reaches the handler through the
    # file the contract offers for this, inherited like the cgroup would be
    path = os.path.join(ctl, "cgroup")
    uid = os.getuid()
    with open(path, "w") as fake:
        fake.write(
            f"0::/user.slice/user-{uid}.slice/user@{uid}.service"
            f"/app.slice/{unit}\n"
        )
    os.environ["BROWSER_SELECTOR_CGROUP_FILE"] = path


def xprop(*args):
    result = subprocess.run(
        ["xprop", *args], capture_output=True, text=True, timeout=5
    )
    return result.stdout


class Window:
    """A top level window with the class and the title of the real app."""

    def __init__(self, instance, cls, title):
        import tkinter

        self.root = tkinter.Tk()
        self.root.withdraw()
        # WM_CLASS of a Tk toplevel is (its name, its class): the name of the
        # main window is derived from the class and cannot be chosen, the
        # name of a second toplevel can
        self.top = tkinter.Toplevel(self.root, name=instance, class_=cls)
        self.top.title(title)
        self.top.geometry("480x160")
        self.pump()

        # The window the window manager deals with is the wrapper Tk puts
        # around a toplevel: it carries WM_CLASS and the title. Tk leaves
        # _NET_WM_PID off it, which every real toolkit sets.
        tree = subprocess.run(
            ["xwininfo", "-id", str(self.top.winfo_id()), "-children"],
            capture_output=True, text=True, timeout=5,
        ).stdout
        self.id = int(re.search(r"Parent window id: (0x[0-9a-f]+)", tree).group(1), 16)
        xprop("-id", hex(self.id), "-f", "_NET_WM_PID", "32c",
              "-set", "_NET_WM_PID", str(os.getpid()))

    def pump(self):
        self.root.update()

    def set_title(self, title):
        self.top.title(title)
        self.pump()

    def is_active(self):
        """True when _NET_ACTIVE_WINDOW points at this window.

        The same question the handler asks, answered the same way.
        """
        match = re.search(r"window id # (0x[0-9a-f]+)", xprop("-root", "_NET_ACTIVE_WINDOW"))
        return bool(match) and int(match.group(1), 16) == self.id

    def focus(self):
        subprocess.run(["wmctrl", "-i", "-a", hex(self.id)], timeout=5)
        deadline = time.monotonic() + FOCUS_TIMEOUT
        while time.monotonic() < deadline:
            self.pump()
            if self.is_active():
                return True
            time.sleep(0.05)
        return False


class App:
    def __init__(self, args):
        self.ctl = args.ctl
        self.events = os.path.join(args.ctl, "events")
        self.window = None
        if args.cls:
            self.window = Window(args.instance or args.cls.lower(), args.cls, args.title)

    def event(self, text):
        with open(self.events, "a") as events:
            events.write(text + "\n")

    def open(self, url):
        child = subprocess.Popen(["xdg-open", url])
        deadline = time.monotonic() + OPEN_TIMEOUT
        while child.poll() is None and time.monotonic() < deadline:
            if self.window:
                self.window.pump()
            time.sleep(0.02)
        if child.poll() is None:
            child.kill()
            self.event(f"error\txdg-open did not return\txdg_open_pid={child.pid}")
            return
        self.event(f"opened\trc={child.returncode}\txdg_open_pid={child.pid}")

    def handle(self, line):
        command, _, rest = line.partition(" ")
        if command == "title" and self.window:
            self.window.set_title(rest)
            self.event("title")
        elif command == "focus" and self.window:
            self.event("focused" if self.window.focus() else "error\tno focus")
        elif command == "open":
            if self.window and not self.window.focus():
                self.event("error\tno focus, nothing opened")
                return True
            self.open(rest)
        elif command == "open-now":
            self.open(rest)
        elif command == "quit":
            return False
        else:
            self.event(f"error\tunknown command {command}")
        return True

    def run(self):
        # Read and write: the FIFO never reports end of file between two
        # commands, and the scenario never blocks on its write
        fifo = os.open(os.path.join(self.ctl, "ctl"), os.O_RDWR)
        self.event("ready")
        pending = b""
        while True:
            readable, _, _ = select.select([fifo], [], [], 0.05)
            if self.window:
                self.window.pump()
            if not readable:
                continue
            pending += os.read(fifo, 65536)
            while b"\n" in pending:
                line, _, pending = pending.partition(b"\n")
                if not self.handle(line.decode()):
                    return


def main():
    args = parse_args()
    if args.unit:
        join_cgroup(args.unit, args.ctl)
    if args.desktop:
        os.environ["CHROME_DESKTOP"] = args.desktop
    else:
        os.environ.pop("CHROME_DESKTOP", None)
    # An application without a display, as started from a tty or a service:
    # the handler inherits that environment
    if args.no_display:
        os.environ.pop("DISPLAY", None)
    App(args).run()


if __name__ == "__main__":
    main()
