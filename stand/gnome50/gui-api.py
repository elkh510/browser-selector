#!/usr/bin/env python3
"""Checks the GTK and libadwaita names a source file uses against this system.

    gui-api.py FILE

Three passes over the text of FILE, with the typelibs of the installed GTK 4
and libadwaita:

    missing      Namespace.Name or Namespace.Name.member that is not there
    deprecated   the same, there but marked deprecated
    hint         .method( calls, keyword properties and signals whose name is
                 that of a deprecated method, property or signal of one of
                 the classes the file names, or of their ancestors and
                 interfaces. The receiver is not known, so this is a place to
                 look at, not a verdict: a run with `python3 -W always` and
                 G_ENABLE_DIAGNOSTIC=1 names the deprecated ones for real.

One line per finding, then `missing: N, deprecated: N, hints: N`. The exit
code is 1 when something is missing or deprecated.
"""

import re
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

MODULES = {"Adw": Adw, "Gdk": Gdk, "Gio": Gio, "GLib": GLib, "Gtk": Gtk}


def lineage(info):
    """The class, its ancestors and all their interfaces, as repository infos."""
    seen = []
    while info is not None:
        seen.append(info)
        seen += list(info.get_interfaces()) if hasattr(info, "get_interfaces") else []
        info = info.get_parent() if hasattr(info, "get_parent") else None
    return seen


def members(info, getter):
    return list(getattr(info, getter)()) if hasattr(info, getter) else []


def main(path):
    source = open(path, encoding="utf-8").read()
    repository = gi.Repository.get_default()
    missing, deprecated, classes = [], [], {}

    for namespace, name, member in sorted(set(re.findall(r"\b(Adw|Gdk|Gio|GLib|Gtk)\.(\w+)(?:\.(\w+))?", source))):
        full = f"{namespace}.{name}"
        if not hasattr(MODULES[namespace], name):
            missing.append(full)
            continue
        info = repository.find_by_name(namespace, name)
        if info is None:
            continue
        if info.is_deprecated():
            deprecated.append(full)
        if hasattr(info, "get_methods"):
            classes[full] = info
        if member:
            if not hasattr(getattr(MODULES[namespace], name), member):
                missing.append(f"{full}.{member}")
            method = info.find_method(member) if hasattr(info, "find_method") else None
            if method is not None and method.is_deprecated():
                deprecated.append(f"{full}.{member}")

    by_name = []
    old = {"method": {}, "property": {}, "signal": {}}
    for info in {id(i): i for full in classes.values() for i in lineage(full)}.values():
        owner = f"{info.get_namespace()}.{info.get_name()}"
        for kind, getter in (("method", "get_methods"), ("property", "get_properties"), ("signal", "get_signals")):
            for item in members(info, getter):
                if item.is_deprecated():
                    old[kind].setdefault(item.get_name(), owner)
    for name, owner in sorted(old["method"].items()):
        if re.search(rf"\.{re.escape(name)}\(", source):
            by_name.append(f"method .{name}( is deprecated in {owner}")
    for name, owner in sorted(old["property"].items()):
        word = name.replace("-", "_")
        if re.search(rf"[(,]\s*{word}=", source) or f"notify::{name}" in source:
            by_name.append(f"property {name} is deprecated in {owner}")
    for name, owner in sorted(old["signal"].items()):
        if re.search(rf"connect\(\"{re.escape(name)}\"", source):
            by_name.append(f"signal {name} is deprecated in {owner}")

    for label, found in (("missing", missing), ("deprecated", deprecated), ("hint", by_name)):
        for item in found:
            print(f"{label}: {item}")
    print(f"classes looked at: {len(classes)}")
    print(f"missing: {len(missing)}, deprecated: {len(deprecated)}, hints: {len(by_name)}")
    return 1 if missing or deprecated else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
