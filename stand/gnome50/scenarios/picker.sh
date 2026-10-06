#!/bin/bash
# The picker under GNOME Shell on Wayland: with `default = ask` a click no
# rule decides shows a window with the configured browsers. The first
# question is the focus: the picker is a new window of another process, and
# whether it gets the keyboard or is left behind the app with a "is ready"
# notification is up to the shell. Asked for a link of an X11 app and for one
# of a native Wayland app, after a real click into the app. Then the keys of
# common/scenarios/picker.sh: a digit, Enter or a click picks a browser, Esc
# or closing the window opens nothing.
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

[browser brave-home]
name = Brave - R&D <el>
command = brave-browser --profile-directory="Profile 1" {url}

[rule slack]
app = slack
browser = fox

[rule netbird]
app = netbird
browser = ask
CONFIG

PICKER="Open link"
X11_APP="Terminal"
WAYLAND_APP="notes.txt"

start_app terminal --instance gnome-terminal-server --class Gnome-terminal --title "$X11_APP"
start_wayland_app editor --app-id org.gnome.TextEditor --title "$WAYLAND_APP" \
    --unit app-gnome-org.gnome.TextEditor-5001.scope
start_app slack --instance slack --class Slack --title "Slack" --unit app-slack-2382881.scope
start_app netbird --unit app-gnome-netbird-14016.scope

# use_window TITLE: the user is in this window. The shell raises it, then a
# click of the pointer lands in it: the last input of the session went to the
# app the link is about to come from.
use_window() {
    focus "$1"
    WINDOW="$1"
    click_window 240 120
    expect_equal "the user works in: $1" "$1" "$(focused_field title)"
}

# click_link APP URL: the app opens the link, and the picker is waited for
# instead of a browser
click_link() {
    BEFORE="$(launches)"
    app_cmd "$1" "open-now $2"
    wait_window "$PICKER"
}

# picker_shown WHAT: the picker is on the screen and nothing was started yet
picker_shown() {
    if [ -n "$WINDOW" ] && [ "$(launches)" = "$BEFORE" ]; then
        pass "$1"
    else
        fail "$1"
        echo "     window: ${WINDOW:-none}, launches: $BEFORE -> $(launches)"
    fi
}

# has_focus WHAT: the picker got the keyboard without anybody giving it, and
# the shell did not put it aside with a notification
has_focus() {
    expect_true "$1" wait_focus "$PICKER"
    echo "     focused: $(shell focused)"
    expect_equal "no window asked for attention, the shell showed no \"is ready\"" "" "$(shell attention)"
}

echo "== a rule decides: no picker =="
app_open slack https://example.com/rule open-now
expect_launch "the browser of the rule opens" firefox --new-tab https://example.com/rule
expect_equal "and no picker was shown" "" "$(window_id "$PICKER")"

echo "== a link of an X11 app: the focus, then the digit of a row =="
use_window "$X11_APP"
echo "     focused: $(shell focused)"
click_link terminal https://example.com/digit
picker_shown "a click no rule decides shows the picker and starts nothing"
shell window "$PICKER" | sed 's/^/     picker:  /'
expect_equal "the picker is a native Wayland window with the app id browser-selector" \
    "wayland browser-selector" "$(window_field "$PICKER" client) $(window_field "$PICKER" class)"
has_focus "the picker gets the keyboard focus on its own"
press 2
wait_launch $((BEFORE + 1))
expect_launch "2 opens the link in the second browser" firefox --new-tab https://example.com/digit
expect_true "and the picker is gone" window_gone "$PICKER"
expect_true "the focus goes back to the app" wait_focus "$X11_APP"

echo "== a link of a native Wayland app: the focus, then Enter =="
use_window "$WAYLAND_APP"
echo "     focused: $(shell focused)"
click_link editor 'https://example.com/enter?a=$(touch /tmp/pwned)&b=;x'
picker_shown "the picker is shown"
shell window "$PICKER" | sed 's/^/     picker:  /'
has_focus "the picker gets the keyboard focus on its own"
press Return
wait_launch $((BEFORE + 1))
expect_launch "Enter opens the first browser, the URL is one unchanged argument" \
    google-chrome "--profile-directory=Profile 6" 'https://example.com/enter?a=$(touch /tmp/pwned)&b=;x'
expect_unit "the browser is started from the cgroup of the app" app-gnome-org.gnome.TextEditor-5001.scope
expect_true "the focus goes back to the app" wait_focus "$WAYLAND_APP"

echo "== Down, then Enter =="
click_link editor https://example.com/down
picker_shown "the picker is shown"
press Down Down
press Return
wait_launch $((BEFORE + 1))
expect_launch "the third row is selected and opened, the URL goes where {url} is" \
    brave-browser "--profile-directory=Profile 1" https://example.com/down

echo "== a click on a row =="
click_link editor https://example.com/click
picker_shown "the picker is shown"
echo "     rect: $(window_field "$PICKER" rect)"
# The last row ends 12 pixels above the lower edge of the window
click_window 150 -40
wait_launch $((BEFORE + 1))
expect_launch "a click on the last row opens the third browser" \
    brave-browser "--profile-directory=Profile 1" https://example.com/click

echo "== a rule that asks, an app without a window =="
click_link netbird https://example.com/rule-asks
picker_shown "browser = ask in a rule shows the picker"
has_focus "the picker gets the keyboard focus on its own"
press 1
wait_launch $((BEFORE + 1))
expect_launch "1 opens the first browser" \
    google-chrome "--profile-directory=Profile 6" https://example.com/rule-asks
expect_unit "the browser is started from the cgroup of the app" app-gnome-netbird-14016.scope

echo "== Esc =="
mark="$(log_mark)"
click_link editor https://example.com/escape
picker_shown "the picker is shown"
press Escape
expect_true "Esc closes the picker" window_gone "$PICKER"
sleep 1
expect_equal "and nothing was started" "$BEFORE" "$(launches)"
log_since "$mark" | sed 's/^/     /'
expect_true "the log says the picker was closed" log_has "$mark" "browser=ask .*url=https://example\.com closed$"

echo "== Esc: the exit code =="
# Called directly: the exit code of a handler gio started cannot be seen
BEFORE="$(launches)"
"$HANDLER" https://example.com/escape-direct >"$OUT_DIR/direct.log" 2>&1 &
pid=$!
wait_window "$PICKER"
picker_shown "the picker is shown"
press Escape
wait_exit "$pid"
expect_equal "the handler exits with 0" 0 "$EXIT_CODE"
expect_equal "and says nothing" "" "$(cat "$OUT_DIR/direct.log")"
expect_equal "nothing was started" "$BEFORE" "$(launches)"

echo "== the window is closed by the shell =="
BEFORE="$(launches)"
"$HANDLER" https://example.com/closed >"$OUT_DIR/direct.log" 2>&1 &
pid=$!
wait_window "$PICKER"
picker_shown "the picker is shown"
shell close "$PICKER"
wait_exit "$pid"
expect_equal "the handler exits with 0" 0 "$EXIT_CODE"
expect_equal "and says nothing" "" "$(cat "$OUT_DIR/direct.log")"
expect_equal "nothing was started" "$BEFORE" "$(launches)"

echo "== a key that is no row =="
click_link editor https://example.com/other-key
picker_shown "the picker is shown"
press 9 x
expect_equal "9 and x start nothing, the picker stays" "$BEFORE $PICKER" "$(launches) $(window_id "$PICKER")"
press 3
wait_launch $((BEFORE + 1))
expect_launch "3 still opens the third browser" \
    brave-browser "--profile-directory=Profile 1" https://example.com/other-key

echo "== the picker dies =="
# The window lives in a child of the handler. Whatever takes it away, a lost
# display or a crash of GTK, the handler is still there to open something.
mark="$(log_mark)"
click_link editor https://example.com/killed
picker_shown "the picker is shown"
kill -KILL "$(window_field "$PICKER" pid)"
wait_launch $((BEFORE + 1))
expect_launch "the process of the window is killed: the last resort opens" \
    google-chrome https://example.com/killed
log_since "$mark" | sed 's/^/     /'
expect_true "the log says why" log_has "$mark" "error: picker: the window ended with wait status 9: last resort"

echo "== GTK is loaded for the picker only =="
# Called directly, under strace. The app comes from the file the contract has
# for that: with it a rule decides, without it nobody does and the picker asks.
printf '0::/user.slice/user-1000.slice/user@1000.service/app.slice/app-slack-1.scope\n' >"$STAND/slack.cgroup"
before="$(launches)"
BROWSER_SELECTOR_CGROUP_FILE="$STAND/slack.cgroup" strace -f -o "$OUT_DIR/rule.strace" -e trace=openat \
    "$HANDLER" https://example.com/strace-rule >/dev/null 2>&1 || true
wait_launch $((before + 1))
expect_launch "a click the rule decides" firefox --new-tab https://example.com/strace-rule
expect_false "opens no file of GTK, libadwaita or gi" \
    grep -Eq "libgtk|libadwaita|girepository|/gi/|browser_selector_gui" "$OUT_DIR/rule.strace"
strace -f -o "$OUT_DIR/ask.strace" -e trace=openat "$HANDLER" https://example.com/strace-ask >/dev/null 2>&1 &
pid=$!
wait_window "$PICKER"
press Escape
wait_exit "$pid"
expect_true "a click that asks does open them" grep -q "libgtk-4" "$OUT_DIR/ask.strace"

echo "== an app without DISPLAY: the picker is a Wayland window all the same =="
start_app tty --unit app-org.example.Tty-4711.scope --no-display
click_link tty https://example.com/wayland-only
picker_shown "with WAYLAND_DISPLAY alone the picker is shown"
press 2
wait_launch $((BEFORE + 1))
expect_launch "and opens the browser picked" firefox --new-tab https://example.com/wayland-only
expect_equal "the handler had no DISPLAY" "" "$(meta display)"

echo "== no display at all: the last resort =="
session="$WAYLAND_DISPLAY"
unset WAYLAND_DISPLAY
start_app blind --unit app-org.example.Blind-4712.scope --no-display
export WAYLAND_DISPLAY="$session"
mark="$(log_mark)"
app_open blind https://example.com/no-display open-now
expect_launch "without DISPLAY and WAYLAND_DISPLAY the last resort opens, with the URL alone" \
    google-chrome https://example.com/no-display
log_since "$mark" | sed 's/^/     /'
expect_true "the log says why" log_has "$mark" "error: picker: no display: last resort"

echo "== a Wayland display nobody answers on: the last resort =="
WAYLAND_DISPLAY=wayland-9 start_app late --unit app-org.example.Late-4713.scope --no-display
mark="$(log_mark)"
app_open late https://example.com/dead-display open-now
expect_launch "with a dead WAYLAND_DISPLAY the last resort opens" google-chrome https://example.com/dead-display
log_since "$mark" | sed 's/^/     /'
expect_true "the log says why" log_has "$mark" "error: picker: the display cannot be opened: last resort"

echo "== what the pickers printed =="
# The picker of a click writes to the output of the app the link came from
grep -HE "Warning|WARNING|CRITICAL|ERROR|deprecat|Traceback" "$OUT_DIR"/app-*.log "$OUT_DIR/direct.log" \
    | sed 's/^/     /' || true
expect_false "no warning, critical or traceback of python, GTK or libadwaita" \
    grep -qE "Warning|WARNING|CRITICAL|ERROR|deprecat|Traceback" "$OUT_DIR"/app-*.log "$OUT_DIR/direct.log"
expect_false "no URL ever ran a command" test -e /tmp/pwned

finish
