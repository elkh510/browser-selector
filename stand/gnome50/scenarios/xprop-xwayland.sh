#!/bin/bash
# What xprop tells the handler on a Wayland session. The handler asks the
# Xwayland of the shell for _NET_ACTIVE_WINDOW, so it can see an X11 client
# and nothing else: with a native Wayland window focused there must be no
# window for it, and above all not the X11 window that had the focus before.
# Which window has the focus is asked from the shell itself every time.
set -eu
. "$GNOME50_DIR/scenarios/_boot.sh"
boot

write_config <<'CONFIG'
[settings]
default = firefox

[browser firefox]
command = firefox

[browser chrome-acme]
command = google-chrome --profile-directory="Profile 6"

[browser brave-title]
command = brave-browser --profile-directory=Default

[rule slack-acme]
app = slack
title = - Acme - Slack$
browser = chrome-acme

[rule title-alone]
title = - Acme - Slack$
browser = brave-title
CONFIG

show() { sed 's/^/     /'; }

# The two questions of the handler, with the raw answers of xprop
active_raw() { xprop -root _NET_ACTIVE_WINDOW 2>&1; }
active_id() { active_raw | sed -n 's/.*window id # //p'; }
window_raw() { LC_ALL=C.UTF-8 xprop -id "$1" WM_CLASS _NET_WM_NAME WM_NAME _NET_WM_PID 2>&1; }

# What the handler makes of it, seen from Slack: --explain with the app id a
# real Slack has in its environment
explain() {
    CHROME_DESKTOP=slack.desktop "$HANDLER" --explain "$1" 2>&1 | grep -E '^(window|title|rule|browser):'
}
explain_line() { explain "$1" | sed -n "s/^$2: //p"; }

SLACK_TITLE="Threads - Acme - Slack"

echo "== before the first X11 client =="
# The shell listens on the X11 socket and starts Xwayland for the first
# client, and that client can be the xprop of the handler. It does so when
# its cgroup says it runs as a unit of systemd --user, as on the desktop and
# in the real cgroups of the stand. Anywhere else it starts Xwayland at boot.
if [ "$CGROUP_MODE" = real ]; then
    expect_false "Xwayland is not running yet" pgrep -x Xwayland
else
    echo "SKIP Xwayland is not running yet: CGROUP=file, the shell is in no unit and starts it at boot"
fi
start_wayland_app editor --app-id org.gnome.TextEditor --title "notes.txt" \
    --unit app-gnome-org.gnome.TextEditor-5001.scope
focus "notes.txt"
echo "     focused: $(shell focused)"
explain https://example.com/ | show
expect_equal "--explain has no window" "-" "$(explain_line https://example.com/ window)"
for _ in $(seq 1 50); do
    pgrep -x Xwayland >/dev/null && break
    sleep 0.1
done
expect_true "Xwayland is running after the xprop of the handler" pgrep -x Xwayland
echo "     \$ xprop -root _NET_ACTIVE_WINDOW"
active_raw | show
if [ "$CGROUP_MODE" = real ]; then
    expect_equal "the focus has not changed since Xwayland came up: no _NET_ACTIVE_WINDOW at all" \
        "" "$(active_id)"
fi
click editor "notes.txt" https://example.com/first
expect_launch "the click opens the default browser" firefox https://example.com/first

echo "== (a) an X11 window has the focus =="
start_app slack --instance slack --class Slack --title "$SLACK_TITLE" \
    --unit app-slack-2382881.scope --desktop slack.desktop
focus "$SLACK_TITLE"
echo "     focused: $(shell focused)"
slack_id="$(focused_field id)"
expect_equal "the shell has the focus on the X11 client Slack" \
    "x11 Slack $SLACK_TITLE" "$(focused_field client) $(focused_field class) $(focused_field title)"
echo "     \$ xprop -root _NET_ACTIVE_WINDOW"
active_raw | show
echo "     \$ xprop -id $(active_id) WM_CLASS _NET_WM_NAME WM_NAME _NET_WM_PID"
window_raw "$(active_id)" | show
expect_equal "_NET_ACTIVE_WINDOW is the window the shell has the focus on" \
    "$((slack_id))" "$(($(active_id)))"
explain https://example.com/ | show
expect_equal "--explain sees the class" "slack, Slack" "$(explain_line https://example.com/ window)"
expect_equal "--explain sees the title" "$SLACK_TITLE" "$(explain_line https://example.com/ title)"
app_open slack https://example.com/a open-now
expect_launch "the title rule fires for the focused X11 Slack" \
    google-chrome "--profile-directory=Profile 6" https://example.com/a
app_title slack "general (Channel) - Globex - Slack"
app_open slack https://example.com/a-globex open-now
expect_launch "the title is read on every click: another workspace, the default browser" \
    firefox https://example.com/a-globex
app_title slack "$SLACK_TITLE"

echo "== (b) a native Wayland window has the focus =="
focus "notes.txt"
echo "     focused: $(shell focused)"
expect_equal "the shell has the focus on the Wayland client" \
    "wayland notes.txt" "$(focused_field client) $(focused_field title)"
echo "     \$ xprop -root _NET_ACTIVE_WINDOW"
active_raw | show
other_id="$(active_id)"
echo "     \$ xprop -id $other_id WM_CLASS _NET_WM_NAME WM_NAME _NET_WM_PID"
window_raw "$other_id" | show
echo "     \$ xwininfo -id $other_id"
xwininfo -id "$other_id" 2>&1 | grep -E 'Window id|Width|Height|Absolute' | show
if [ -n "$other_id" ] && [ "$((other_id))" != "$((slack_id))" ]; then
    pass "_NET_ACTIVE_WINDOW is not the X11 window that had the focus before"
else
    fail "_NET_ACTIVE_WINDOW is not the X11 window that had the focus before"
fi
explain https://example.com/ | show
expect_equal "--explain has no window" "-" "$(explain_line https://example.com/ window)"
expect_equal "--explain has no title" "-" "$(explain_line https://example.com/ title)"
app_open editor https://example.com/b-editor open-now
expect_launch "a link of the Wayland app: no title rule fires on the title of Slack" \
    firefox https://example.com/b-editor
app_open slack https://example.com/b-slack open-now
expect_launch "a link of the unfocused Slack: its own title rule does not fire either" \
    firefox https://example.com/b-slack

# The same reading right after each of ten focus changes: the hint of the
# shell must never lag behind the focus
stale=0
for _ in $(seq 1 10); do
    shell focus "$SLACK_TITLE"
    [ "$(($(active_id)))" = "$((slack_id))" ] || stale=$((stale + 1))
    shell focus "notes.txt"
    [ "$(($(active_id)))" != "$((slack_id))" ] || stale=$((stale + 1))
done
expect_equal "ten focus changes back and forth, no reading of _NET_ACTIVE_WINDOW lags behind" 0 "$stale"

echo "== (b) Slack itself as a native Wayland window =="
# What an Electron app is once it runs on Wayland natively: the same app id,
# cgroup and title, and no X11 window
WAYLAND_TITLE="general (Channel) - Acme - Slack"
start_wayland_app slack-wayland --app-id slack --title "$WAYLAND_TITLE" \
    --unit app-slack-2390000.scope --desktop slack.desktop
focus "$WAYLAND_TITLE"
echo "     focused: $(shell focused)"
expect_equal "the shell has the focus on the Wayland client Slack" \
    "wayland slack $WAYLAND_TITLE" "$(focused_field client) $(focused_field class) $(focused_field title)"
echo "     \$ xprop -root _NET_ACTIVE_WINDOW"
active_raw | show
explain https://example.com/ | show
app_open slack-wayland https://example.com/b-native open-now
expect_launch "its title is out of reach of xprop: the title rule does not fire" \
    firefox https://example.com/b-native
expect_unit "though the handler sat in the cgroup of that Slack" app-slack-2390000.scope
expect_equal "and had its CHROME_DESKTOP" slack.desktop "$(meta chrome_desktop)"

echo "== back on the X11 window =="
click slack "$SLACK_TITLE" https://example.com/back
echo "     focused: $(shell focused)"
expect_launch "the title rule fires again" \
    google-chrome "--profile-directory=Profile 6" https://example.com/back

echo "== (c) Xwayland is up, the app has no DISPLAY =="
start_app slack-tty --unit app-slack-2382999.scope --desktop slack.desktop --no-display
app_open slack-tty https://example.com/no-display
expect_launch "without DISPLAY the click opens the default browser" \
    firefox https://example.com/no-display
expect_equal "the handler had no DISPLAY" "" "$(meta display)"

finish
