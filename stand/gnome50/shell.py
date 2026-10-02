#!/usr/bin/env python3
"""Asks the GNOME Shell under test, through org.gnome.Shell.Eval.

Eval answers only in unsafe mode, which unsafe-ext turns on. This is how the
stand moves the focus and how it learns which window really has it: from the
shell itself, not from X11 and not by assumption. It is also how a window is
driven: keys and clicks come from virtual devices of the seat, so they reach
a native Wayland window the way the keyboard and the mouse of a user do.

    shell.py eval CODE      evaluate JS inside the shell, print the result
    shell.py focused        the focused window, `none` when there is none
    shell.py windows        every window, one line each
    shell.py window TITLE   the window with this title, with more fields;
                            exit code 1 when there is none
    shell.py focus TITLE    give the focus to the window with this title and
                            wait until the shell names it as the focused one
    shell.py close TITLE    close the window the way the close button of the
                            shell does
    shell.py keys KEY...    press keys: 2, Return, Escape, Down, alt+f, ctrl+q
    shell.py type TEXT      type the text
    shell.py move X Y       move the pointer to a point of the screen
    shell.py click X Y      move it there and click the primary button
    shell.py pointer        where the pointer is: X Y
    shell.py attention      titles of the windows that asked for attention
                            instead of getting the focus, since the first call

A window is one tab separated line: client=x11 or wayland, id= the X11 window
id of an X11 client and - for a Wayland one, instance=, class=, title=.
`window` adds pid= (the process of the client), app= and app_name= (the
application the window tracker of the shell takes the window for, - when it
knows none), rect=x,y,width,height (the frame of the window on the screen)
and focused=yes or no.
"""

import json
import re
import sys
import time

from gi.repository import Gio, GLib

FOCUS_TIMEOUT = 10

DESCRIBE = """
const describe = w => {
    const app = imports.gi.Shell.WindowTracker.get_default().get_window_app(w);
    const rect = w.get_frame_rect();
    return {
        x11: w.get_client_type() === imports.gi.Meta.WindowClientType.X11,
        description: w.get_description(),
        instance: w.get_wm_class_instance(),
        cls: w.get_wm_class(),
        title: w.get_title(),
        pid: w.get_pid(),
        app: app && !app.is_window_backed() ? app.get_id() : null,
        app_name: app && !app.is_window_backed() ? app.get_name() : null,
        rect: [rect.x, rect.y, rect.width, rect.height],
        focused: global.display.focus_window === w,
    };
};
const windows = () => global.get_window_actors().map(a => a.meta_window);
"""

# One virtual keyboard and one virtual pointer of the seat, kept in the shell
DEVICES = """
const Clutter = imports.gi.Clutter;
const seat = global.stage.context.get_backend().get_default_seat();
const device = (name, type) => global[name] || (global[name] = seat.create_virtual_device(type));
const keyboard = () => device('_stand_keyboard', Clutter.InputDeviceType.KEYBOARD_DEVICE);
const pointer = () => device('_stand_pointer', Clutter.InputDeviceType.POINTER_DEVICE);
const now = () => imports.gi.GLib.get_monotonic_time();
"""

# X11 keysyms of the keys that are not a character, and of the modifiers
KEYSYMS = {
    "Return": 0xff0d, "Escape": 0xff1b, "Tab": 0xff09, "BackSpace": 0xff08, "space": 0x20,
    "Home": 0xff50, "Left": 0xff51, "Up": 0xff52, "Right": 0xff53, "Down": 0xff54, "End": 0xff57,
    "alt": 0xffe9, "ctrl": 0xffe3, "shift": 0xffe1,
}


def evaluate(code):
    """The value of the JS code, evaluated inside the shell."""
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    done, result = bus.call_sync(
        "org.gnome.Shell", "/org/gnome/Shell", "org.gnome.Shell", "Eval",
        GLib.Variant("(s)", (code,)), GLib.VariantType("(bs)"),
        Gio.DBusCallFlags.NONE, 5000, None,
    ).unpack()
    if not done:
        raise RuntimeError(result or "Eval refused: the shell is not in unsafe mode")
    return json.loads(result) if result else None


def line(window, more=False):
    if window is None:
        return "none"
    # The description of an X11 client starts with its window id, the one of
    # a Wayland client is a serial of the shell (W1, W2)
    xid = re.match(r"0x[0-9a-fA-F]+", window["description"] or "")
    fields = {
        "client": "x11" if window["x11"] else "wayland",
        "id": xid.group(0) if window["x11"] and xid else "-",
        "instance": window["instance"] or "",
        "class": window["cls"] or "",
        "title": window["title"] or "",
    }
    if more:
        fields.update({
            "pid": window["pid"],
            "app": window["app"] or "-",
            "app_name": window["app_name"] or "-",
            "rect": ",".join(str(number) for number in window["rect"]),
            "focused": "yes" if window["focused"] else "no",
        })
    return "\t".join(f"{key}={value}" for key, value in fields.items())


def focused():
    return evaluate(
        f"(() => {{ {DESCRIBE} const w = global.display.focus_window;"
        " return w ? describe(w) : null; })()"
    )


def titled(title):
    return evaluate(
        f"(() => {{ {DESCRIBE}"
        f" const w = windows().find(w => w.get_title() === {json.dumps(title)});"
        " return w ? describe(w) : null; })()"
    )


def focus(title):
    found = evaluate(
        f"(() => {{ {DESCRIBE}"
        f" const w = windows().find(w => w.get_title() === {json.dumps(title)});"
        " if (!w) return false;"
        " Main.activateWindow(w);"
        " return true; })()"
    )
    if not found:
        print(f"no window titled {title}", file=sys.stderr)
        return 1
    deadline = time.monotonic() + FOCUS_TIMEOUT
    while time.monotonic() < deadline:
        window = focused()
        if window and window["title"] == title:
            return 0
        time.sleep(0.05)
    print(f"the focus did not go to {title}, it is on: {line(focused())}", file=sys.stderr)
    return 1


def keysym(name):
    if name in KEYSYMS:
        return KEYSYMS[name]
    if len(name) != 1:
        raise ValueError(f"no such key: {name}")
    # Latin-1 has its code points as keysyms, the rest of Unicode sits at 0x01000000
    return ord(name) if ord(name) < 0x100 else 0x01000000 | ord(name)


def key(name, pressed):
    state = "PRESSED" if pressed else "RELEASED"
    evaluate(f"(() => {{ {DEVICES} keyboard().notify_keyval(now(), {keysym(name)},"
             f" Clutter.KeyState.{state}); }})()")
    time.sleep(0.02)


def stroke(combination):
    """alt+f: the modifiers go down, the key is pressed and released, the modifiers go up."""
    *modifiers, name = combination.split("+") if len(combination) > 1 else [combination]
    for modifier in modifiers:
        key(modifier, True)
    key(name, True)
    key(name, False)
    for modifier in reversed(modifiers):
        key(modifier, False)
    time.sleep(0.05)


def move(x, y):
    evaluate(f"(() => {{ {DEVICES} pointer().notify_absolute_motion(now(), {x}, {y}); }})()")
    time.sleep(0.3)


def click(x, y):
    move(x, y)
    for state in ("PRESSED", "RELEASED"):
        evaluate(f"(() => {{ {DEVICES} pointer().notify_button(now(), Clutter.BUTTON_PRIMARY,"
                 f" Clutter.ButtonState.{state}); }})()")
        time.sleep(0.1)


def attention():
    """Titles of the windows the shell marked instead of focusing them.

    The shell shows its "... is ready" notification for exactly these two
    signals. The first call starts the watch.
    """
    return evaluate(
        "(() => { if (!global._stand_attention) { global._stand_attention = [];"
        " for (const signal of ['window-demands-attention', 'window-marked-urgent'])"
        " global.display.connect(signal, (display, w) => global._stand_attention.push(w.get_title())); }"
        " return global._stand_attention; })()"
    )


def main(argv):
    command, args = (argv[0] if argv else ""), argv[1:]
    if command == "eval" and len(args) == 1:
        print(json.dumps(evaluate(args[0])))
    elif command == "focused" and not args:
        print(line(focused()))
    elif command == "windows" and not args:
        for window in evaluate(f"(() => {{ {DESCRIBE} return windows().map(describe); }})()"):
            print(line(window))
    elif command == "window" and len(args) == 1:
        window = titled(args[0])
        if window is None:
            return 1
        print(line(window, more=True))
    elif command == "focus" and len(args) == 1:
        return focus(args[0])
    elif command == "close" and len(args) == 1:
        evaluate(
            f"(() => {{ {DESCRIBE}"
            f" const w = windows().find(w => w.get_title() === {json.dumps(args[0])});"
            " if (w) w.delete(global.get_current_time()); })()"
        )
    elif command == "keys" and args:
        for combination in args:
            stroke(combination)
    elif command == "type" and len(args) == 1:
        for char in args[0]:
            stroke("space" if char == " " else char)
    elif command == "move" and len(args) == 2:
        move(int(args[0]), int(args[1]))
    elif command == "click" and len(args) == 2:
        click(int(args[0]), int(args[1]))
    elif command == "pointer" and not args:
        print(*evaluate("global.get_pointer().slice(0, 2)"))
    elif command == "attention" and not args:
        for title in attention():
            print(title)
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
