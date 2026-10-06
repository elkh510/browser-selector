#!/bin/bash
# Does browser_selector_gui.py run on Ubuntu 26.04 at all: python 3.14, GTK
# 4.22, libadwaita 1.9. It was written against GTK 4.6 and libadwaita 1.1.
# The module is imported with every warning as an error, the names it uses
# are looked up in the typelibs, and both windows are walked through with the
# diagnostics of Python and GObject on: every warning, deprecation and
# critical they print is listed.
set -eu
. "$GNOME50_DIR/scenarios/_boot.sh"
. "$GNOME50_DIR/gui.sh"
boot
start_gui

write_config <<'CONFIG'
[settings]
default = ask

[browser chrome-main]
name = Google Chrome - main
icon = google-chrome
command = google-chrome --profile-directory="Profile 6"

[browser fox]
name = Firefox
command = firefox --new-tab

[rule docs]
url = ^https://docs\.example\.com/
browser = fox
CONFIG

LIB="$XDG_DATA_HOME/browser-selector"
PICKER="Open link"
SETTINGS="Browser Selector"
DIAGNOSTICS="$OUT_DIR/diagnostics.log"
show() { sed 's/^/     /'; }

# What counts as a complaint in the output of a window
complaints() {
    grep -E "Warning|WARNING|CRITICAL|ERROR|deprecat|Traceback" "$@" || true
}

# PyGObject 3.56 warns about itself on this python and GLib, from its own
# files: that is not the tool
OWN_OF_GI="^/usr/lib/python3/dist-packages/gi/"

echo "== versions =="
python3 - <<'PYTHON' | show
import sys
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk
print(f"python {sys.version.split()[0]}, PyGObject {gi.__version__},"
      f" GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()},"
      f" libadwaita {Adw.get_major_version()}.{Adw.get_minor_version()}.{Adw.get_micro_version()}")
PYTHON

echo "== the module imports =="
# Isolated like the installed handler, and every warning is an error, the
# ones PyGObject raises about itself aside: a warning of python 3.14 about
# the handler or the windows would stop the import
rc=0
/usr/bin/python3 -I -W error -W ignore:::gi.overrides -W ignore:::gi.events -c \
    'import sys; sys.path.insert(0, sys.argv[1]); import browser_selector, browser_selector_gui' \
    "$LIB" >"$OUT_DIR/import.log" 2>&1 || rc=$?
show <"$OUT_DIR/import.log"
expect_equal "browser_selector and browser_selector_gui import with warnings as errors" \
    "0 " "$rc $(cat "$OUT_DIR/import.log")"

echo "== the names the windows use =="
rc=0
python3 "$GNOME50_DIR/gui-api.py" "$LIB/browser_selector_gui.py" >"$OUT_DIR/api.log" 2>&1 || rc=$?
show <"$OUT_DIR/api.log"
expect_equal "no class, function or constant of GTK and libadwaita is missing or deprecated" 0 "$rc"
# A hint is a name that is deprecated in some class of the file, with the
# receiver unknown: the run under diagnostics below says whether it is real

echo "== the icons the windows name =="
# The names in the source and the one of the desktop entry of the settings
# window. Yaru is the icon theme of Ubuntu and what counts here, Adwaita the
# one of plain GNOME, for the record.
icons="$(grep -o '"[a-z-]*-symbolic"' "$LIB/browser_selector_gui.py" | tr -d '"' | sort -u | tr '\n' ' ')web-browser"
echo "     $icons"
absent_in() {
    gsettings set org.gnome.desktop.interface icon-theme "$1"
    sleep 0.5
    # shellcheck disable=SC2086
    python3 - $icons <<'PYTHON'
import sys
import gi
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk
Gtk.init()
theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
print(" ".join(name for name in sys.argv[1:] if not theme.has_icon(name)))
PYTHON
}
echo "     not in Adwaita $(dpkg-query -W -f '${Version}' adwaita-icon-theme): $(absent_in Adwaita)"
expect_equal "every icon is in Yaru" "" "$(absent_in Yaru)"

echo "== the picker under diagnostics =="
# -W always shows every Python warning once more than the default filter
# does, G_ENABLE_DIAGNOSTIC makes GObject name deprecated properties and
# signals in use
export G_ENABLE_DIAGNOSTIC=1
BEFORE="$(launches)"
/usr/bin/python3 -I -W always "$HANDLER" https://example.com/diagnostics >>"$DIAGNOSTICS" 2>&1 &
pid=$!
wait_window "$PICKER"
expect_true "the picker is shown" test -n "$WINDOW"
press Down Up
press 1
wait_launch $((BEFORE + 1))
expect_launch "and opens the browser of its first row" \
    google-chrome "--profile-directory=Profile 6" https://example.com/diagnostics

echo "== the settings window under diagnostics =="
/usr/bin/python3 -I -W always "$HANDLER" --settings >>"$DIAGNOSTICS" 2>&1 &
pid=$!
APP_PIDS="$APP_PIDS $pid"
wait_window "$SETTINGS"
expect_true "the settings window is shown" test -n "$WINDOW"
# Every page, both forms, the list of the default, a test and a refusal
press alt+1
press alt+f
press alt+b
wait_window "New browser"
expect_true "the form of a browser opens" test -n "$WINDOW"
press Escape
window_gone "New browser" || true
press alt+2
press alt+r
wait_window "New rule"
expect_true "the form of a rule opens" test -n "$WINDOW"
type_text "bad"
press alt+u
type_text "(unclosed"
press alt+s
press Escape
window_gone "New rule" || true
press alt+3
press alt+e
press Escape
press alt+4
press alt+u
type_text "https://docs.example.com/page"
press alt+t
press alt+5
press ctrl+q
wait_exit "$pid"
expect_equal "the window is closed with ctrl+q, exit code 0" 0 "$EXIT_CODE"
unset G_ENABLE_DIAGNOSTIC

echo "== what the windows printed =="
sort "$DIAGNOSTICS" | uniq -c | show
expect_equal "three warnings of PyGObject about itself, the same in both processes" \
    "3" "$(complaints "$DIAGNOSTICS" | grep -E "$OWN_OF_GI" | sort -u | wc -l)"
expect_equal "no warning, deprecation, critical or traceback names the tool, GTK or libadwaita" \
    "" "$(complaints "$DIAGNOSTICS" | grep -Ev "$OWN_OF_GI" || true)"
# The refusal of the bad regex is the one line that is meant to be there
expect_true "the refusal of the bad regex is there" \
    grep -q "^browser-selector: not saved: \[rule bad\] url: bad regex" "$DIAGNOSTICS"

echo "== the unit tests on this python =="
rc=0
(cd /repo && PYTHONDONTWRITEBYTECODE=1 python3 -W always -m unittest discover -s tests) \
    >"$OUT_DIR/unit-tests.log" 2>&1 || rc=$?
tail -n 4 "$OUT_DIR/unit-tests.log" | show
expect_equal "the unit tests of the checkout pass" 0 "$rc"
warnings="$(grep -E "Warning" "$OUT_DIR/unit-tests.log" | sort -u || true)"
[ -z "$warnings" ] || printf '%s\n' "$warnings" | show
expect_equal "without a warning of python" "" "$warnings"

finish
