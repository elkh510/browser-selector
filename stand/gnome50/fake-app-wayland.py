#!/usr/bin/env python3
"""A fake application with a native Wayland window, for the GNOME 50 stand.

The Wayland twin of common/fake-app.py: a GTK 4 window that is a Wayland
client and nothing else, so no X11 window, no WM_CLASS and nothing xprop
could find. The rest is the same: a cgroup named like the systemd unit of
the application, CHROME_DESKTOP in the environment, and a link is opened
with `xdg-open URL` as a child process.

    fake-app-wayland.py --ctl DIR --app-id slack [--title TEXT]
                        [--unit app-slack-2382881.scope] [--desktop slack.desktop]

The application is driven through the FIFO DIR/ctl, one command per line:

    title TEXT      change the title of the window
    open-now URL    open the URL right away, focused or not
    quit

A Wayland client cannot take the focus by itself, so there is no `focus` and
no `open`: the scenario moves the focus through the shell (shell.py focus).
Every command leaves one line in DIR/events when it is done, `ready` is the
first one.
"""

import argparse
import os
import select
import subprocess
import sys
import time

OPEN_TIMEOUT = 20
MAP_TIMEOUT = 10


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ctl", required=True)
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--unit")
    parser.add_argument("--desktop")
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


class Window:
    """A top level Wayland window with the app id and the title of the real app."""

    def __init__(self, app_id, title):
        # Wayland or nothing: with an X11 fallback the window would quietly
        # become one more Xwayland client. The software renderer needs no GPU.
        # Both are put back after the start, a real app does not export them.
        saved = {name: os.environ.get(name) for name in ("GDK_BACKEND", "GSK_RENDERER")}
        os.environ["GDK_BACKEND"] = "wayland"
        os.environ["GSK_RENDERER"] = "cairo"

        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import GLib, Gtk

        # GTK takes the app id of its Wayland surfaces from the program name
        GLib.set_prgname(app_id)
        Gtk.init()
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

        self.context = GLib.MainContext.default()
        self.window = Gtk.Window(title=title)
        self.window.set_default_size(480, 160)
        self.window.present()
        self.backend = type(self.window.get_display()).__name__

        deadline = time.monotonic() + MAP_TIMEOUT
        while not self.window.get_mapped() and time.monotonic() < deadline:
            self.pump()
            time.sleep(0.02)
        self.pump()

    def pump(self):
        while self.context.pending():
            self.context.iteration(False)

    def set_title(self, title):
        self.window.set_title(title)
        self.pump()


class App:
    def __init__(self, args):
        self.ctl = args.ctl
        self.events = os.path.join(args.ctl, "events")
        self.window = Window(args.app_id, args.title)
        print(f"display backend: {self.window.backend}", flush=True)

    def event(self, text):
        with open(self.events, "a") as events:
            events.write(text + "\n")

    def open(self, url):
        child = subprocess.Popen(["xdg-open", url])
        deadline = time.monotonic() + OPEN_TIMEOUT
        while child.poll() is None and time.monotonic() < deadline:
            self.window.pump()
            time.sleep(0.02)
        if child.poll() is None:
            child.kill()
            self.event(f"error\txdg-open did not return\txdg_open_pid={child.pid}")
            return
        self.event(f"opened\trc={child.returncode}\txdg_open_pid={child.pid}")

    def handle(self, line):
        command, _, rest = line.partition(" ")
        if command == "title":
            self.window.set_title(rest)
            self.event("title")
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
    App(args).run()


if __name__ == "__main__":
    sys.exit(main())
