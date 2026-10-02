#!/usr/bin/env python3
"""browser-selector: a default web browser that starts another one.

For every link it looks at who opened it (systemd unit, CHROME_DESKTOP), at
the focused window, the URL and probe commands, then execs the browser of the
first matching rule. The contract is docs/design.md. Discovery of browsers, the
config as the settings window edits it and everything else the windows need
without a window live here too, the contract is docs/design-gui.md.
"""

import configparser
import errno
import json
import os
import re
import select
import shlex
import shutil
import stat
import subprocess
import sys
import time
from urllib.parse import urlsplit

VERSION = "0.2.0"
USAGE = """\
usage: browser-selector [--config PATH] URL
       browser-selector [--config PATH] --explain [URL]
       browser-selector [--config PATH] --check
       browser-selector [--config PATH] --settings
       browser-selector [--config PATH] --init-config
       browser-selector --discover
       browser-selector --version"""

HANDLER = os.path.realpath(__file__)
LAST_RESORT = ("google-chrome", "brave-browser", "firefox", "chromium")
# Programs that hand the URL back to the default browser, which is this handler.
LOOPING = {"xdg-open", "gio", "gnome-open", "sensible-browser",
           "browser-selector", "browser_selector.py", os.path.basename(__file__)}
# The handler puts the time into this variable before it execs a browser. When
# it is started again within GUARD_SECONDS, a command led back to it.
GUARD = "BROWSER_SELECTOR_GUARD"
GUARD_SECONDS = 5
LOG_LIMIT = 1024 * 1024
PROBE_LIMIT = 64 * 1024
MAX_PROBE_TIMEOUT = 30
BUILTIN_PROBES = {"@slack-workspace"}
# The keys of every kind of section, in the order they are written in.
KEYS = {
    "settings": ("default", "probe_timeout"),
    "browser": ("name", "icon", "command"),
    "rule": ("app", "window", "title", "url", "probe", "probe_match", "browser"),
}
# Not a browser: the picker window asks which one.
ASK = "ask"
# What no name and no value of the config may hold: every line break of any reader (Python
# and GLib know more than the line feed), every control character but the tab, a lone surrogate.
UNWRITABLE = re.compile("[\x00-\x08\x0a-\x1f\x7f-\x9f\u2028\u2029\ud800-\udfff]")
ENTRY = "browser-selector.desktop"
OWN_ENTRIES = {ENTRY, "browser-selector-settings.desktop"}
REGEX_FLAGS = {"app": re.IGNORECASE, "window": re.IGNORECASE, "title": 0, "url": 0,
               "probe_match": re.MULTILINE}


def xdg_dir(env, variable, fallback):
    """An XDG base directory: the variable when it is an absolute path, else the fallback under HOME."""
    value = env.get(variable) or ""
    # The base directory specification: a relative path is to be taken as not set.
    return value if os.path.isabs(value) else os.path.join(env.get("HOME") or os.path.expanduser("~"), fallback)


def config_path(env, option):
    return (option or env.get("BROWSER_SELECTOR_CONFIG")
            or os.path.join(xdg_dir(env, "XDG_CONFIG_HOME", ".config"), "browser-selector", "config.ini"))


def read_file(path, encoding="utf-8", errors="strict", newline=None):
    """Text of a regular file. A FIFO or a device in its place would block the click."""
    if not stat.S_ISREG(os.stat(path).st_mode):
        raise OSError(errno.EINVAL, "not a regular file", path)
    with open(path, encoding=encoding, errors=errors, newline=newline) as file:
        return file.read()


def read_config(path):
    """Text of a config file: a line ends at a line feed, alone or after a carriage return.

    Nowhere else. Python would also end a line at a lone carriage return, and
    what is read back would not be what was validated before it was written.
    """
    return read_file(path, "utf-8-sig", newline="").replace("\r\n", "\n")


def printable(text):
    """Control characters, lone surrogates and the like as backslash escapes."""
    return "".join(char if char.isprintable() else char.encode("unicode_escape").decode("ascii")
                   for char in text)


def write_log(env, line):
    """Append one line to the log. Whatever goes wrong here, the click goes on."""
    try:
        directory = os.path.join(xdg_dir(env, "XDG_STATE_HOME", ".local/state"), "browser-selector")
        path = os.path.join(directory, "log")
        os.makedirs(directory, mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)
        if os.path.exists(path) and os.path.getsize(path) > LOG_LIMIT:
            os.replace(path, path + ".1")
        # O_NONBLOCK: a FIFO in place of the log fails here instead of waiting for a reader.
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NONBLOCK, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8", errors="backslashreplace") as file:
            os.fchmod(fd, 0o600)  # the umask or an older file may say otherwise
            file.write(printable(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {line}") + "\n")
    except Exception:
        pass


def url_origin(url):
    """Scheme and host only: everything else in a URL can carry a token."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return "-"
    return "".join(f"{parts.scheme}://{host}".split()) if parts.scheme and host else "-"


def guard_is_fresh(env):
    """True when the handler execed a browser a moment ago and is started again."""
    try:
        age = time.time() - float(env.get(GUARD, ""))
    except ValueError:
        return False
    return abs(age) < GUARD_SECONDS


# --- app: who opened the link ---

def cgroup_unit(text):
    """The systemd unit name from the text of /proc/self/cgroup, or None."""
    paths = {}
    for line in text.splitlines():
        fields = line.split(":", 2)
        if len(fields) == 3:
            paths[fields[1]] = fields[2]
    # cgroup v2 is the line without a controller, v1 keeps the units in name=systemd.
    path = paths.get("", paths.get("name=systemd", ""))
    return path.rstrip("/").rpartition("/")[2] or None


def unit_app_id(unit):
    """app-gnome-netbird-14016.scope -> netbird, app-slack@autostart.service -> slack"""
    name = re.sub(r"\.(scope|service)$", "", unit)
    name = name.partition("@")[0]
    name = re.sub(r"-\d+$", "", name)
    name = re.sub(r"^app-(gnome-|flatpak-)?", "", name)
    # Escapes are decoded last: an escaped dash belongs to the id, it separates nothing.
    raw = re.sub(rb"\\x([0-9a-fA-F]{2})", lambda found: bytes([int(found.group(1), 16)]), name.encode())
    return raw.decode(errors="replace")


def app_ids(unit, env):
    """Candidate app ids, from the unit name and from CHROME_DESKTOP."""
    ids = [unit_app_id(unit) if unit else "", env.get("CHROME_DESKTOP", "").removesuffix(".desktop")]
    return list(dict.fromkeys(app for app in ids if app))


# --- window and title: the focused X11 window ---

XPROP_ESCAPE = re.compile(r"(?P<octal>(?:\\[0-3][0-7]{2})+)|\\(?P<char>.)")


def xprop_unescape(found):
    if found.group("octal"):
        # Without a UTF-8 locale xprop prints every byte of a title as an octal escape.
        raw = bytes(int(code, 8) for code in found.group("octal").split("\\")[1:])
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1")
    return {"n": "\n", "t": "\t"}.get(found.group("char"), found.group("char"))


def xprop_strings(text, name):
    """The quoted strings of one property in xprop output; empty when it is not there."""
    found = re.search(rf"^{name}\(\w+\) = (.*)$", text, re.MULTILINE)
    if not found:
        return []
    return [XPROP_ESCAPE.sub(xprop_unescape, quoted)
            for quoted in re.findall(r'"((?:[^"\\]|\\.)*)"', found.group(1))]


def parse_active_window(text):
    """The window id from `xprop -root _NET_ACTIVE_WINDOW`, None for no window or 0x0."""
    found = re.search(r"window id # (0x[0-9a-fA-F]+)", text)
    return found.group(1) if found and int(found.group(1), 16) else None


def parse_window(text):
    """(classes, title) from the xprop output of one window, None without a class."""
    classes = [part for part in xprop_strings(text, "WM_CLASS") if part]
    if not classes:
        return None
    titles = xprop_strings(text, "_NET_WM_NAME") + xprop_strings(text, "WM_NAME")
    return classes, next((title for title in titles if title), "")


def read_window(env):
    """(classes, title) of the focused window, None when there is none."""
    if not env.get("DISPLAY"):
        return None

    def xprop(*args):
        return subprocess.run(
            ("xprop",) + args, env=dict(env, LC_ALL="C.UTF-8"), timeout=1, check=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            encoding="utf-8", errors="replace").stdout

    try:
        window = parse_active_window(xprop("-root", "_NET_ACTIVE_WINDOW"))
        if not window:
            return None
        return parse_window(xprop("-id", window, "WM_CLASS", "_NET_WM_NAME", "WM_NAME", "_NET_WM_PID"))
    except (OSError, subprocess.SubprocessError):
        return None


# --- probe ---

def slack_workspace(env):
    """Name of the selected workspace of the Slack desktop app, or None."""
    path = os.path.join(xdg_dir(env, "XDG_CONFIG_HOME", ".config"), "Slack", "storage", "root-state.json")
    try:
        state = json.loads(read_file(path))
        name = state["workspaces"][state["workspacesMeta"]["selectedWorkspaceId"]]["name"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return name if isinstance(name, str) else None


def run_probe(command, timeout, env):
    """Stdout of a probe, None when it fails, times out or is not found.

    At most PROBE_LIMIT bytes are read: a probe that says more is killed and
    judged by what it said so far.
    """
    if command == "@slack-workspace":
        return slack_workspace(env)
    try:
        process = subprocess.Popen(shlex.split(command), env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except (OSError, ValueError):
        return None
    deadline = time.monotonic() + timeout
    output = b""
    try:
        fd = process.stdout.fileno()
        while len(output) < PROBE_LIMIT:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                return None
            chunk = os.read(fd, PROBE_LIMIT - len(output))
            if not chunk:
                # End of output: now the exit status counts.
                if process.wait(max(deadline - time.monotonic(), 0)) != 0:
                    return None
                break
            output += chunk
        return output.decode("utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        process.kill()
        process.stdout.close()
        process.wait()


# --- config ---

def loops_back(argv, which):
    """The word of a command that leads back to the handler, None when there is none."""
    resolved = which(argv[0]) if which else None
    for word in argv + ([resolved] if resolved else []):
        if os.path.basename(word) in LOOPING or os.path.realpath(word) == HANDLER:
            return word
    return None


def parse_command(section, items, errors, which):
    command = items.get("command", "")
    if "\0" in command:
        errors.append(f"[{section}] command: has a NUL byte")
        return None
    try:
        argv = shlex.split(command)
    except ValueError as error:
        errors.append(f"[{section}] command: {error}")
        return None
    if not argv:
        errors.append(f"[{section}] command: missing")
        return None
    word = loops_back(argv, which)
    if word:
        errors.append(f"[{section}] command: {word} would loop back to the handler")
    return argv


def parse_rule(section, name, items, errors):
    rule = {"name": name, "browser": items.get("browser"), "probe": items.get("probe")}
    if not rule["browser"]:
        errors.append(f"[{section}] browser: missing")
    for key, flags in REGEX_FLAGS.items():
        rule[key] = None
        if key in items:
            try:
                rule[key] = re.compile(items[key], flags)
            except Exception as error:  # re.error, and OverflowError or RecursionError from odd patterns
                errors.append(f"[{section}] {key}: bad regex: {error or type(error).__name__}")
    if "probe" in items and "probe_match" not in items:
        errors.append(f"[{section}] probe_match: missing, probe needs it")
    if "probe_match" in items and "probe" not in items:
        errors.append(f"[{section}] probe: missing, probe_match needs it")
    if "probe" in items:
        probe = items["probe"]
        try:
            if probe.startswith("@") and probe not in BUILTIN_PROBES:
                errors.append(f"[{section}] probe: unknown built-in {probe}")
            elif not shlex.split(probe):
                errors.append(f"[{section}] probe: empty")
        except ValueError as error:
            errors.append(f"[{section}] probe: {error}")
    return rule


def ini_parser():
    # default_section="" turns [DEFAULT] into an ordinary, unknown section.
    parser = configparser.ConfigParser(interpolation=None, default_section="")
    parser.optionxform = str
    return parser


def parse_config(text, which=None):
    """Parse and validate the config text.

    Returns (config, errors). Every error names its section and key. The
    config is None when there are errors. With `which` the program of every
    command is resolved, to see whether it is the handler itself.
    """
    parser = ini_parser()
    try:
        parser.read_string(text, source="config")
    except configparser.Error as error:
        return None, [" ".join(str(error).split())]

    errors = []
    settings, browsers, shown, rules = {}, {}, {}, []
    seen = set()
    for section in parser.sections():
        kind, _, name = section.partition(" ")
        name = name.strip()
        if kind not in KEYS or bool(name) == (kind == "settings"):
            errors.append(f"[{section}]: unknown section")
            continue
        if (kind, name) in seen:
            # [rule x] and [rule  x]: two sections for configparser, one name here.
            errors.append(f"[{section}]: a second section of this name")
            continue
        seen.add((kind, name))
        items = dict(parser[section])
        errors += [f"[{section}] {key}: unknown key" for key in items if key not in KEYS[kind]]
        if kind == "settings":
            settings = items
        elif kind == "browser":
            if name == ASK:
                errors.append(f"[{section}]: {ASK} is a reserved name")
            browsers[name] = parse_command(section, items, errors, which)
            shown[name] = (items.get("name") or name, items.get("icon") or "")
        else:
            rules.append(parse_rule(section, name, items, errors))

    default = settings.get("default")
    if not default:
        errors.append("[settings] default: missing")
    elif default != ASK and default not in browsers:
        errors.append(f"[settings] default: browser {default} is not defined")
    try:
        timeout = float(settings.get("probe_timeout", 2))
        if not 0 < timeout <= MAX_PROBE_TIMEOUT:
            raise ValueError
    except ValueError:
        errors.append(f"[settings] probe_timeout: not a number of seconds from 0 to {MAX_PROBE_TIMEOUT}")
    for rule in rules:
        if rule["browser"] and rule["browser"] != ASK and rule["browser"] not in browsers:
            errors.append(f"[rule {rule['name']}] browser: browser {rule['browser']} is not defined")

    if errors:
        return None, errors
    return {"default": default, "probe_timeout": timeout, "browsers": browsers, "shown": shown, "rules": rules}, []


def load_config(path, which=None):
    """(config, errors) of the file; (None, []) when there is no file. Never raises."""
    try:
        return parse_config(read_config(path), which)
    except FileNotFoundError:
        return None, []
    except Exception as error:
        return None, [f"config: {type(error).__name__}: {error}"]


# --- decision ---

def rule_matches(rule, url, apps, window, probe):
    """Check the conditions of a rule, cheapest first.

    window() returns (classes, title) or None, probe(command) returns stdout
    or None. Both are called only when the cheaper conditions hold.
    """
    if rule["url"] and not rule["url"].search(url):
        return False
    if rule["app"] and not any(rule["app"].fullmatch(app) for app in apps):
        return False
    if rule["window"] or rule["title"]:
        seen = window()
        if seen is None:
            return False
        classes, title = seen
        if rule["window"] and not any(rule["window"].fullmatch(part) for part in classes):
            return False
        if rule["title"] and not rule["title"].search(title):
            return False
    if rule["probe"]:
        output = probe(rule["probe"])
        if output is None or not rule["probe_match"].search(output):
            return False
    return True


def build_command(argv, url):
    if any("{url}" in arg for arg in argv):
        return [arg.replace("{url}", url) for arg in argv]
    return argv + [url]


def commands(config, rule, url, which, note):
    """What to start, in the order to try: [(browser name or None, program path, argv)].

    The browser of the rule, the default browser, then the last resort; only
    programs that exist and are not the handler itself. `ask` is no command.
    """
    wanted = []
    if config:
        names = ([rule["browser"]] if rule else []) + [config["default"]]
        wanted = [(name, build_command(config["browsers"][name], url))
                  for name in dict.fromkeys(names) if name != ASK]
    wanted += [(None, [program, url]) for program in LAST_RESORT]
    found = []
    for name, argv in wanted:
        path = which(argv[0])
        if path and os.path.realpath(path) == HANDLER:
            note(f"{argv[0]} is the handler itself, not started")
        elif path:
            found.append((name, path, argv))
        elif name:
            note(f"[browser {name}] command: {argv[0]} not found")
    return found


def decide(url, explain, config_file, env, cgroup_text, read_window, run_probe, which, note):
    """Everything before the exec: (config, unit, apps, window, probes, rule, commands to try)."""
    if cgroup_text is None:
        try:
            cgroup_text = read_file(env.get("BROWSER_SELECTOR_CGROUP_FILE") or "/proc/self/cgroup",
                                    errors="replace")
        except OSError:
            cgroup_text = ""
    unit = cgroup_unit(cgroup_text)
    apps = app_ids(unit, env)

    config = None
    if guard_is_fresh(env):
        note("started again right after starting a browser, a command leads back to the handler: "
             "the rules are skipped")
    else:
        config, errors = load_config(config_file, which)
        for error in errors:
            note(error)
        if explain and config is None and not errors:
            note(f"{config_file}: no such file")

    windows = []  # the window once it is read, so it is read at most once
    probes = {}   # probe command -> stdout, so each probe runs once

    # A reader that breaks is a condition that is false: the next rule is tried.
    def window():
        if not windows:
            try:
                windows.append(read_window(env))
            except Exception as error:
                note(f"window: {type(error).__name__}")
                windows.append(None)
        return windows[0]

    def probe(command):
        if command not in probes:
            try:
                probes[command] = run_probe(command, config["probe_timeout"], env)
            except Exception as error:
                note(f"probe {command}: {type(error).__name__}")
                probes[command] = None
        return probes[command]

    rule = None
    if explain:
        window()
    if config and url is not None:
        rule = next((r for r in config["rules"] if rule_matches(r, url, apps, window, probe)), None)
    elif config:
        # --explain without a URL has no rule to follow: show every probe.
        for r in config["rules"]:
            if r["probe"]:
                probe(r["probe"])
    found = commands(config, rule, url, which, note) if url is not None else []
    return config, unit, apps, windows[0] if windows else None, probes, rule, found


def print_explain(url, unit, apps, seen, probes, rule, found, asks=False):
    classes, title = seen or (["-"], "-")
    lines = [f"url: {url}"] if url is not None else []
    lines += [f"unit: {unit or '-'}", f"app: {', '.join(apps) or '-'}",
              f"window: {', '.join(classes)}", f"title: {title}"]
    for command, output in probes.items():
        # One line per probe: the lines of the output are joined with " | ".
        shown = " | ".join(line.strip() for line in output.splitlines() if line.strip()) if output else ""
        lines.append(f"probe {command}: {shown or '-'}")
    if url is not None:
        name, _, argv = (ASK, None, None) if asks else found[0] if found else (None, None, None)
        lines += [f"rule: {rule['name'] if rule else '-'}", f"browser: {name or '-'}",
                  f"command: {shlex.join(argv) if argv else '-'}"]
    for line in lines:
        print(printable(line))


# --- the config as the settings window edits it ---
#
# A model is the config as raw strings in file order:
#   {"settings": {key: value}, "browsers": {name: {key: value}},
#    "rules": {name: {key: value}}, "unknown": {section: {key: value}}}
# An edit returns a new model and leaves the one it got alone.

def empty_model():
    return {"settings": {}, "browsers": {}, "rules": {}, "unknown": {}}


def copy_model(model):
    new = {kind: {name: dict(items) for name, items in model[kind].items()}
           for kind in ("browsers", "rules", "unknown")}
    return dict(new, settings=dict(model["settings"]))


def read_model(text):
    """The config text as a model, nothing validated. configparser.Error when it is not INI."""
    parser = ini_parser()
    parser.read_string(text, source="config")
    model = empty_model()
    seen = set()
    for section in parser.sections():
        kind, _, name = section.partition(" ")
        name = name.strip()
        known = (kind == "settings" and not name) or (kind in ("browser", "rule") and bool(name))
        if not known or (kind, name) in seen:
            # Kept as it is, a second spelling of a name too: a save names it instead of dropping it.
            model["unknown"][section] = dict(parser[section])
        elif kind == "settings":
            model["settings"] = dict(parser[section])
        else:
            model[kind + "s"][name] = dict(parser[section])
        seen.add((kind, name))
    return model


def model_sections(model):
    """[(section, items)] of a model the way they are written: settings, browsers, rules in their order."""
    sections = [("settings", model["settings"])] if model["settings"] else []
    sections += [(f"browser {name}", items) for name, items in model["browsers"].items()]
    sections += [(f"rule {name}", items) for name, items in model["rules"].items()]
    return sections + list(model["unknown"].items())


def render_model(model):
    """The model as INI text."""
    # A line break inside a value goes on as an indented line, as configparser reads it.
    return "\n".join(
        f"[{section}]\n" + "".join(f"{key} = {value}".rstrip().replace("\n", "\n\t") + "\n"
                                   for key, value in items.items())
        for section, items in model_sections(model))


def check_model(model, which=None):
    """The errors of a model, found by the code of --check. Empty when it can be written."""
    for section, items in model_sections(model):
        if UNWRITABLE.search(section):
            return [printable(f"[{section}]: the name has a line break or a control character")]
        for key, value in items.items():
            # The line feed of a value that goes on in the next line is the one that may stay.
            if UNWRITABLE.search(key + value.replace("\n", "")):
                return [printable(f"[{section}] {key}: has a line break or a control character")]
    text = render_model(model)
    try:
        written = read_model(text)
    except configparser.Error as error:
        return [" ".join(str(error).split())]
    # What is read back must be what was written: a name with a line break in it would not be.
    for kind, label in (("browsers", "browser "), ("rules", "rule "), ("unknown", "")):
        for name, items in model[kind].items():
            if written[kind].get(name) != items:
                return [f"[{label}{name}]: the name or a value cannot be written to an INI file"]
    if written["settings"] != model["settings"]:
        return ["[settings]: a value cannot be written to an INI file"]
    return parse_config(text, which)[1]


def write_text(path, text):
    """Replace a file through a temporary file and a rename: a reader sees the old text or the new."""
    path = os.path.realpath(path)  # a config that is a link into a dotfiles repo stays a link
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f"{path}.{os.getpid()}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(fd)
        if os.path.exists(path):
            os.chmod(temporary, stat.S_IMODE(os.stat(path).st_mode))
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def load_model(path):
    """(model, error) of the config file. An empty model when there is no file."""
    try:
        return read_model(read_config(path)), None
    except FileNotFoundError:
        return empty_model(), None
    except configparser.Error as error:
        return None, " ".join(str(error).split())
    except Exception as error:
        return None, f"config: {type(error).__name__}: {error}"


def save_model(path, model, which=None):
    """Write the model to the config file when it is valid. The errors, empty when it is written."""
    errors = check_model(model, which)
    if not errors:
        try:
            write_text(path, render_model(model))
        except (OSError, ValueError) as error:  # ValueError: a path or a text no file can take
            errors = [printable(f"{path}: {getattr(error, 'strerror', None) or error}")]
    return errors


def change_config(path, edit, which=None):
    """One edit of the config file: read, change, validate, write. Returns (model, errors).

    The file is read again for every edit, so what was changed by hand in the
    meantime is kept. With errors nothing is written and the model is None.
    """
    model, error = load_model(path)
    if error:
        return None, [error]
    try:
        model = edit(model)
    except ValueError as error:
        return None, [str(error)]
    errors = save_model(path, model, which)
    return (None, errors) if errors else (model, [])


def clean(items):
    """The fields of a form as the items of a section: no space around, nothing empty."""
    return {key: value.strip() for key, value in items.items() if value.strip()}


def put_section(kind, sections, name, items, old):
    """The sections with `name` added at the end, or in the place of `old`."""
    if not name:
        raise ValueError(f"[{kind}]: a name is needed")
    if name != old and name in sections:
        raise ValueError(f"[{kind} {name}]: there is one with this name already")
    if old is None:
        return {**sections, name: items}
    if old not in sections:
        raise ValueError(f"[{kind} {old}]: not in the config any more")
    for key in sections[old]:
        if key not in KEYS[kind]:
            # The form has no field for it and would drop it without a word.
            raise ValueError(f"[{kind} {old}] {key}: unknown key, mend the file by hand")
    return {name if key == old else key: items if key == old else value for key, value in sections.items()}


def with_browser(model, name, items, old=None):
    """A browser added, or `old` replaced by it; the default and the rules follow a new name."""
    new = copy_model(model)
    new["browsers"] = put_section("browser", new["browsers"], name, items, old)
    if old is not None and old != name:
        if new["settings"].get("default") == old:
            new["settings"]["default"] = name
        for rule in new["rules"].values():
            if rule.get("browser") == old:
                rule["browser"] = name
    # A config needs a default: the first browser of a new one is it.
    return new if new["settings"].get("default") else with_default(new, name)


def browser_users(model, name):
    """The places a browser is still named in: the default and the rules."""
    users = ["[settings] default"] if model["settings"].get("default") == name else []
    return users + [f"[rule {rule}]" for rule, items in model["rules"].items() if items.get("browser") == name]


def without_browser(model, name):
    users = browser_users(model, name)
    if users:
        raise ValueError(f"[browser {name}]: still used by {', '.join(users)}")
    new = copy_model(model)
    new["browsers"].pop(name, None)
    return new


def with_rule(model, name, items, old=None):
    """A rule added at the end, or `old` replaced by it in its place."""
    new = copy_model(model)
    new["rules"] = put_section("rule", new["rules"], name, items, old)
    return new


def without_rule(model, name):
    new = copy_model(model)
    new["rules"].pop(name, None)
    return new


def move_rule(model, name, step):
    """The rule one place up (step -1) or down (step 1); the same model at either end."""
    names = list(model["rules"])
    if name not in names:
        raise ValueError(f"[rule {name}]: not in the config any more")
    at = names.index(name)
    if not 0 <= at + step < len(names):
        return model
    names[at], names[at + step] = names[at + step], names[at]
    new = copy_model(model)
    new["rules"] = {rule: new["rules"][rule] for rule in names}
    return new


def with_default(model, name):
    new = copy_model(model)
    new["settings"] = {"default": name, **new["settings"], "default": name}
    return new


def command_key(command, which):
    """What a command starts, to tell whether two sections are the same browser."""
    try:
        argv = shlex.split(command)
    except ValueError:
        argv = []
    if not argv:
        return (command,)
    path = which(argv[0]) if which else None
    return (os.path.realpath(path) if path else argv[0], *argv[1:])


def browser_items(browser):
    """What discovery found about one browser as the items of its section."""
    return {key: browser[key] for key in KEYS["browser"] if browser[key]}


def with_discovered(model, found, which=None):
    """(model, names added): what discovery found and the config does not have yet.

    A section that is there is never changed or removed, whatever its name:
    a browser is there when a section starts the same program the same way.
    """
    new = copy_model(model)
    known = {command_key(items.get("command", ""), which) for items in new["browsers"].values()}
    added = []
    for browser in found:
        key = command_key(browser["command"], which)
        if key in known:
            continue
        known.add(key)
        name = unique_name(browser["section"], set(new["browsers"]) | {ASK})
        new["browsers"][name] = browser_items(browser)
        added.append(name)
    if added and not new["settings"].get("default"):
        new = with_default(new, added[0])
    return new, added


# --- discovery: the browsers and profiles of this home ---

SNAP_APPLICATIONS = "/var/lib/snapd/desktop/applications"
FLATPAK_APPLICATIONS = "/var/lib/flatpak/exports/share/applications"
# The Chromium family: name of the sections, programs, flatpak id, data
# directory under the config home, data directory of the snap under the home.
CHROMIUM_FAMILY = (
    ("chrome", ("google-chrome", "google-chrome-stable"), "com.google.Chrome", "google-chrome", None),
    ("brave", ("brave-browser", "brave-browser-stable", "brave"), "com.brave.Browser",
     "BraveSoftware/Brave-Browser", "snap/brave/current/.config/BraveSoftware/Brave-Browser"),
    ("chromium", ("chromium", "chromium-browser"), "org.chromium.Chromium", "chromium",
     "snap/chromium/common/chromium"),
    ("edge", ("microsoft-edge", "microsoft-edge-stable"), "com.microsoft.Edge", "microsoft-edge", None),
    ("vivaldi", ("vivaldi", "vivaldi-stable"), "com.vivaldi.Vivaldi", "vivaldi", None),
)
FIREFOX_PROGRAMS = ("firefox", "firefox-esr")
FIREFOX_FLATPAK = "org.mozilla.firefox"
PLAIN_WORD = re.compile(r"[\w@%+=:,./{}~^-]+")
DESKTOP_ESCAPES = {"s": " ", "n": "\n", "t": "\t", "r": "\r", "\\": "\\"}
FIELD_CODE = re.compile("%([%fFuUdDnNickvm])")


def slug(text):
    """Google Chrome -> google-chrome, acme -> acme"""
    return re.sub(r"[\W_]+", "-", text.lower()).strip("-")


def unique_name(name, taken):
    """The name, or the name with the first number that makes it a new one."""
    candidate, number = name, 1
    while candidate in taken:
        number += 1
        candidate = f"{name}-{number}"
    return candidate


def one_line(value):
    """A display name out of foreign data: one line of printable text, empty for anything else."""
    if not isinstance(value, str):
        return ""
    return " ".join("".join(char if char.isprintable() else " " for char in value).split())


def quote_word(word):
    """One word of a command, quoted the way the example config does it: --flag="two words"."""
    if PLAIN_WORD.fullmatch(word):
        return word
    flag, value = re.fullmatch(r"(-[\w-]*=)?(.*)", word, re.DOTALL).groups()
    return (flag or "") + '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def join_command(argv):
    """The opposite of shlex.split for a `command` of the config."""
    return " ".join(quote_word(word) for word in argv)


def application_dirs(env):
    """Where desktop entries live, the directory of the user first."""
    data = xdg_dir(env, "XDG_DATA_HOME", ".local/share")
    dirs = (env.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    dirs = [data] + [path for path in dirs if os.path.isabs(path)]
    dirs = [os.path.join(path, "applications") for path in dirs]
    dirs += [SNAP_APPLICATIONS, os.path.join(data, "flatpak", "exports", "share", "applications"),
             FLATPAK_APPLICATIONS]
    return list(dict.fromkeys(os.path.normpath(path) for path in dirs))


def read_desktop_entry(path):
    """The keys of the [Desktop Entry] group of a file, None when it cannot be read."""
    try:
        text = read_file(path, errors="replace", newline="")
    except OSError:
        return None
    entry, inside = {}, False
    # As GLib reads it: a line ends at a line feed and nowhere else, the space around is ASCII.
    for line in text.split("\n"):
        line = line.strip(" \t\r\f\v")
        if line.startswith("["):
            inside = line == "[Desktop Entry]"
        elif inside and "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            entry.setdefault(key.strip(" \t"), value.strip(" \t\r\f\v"))
    return entry


def split_exec(text):
    """Split an Exec line the way GLib does: [(word, plain)], ValueError for an open quote.

    Like a shell. Inside double quotes a backslash only takes the meaning
    from the four characters the Desktop Entry specification names. A word is
    plain when no quote and no backslash made it.
    """
    argv, word, plain, quote, at = [], None, True, None, 0
    while at < len(text):
        char = text[at]
        at += 1
        if quote is None and char in " \t\n":
            if word is not None:
                argv.append((word, plain))
            word, plain = None, True
            continue
        word = word or ""
        if quote == "'" and char != "'":
            word += char
        elif char == quote:
            quote = None
        elif quote is None and char in "'\"":
            quote, plain = char, False
        elif char == "\\" and at < len(text) and (quote is None or text[at] in '"`$\\'):
            word += text[at]
            at += 1
            plain = False
        else:
            word += char
    if quote:
        raise ValueError("a quote is not closed")
    return argv + ([(word, plain)] if word is not None else [])


def unusable(word):
    """Why a word of foreign data cannot be an argument of a `command`, None when it can."""
    if UNWRITABLE.search(word):
        return "it has a line break or a control character"
    if "{url}" in word:
        return "it has {url} in it, which is where the handler puts the link"
    return None


def exec_argv(value):
    """Exec of a desktop entry as the argv of a `command`. ValueError says why it cannot be one.

    A field code that is a word of its own goes, the handler adds the link at
    the end. In `--flag=%u` it becomes {url}. An entry with a code inside a
    quoted argument stays out: there the link would land in the text of a
    script, where GLib quotes it and the handler cannot.
    """
    text = re.sub(r"\\(.)", lambda found: DESKTOP_ESCAPES.get(found.group(1), found.group(0)), value)
    argv = []
    for word, plain in split_exec(text):
        reason = unusable(word)
        if reason:
            raise ValueError(reason)
        codes = FIELD_CODE.findall(word)
        if len(word) == 2 and codes and codes[0] != "%":
            continue
        if not plain and any(code in "fFuU" for code in codes):
            raise ValueError("it has a field code inside a quoted argument")
        argv.append(FIELD_CODE.sub(lambda found: {"%": "%", **dict.fromkeys("fFuU", "{url}")}.get(found.group(1), ""),
                                   word))
    # flatpak wraps the field code: `@@u %U @@`. Without it the pair is empty.
    for at in range(len(argv) - 1):
        if argv[at] in ("@@", "@@u") and argv[at + 1] == "@@":
            del argv[at:at + 2]
            break
    if not argv:
        raise ValueError("it has no command")
    return argv


def desktop_browser(path, which, note):
    """A desktop entry that opens http links, as a browser to look for profiles of. Else None."""
    entry = read_desktop_entry(path)
    if not entry or entry.get("Type", "Application") != "Application" or entry.get("Hidden") == "true":
        return None
    if "x-scheme-handler/http" not in entry.get("MimeType", "").split(";"):
        return None
    try:
        argv = exec_argv(entry.get("Exec", ""))
    except ValueError as error:
        note(f"{os.path.basename(path)} left out: {error}")
        return None
    if loops_back(argv, which):
        return None
    program = which(argv[0])
    if not program or (entry.get("TryExec") and not which(entry["TryExec"])):
        return None
    return {"key": (os.path.realpath(program), *argv[1:]), "argv": argv, "entries": [],
            "name": one_line(entry.get("Name")) or os.path.basename(argv[0]), "icon": one_line(entry.get("Icon")),
            "snap": os.path.dirname(path) == SNAP_APPLICATIONS}


def chromium_profiles(places, note):
    """[(display name, arguments, current)] of the first data directory with a Local State.

    Every profile gets its --profile-directory, a single one too: the section
    is named after the profile and has to open it when a second one appears.
    """
    for place in places:
        try:
            profile = json.loads(read_file(os.path.join(place, "Local State")))["profile"]
            cache = [(directory, info) for directory, info in profile["info_cache"].items() if isinstance(info, dict)]
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
            continue
        if not cache:
            continue
        last = profile.get("last_used")
        opens = last if isinstance(last, str) and last in profile["info_cache"] else "Default"
        found = []
        for directory, info in cache:
            # The directory comes from a file the browser owns, a confined one too: it is data, not config.
            reason = unusable(directory) if directory else "it is empty"
            if reason:
                note(f"profile {directory!r} in {place} left out: {reason}")
                continue
            name = one_line(info.get("shortcut_name")) or one_line(info.get("name")) or one_line(directory)
            found.append((directory, name or directory))
        names = [name for _, name in found]
        return [(name if names.count(name) == 1 else f"{name} ({directory})",
                 [f"--profile-directory={directory}"], directory == opens) for directory, name in found]
    return []


def firefox_profiles(places, note):
    """[(profile name, arguments, current)] of the first directory with a profiles.ini."""
    for place in places:
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.optionxform = str
        try:
            text = read_file(os.path.join(place, "profiles.ini"), errors="replace", newline="")
            parser.read_string(text.replace("\r\n", "\n"))
        except (OSError, configparser.Error):
            continue
        profiles = [parser[section] for section in parser.sections()
                    if section.startswith("Profile") and parser[section].get("Name")]
        if not profiles:
            continue
        # The profile an installation opens by itself is in [Install...], older files mark it Default=1.
        installed = {parser[section].get("Default") for section in parser.sections()
                     if section.startswith("Install")} - {None}
        if any(profile.get("Path") in installed for profile in profiles):
            current = [profile.get("Path") in installed for profile in profiles]
        else:
            current = [profile.get("Default") == "1" for profile in profiles]
        found = []
        for profile, is_current in zip(profiles, current):
            # Firefox is asked for the name as the file has it, the windows show it as one line.
            name = profile["Name"]
            reason = unusable(name)
            if reason:
                note(f"profile {name!r} in {place} left out: {reason}")
                continue
            found.append((one_line(name) or name, ["-P", name], is_current))
        return found
    return []


def browser_profiles(argv, snap, env, note):
    """(name for the sections, profiles) of a browser: which family it is and where its data lives."""
    home = env.get("HOME") or os.path.expanduser("~")
    words = iter(argv)
    program = next(words)
    if os.path.basename(program) == "env":
        # A snap entry: env BAMF_DESKTOP_FILE_HINT=... /snap/bin/chromium
        program = next((word for word in words if "=" not in word), program)
    flatpak = None
    if os.path.basename(program) == "flatpak" and "run" in argv:
        flatpak = next((word for word in argv[argv.index("run") + 1:] if not word.startswith(("-", "@"))), "")
    name = os.path.basename(program)
    snap = snap or program.startswith("/snap/")

    for family, programs, app, directory, snap_directory in CHROMIUM_FAMILY:
        if flatpak == app:
            return family, chromium_profiles([os.path.join(home, ".var", "app", app, "config", directory)], note)
        if flatpak is None and name in programs:
            places = [os.path.join(xdg_dir(env, "XDG_CONFIG_HOME", ".config"), directory)]
            places += [os.path.join(home, snap_directory)] if snap_directory else []
            return family, chromium_profiles(places[::-1] if snap else places, note)
    if flatpak == FIREFOX_FLATPAK:
        return "firefox", firefox_profiles([os.path.join(home, ".var", "app", flatpak, ".mozilla", "firefox")], note)
    if flatpak is None and name in FIREFOX_PROGRAMS:
        places = [os.path.join(home, ".mozilla", "firefox"),
                  os.path.join(home, "snap", "firefox", "common", ".mozilla", "firefox")]
        return "firefox", firefox_profiles(places[::-1] if snap else places, note)
    return slug(name if flatpak is None else flatpak.rpartition(".")[2]) or "browser", []


def discover(env, which, note=None):
    """Every browser and profile found: [{"section", "name", "icon", "command", "entries", "current"}].

    "entries" are the desktop entries the browser came from, "current" marks
    the profile the browser opens when it is started without one. Reads only.
    What cannot be a section of the config is left out, and `note` is told:
    one odd entry or profile does not take the others with it.
    """
    def say(message):
        if note:
            note(printable(message))

    browsers = {}
    seen = set(OWN_ENTRIES)
    for directory in application_dirs(env):
        try:
            files = sorted(os.listdir(directory))
        except OSError:
            continue
        for file in files:
            # An entry in an earlier directory stands for every later one of its name.
            if not file.endswith(".desktop") or file in seen:
                continue
            seen.add(file)
            browser = desktop_browser(os.path.join(directory, file), which, say)
            if browser:
                # com.google.Chrome.desktop and google-chrome.desktop start the same thing: one browser.
                browsers.setdefault(browser["key"], browser)["entries"].append(file)

    found, taken = [], {ASK}
    for browser in browsers.values():
        family, profiles = browser_profiles(browser["argv"], browser["snap"], env, say)
        for profile, arguments, current in profiles or [("", [], True)]:
            section = unique_name("-".join(part for part in (family, slug(profile)) if part), taken)
            item = {"section": section, "name": f"{browser['name']} - {profile}" if profile else browser["name"],
                    "icon": browser["icon"], "command": join_command(browser["argv"] + arguments),
                    "entries": browser["entries"], "current": current}
            # Each one alone, by the code of --check: what is returned can always be written.
            errors = check_model(dict(empty_model(), settings={"default": section},
                                      browsers={section: browser_items(item)}))
            if errors:
                say(f"{section} left out: {errors[0]}")
                continue
            taken.add(section)
            found.append(item)
    return found


# --- the default browser of the system ---

QUOTED_ENTRY = "a home directory with a reserved character in its path cannot be registered by xdg-settings 1.1.3"


def xdg_settings(env, *args, run=subprocess.run):
    """Stdout of an xdg-settings call, None when it fails or is not there."""
    try:
        done = run(("xdg-settings",) + args, env=dict(env), timeout=60, stdin=subprocess.DEVNULL,
                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def system_default(env, run=subprocess.run):
    """The desktop entry that is the default browser of the system, None when nobody knows."""
    return xdg_settings(env, "get", "default-web-browser", run=run) or None


def previous_default_file(env):
    return os.path.join(xdg_dir(env, "XDG_STATE_HOME", ".local/state"), "browser-selector", "previous-default")


def previous_default(env):
    """The default browser from before the handler took over, None when it was not written down."""
    try:
        entry = read_file(previous_default_file(env)).strip()
    except (OSError, ValueError):
        return None
    return entry if re.fullmatch(r"[\w.+-]+\.desktop", entry) and entry not in OWN_ENTRIES else None


def make_default(env, run=subprocess.run):
    """Make the handler the default browser, as install.sh --set-default does. An error or None."""
    current = system_default(env, run)
    if xdg_settings(env, "set", "default-web-browser", ENTRY, run=run) is None:
        entry = read_desktop_entry(os.path.join(xdg_dir(env, "XDG_DATA_HOME", ".local/share"), "applications", ENTRY))
        # xdg-settings takes the first word of Exec for the program, the quote of a quoted path included.
        why = f": {QUOTED_ENTRY}" if entry and entry.get("Exec", "").startswith('"') else ""
        return f"xdg-settings could not make {ENTRY} the default browser{why}"
    # Written down after the switch: one that did not happen leaves nothing to go back to.
    if current and current not in OWN_ENTRIES:
        try:
            write_text(previous_default_file(env), current + "\n")
        except OSError as error:
            return f"{previous_default_file(env)}: {error.strerror or error}"
    return None


def restore_default(env, run=subprocess.run):
    """Put the previous default browser back. An error or None."""
    previous = previous_default(env)
    if not previous:
        return "the previous default browser is not known"
    if xdg_settings(env, "set", "default-web-browser", previous, run=run) is None:
        return f"xdg-settings could not make {previous} the default browser"
    return None


def first_config(env, which, run=subprocess.run, note=None):
    """The model of a new install: every browser found, the default browser of the system as the default."""
    found = discover(env, which, note)
    model, _ = with_discovered(empty_model(), found, which)
    entry = system_default(env, run)
    if not entry or entry in OWN_ENTRIES:
        entry = previous_default(env)
    mine = [browser for browser in found if entry in browser["entries"]]
    default = next((browser for browser in mine if browser["current"]), mine[0] if mine else None)
    if default and default["section"] in model["browsers"]:
        model["settings"]["default"] = default["section"]
    return model


# --- what the windows show ---

class NoWindow(Exception):
    """A window cannot be shown. The message says why, it goes to the log."""


def load_windows():
    """The module with the picker and the settings window. A click a rule decides never gets here."""
    # The installed handler runs isolated (-I): the directory of the script is not in sys.path.
    directory = os.path.dirname(HANDLER)
    if directory not in sys.path:
        sys.path.insert(0, directory)
    # The handler runs as __main__. The windows import it by name and must get this very module.
    sys.modules.setdefault("browser_selector", sys.modules[__name__])
    import browser_selector_gui
    return browser_selector_gui


def need_display(env):
    if not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")):
        raise NoWindow("no display")


def link_label(url):
    """What the picker shows of a link: the host, or the link itself when it has none."""
    try:
        host = urlsplit(url).hostname
    except ValueError:
        host = None
    return printable(host or url)


def in_child(function):
    """What function() returns, run in a child process. NoWindow when it raises or dies.

    GTK ends the process it runs in when the display goes away, and it can
    crash in the environment of an odd app. The click has to outlive that.
    """
    # A handler started with a closed stdout or stderr: the pipe would become fd 1 or 2, and the
    # first warning GTK writes there would be read as the answer. /dev/null takes the free ones.
    spare = os.open(os.devnull, os.O_RDWR)
    while spare < 3:
        spare = os.open(os.devnull, os.O_RDWR)
    os.close(spare)
    result, report = os.pipe()
    child = os.fork()
    if child == 0:
        code = 1
        try:
            os.close(result)
            try:
                answer = [True, function()]
            except Exception as error:
                answer = [False, str(error) if isinstance(error, NoWindow) else type(error).__name__]
            with os.fdopen(report, "w", encoding="utf-8") as pipe:
                json.dump(answer, pipe)
            code = 0
        finally:
            os._exit(code)  # never back into the code of the parent
    os.close(report)
    with os.fdopen(result, encoding="utf-8") as pipe:
        text = pipe.read()
    status = os.waitpid(child, 0)[1]
    try:
        done, value = json.loads(text)
    except ValueError:
        raise NoWindow(f"the window ended with wait status {status}") from None
    if not done:
        raise NoWindow(value)
    return value


def ask(env, url, apps, config, windows=None):
    """The browser picked in the picker window, None when the window was closed.

    `windows` is what the tests have in place of load_windows. They get no
    child process, the fake picker of a test cannot take the test with it.
    """
    need_display(env)
    if not config["browsers"]:
        raise NoWindow("no browser to pick from")
    args = (link_label(url), [printable(app) for app in apps],
            [(name, *config["shown"][name]) for name in config["browsers"]])
    picked = windows().pick(*args) if windows else in_child(lambda: load_windows().pick(*args))
    if picked is not None and picked not in config["browsers"]:
        raise NoWindow("the picker did not return a browser")
    return picked


def try_click(config, url, apps, seen, env, which, run_probe=run_probe):
    """What a click would do, for the test page: (rule name, browser, argv, notes).

    The app ids and the window (classes, title) are typed in by hand, `seen`
    is None for no window. The probes run for real. Rule name and argv are
    None when there is none, the browser is `ask` for the picker.
    """
    notes, probes = [], {}

    def probe(command):
        if command not in probes:
            try:
                probes[command] = run_probe(command, config["probe_timeout"], env)
            except Exception as error:
                notes.append(f"probe {command}: {type(error).__name__}")
                probes[command] = None
        return probes[command]

    rule = next((r for r in config["rules"] if rule_matches(r, url, apps, lambda: seen, probe)), None)
    found = commands(config, rule, url, which, notes.append)
    name, _, argv = found[0] if found else (None, None, None)
    if (rule["browser"] if rule else config["default"]) == ASK:
        name, argv = ASK, None
    return rule["name"] if rule else None, name, argv, notes


def log_tail(env, count=200):
    """The last lines of the decision log, the oldest first. Empty when there is no log."""
    directory = os.path.join(xdg_dir(env, "XDG_STATE_HOME", ".local/state"), "browser-selector")
    lines = []
    for name in ("log.1", "log"):
        try:
            lines += read_file(os.path.join(directory, name), errors="replace").splitlines()
        except OSError:
            pass
    return lines[-count:]


def parse_args(argv):
    """(mode, config option, url). ValueError for anything that is not in the usage."""
    mode, option, urls = "open", None, []
    args = iter(argv)
    for arg in args:
        if arg == "--config":
            option = next(args, None)
            if option is None:
                raise ValueError("--config needs a path")
        elif arg in ("--explain", "--check", "--version", "--discover", "--settings", "--init-config"):
            mode = arg[2:]
        elif re.match(r"[\s\x00-\x20\x7f]*(-|\Z)", arg):
            # Browsers trim an argument before they look for a switch in it.
            raise ValueError(f"not a URL: {arg!r}")
        else:
            urls.append(arg)
    least, most = {"open": (1, 1), "explain": (0, 1)}.get(mode, (0, 0))
    if not least <= len(urls) <= most:
        raise ValueError("one URL is expected" if least else "too many arguments")
    return mode, option, urls[0] if urls else None


def main(argv=None, env=None, cgroup_text=None, read_window=read_window, run_probe=run_probe,
         which=None, execve=os.execve, windows=None):
    """Everything external comes in as an argument, the tests replace it."""
    argv = sys.argv[1:] if argv is None else argv
    env = os.environ if env is None else env
    # An empty PATH is no PATH: shutil.which and execvp would find nothing at all.
    which = which or (lambda program: shutil.which(program, path=env.get("PATH") or os.defpath))

    try:
        mode, option, url = parse_args(argv)
    except ValueError as error:
        print(f"browser-selector: {error}\n{USAGE}", file=sys.stderr)
        return 1
    if mode == "version":
        print(f"browser-selector {VERSION}")
        return 0
    def tell(message):
        print(printable(f"browser-selector: {message}"), file=sys.stderr)

    if mode == "discover":
        found = discover(env, which, tell)
        text = render_model(dict(empty_model(), browsers={browser["section"]: browser_items(browser)
                                                          for browser in found}))
        try:
            print(text, end="")
        except UnicodeError:
            # A terminal that cannot show a name gets it as escapes, not a traceback.
            print(text.encode("ascii", "backslashreplace").decode("ascii"), end="")
        if not found:
            print("browser-selector: no browser found", file=sys.stderr)
        return 0

    config_file = config_path(env, option)
    if mode == "check":
        config, errors = load_config(config_file, which)
        if config is None and not errors:
            errors = [f"{config_file}: no such file"]
        for error in errors:
            print(printable(error), file=sys.stderr)
        if errors:
            return 2
        print(f"{config_file}: ok")
        return 0
    if mode == "init-config":
        # For install.sh: a config that is there is never touched.
        if os.path.lexists(config_file):
            print(f"{config_file}: kept")
            return 0
        model = first_config(env, which, note=tell)
        errors = save_model(config_file, model, which) if model["browsers"] else ["no browser found"]
        for error in errors:
            print(printable(f"browser-selector: {error}"), file=sys.stderr)
        if errors:
            return 1
        print(f"{config_file}: browsers found: {len(model['browsers'])}, default = {model['settings']['default']}")
        return 0
    if mode == "settings":
        try:
            need_display(env)
            return (windows or load_windows)().settings(config_file, env)
        except (NoWindow, ImportError) as error:
            print(printable(f"browser-selector: the settings window cannot be shown: {error}"), file=sys.stderr)
            return 1

    explain = mode == "explain"

    def note(message):
        if explain:
            print(printable(f"error: {message}"), file=sys.stderr)
        else:
            write_log(env, f"error: {message}")

    try:
        config, unit, apps, seen, probes, rule, found = decide(
            url, explain, config_file, env, cgroup_text, read_window, run_probe, which, note)
    except Exception as error:  # whatever broke, the click still opens something
        note(f"{type(error).__name__} before the browser was chosen: last resort")
        config, unit, apps, seen, probes, rule = None, None, [], None, {}, None
        found = commands(None, None, url, which, note) if url is not None else []
    asks = bool(config) and url is not None and (rule["browser"] if rule else config["default"]) == ASK

    if explain:
        print_explain(url, unit, apps, seen, probes, rule, found, asks)
        return 0 if found or asks or url is None else 1

    where = f"app={','.join(apps) or '-'} url={url_origin(url)}"
    if asks:
        try:
            picked = ask(env, url, apps, config, windows)
        except Exception as error:
            # No window, nobody to ask: the last resort, as with no config at all.
            note(f"picker: {error if isinstance(error, NoWindow) else type(error).__name__}: last resort")
            found = [command for command in found if command[0] is None]
        else:
            if picked is None:
                write_log(env, f"rule={rule['name'] if rule else '-'} browser={ASK} {where} closed")
                return 0
            found = commands(config, {"browser": picked}, url, which, note)

    for name, path, command in found:
        write_log(env, f"rule={rule['name'] if rule else '-'} browser={name or '-'} {where}")
        try:
            execve(path, command, dict(env, **{GUARD: str(int(time.time()))}))
            return 0  # reached only with an injected exec
        except (OSError, ValueError) as error:
            write_log(env, f"error: {command[0]}: {getattr(error, 'strerror', None) or error}")
    write_log(env, f"error: no browser to start, url={url_origin(url)}")
    print("browser-selector: no browser to start", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
