#!/bin/bash
# A session without Xwayland at all: the shell runs with --no-x11, there is
# no X11 socket and no DISPLAY. A rule with a title can never match, the rules
# without a window still route, and every click opens a browser.
set -eu
. "$GNOME50_DIR/scenarios/_boot.sh"
boot --no-x11

write_config <<'CONFIG'
[settings]
default = firefox

[browser firefox]
command = firefox

[browser chrome-acme]
command = google-chrome --profile-directory="Profile 6"

[browser brave-globex]
command = brave-browser --profile-directory=Default {url}

[rule slack-acme]
app = slack
title = - Acme - Slack$
browser = chrome-acme

[rule netbird]
app = netbird
browser = brave-globex
CONFIG

show() { sed 's/^/     /'; }
SLACK_TITLE="Threads - Acme - Slack"

echo "== the session =="
expect_false "no Xwayland process" pgrep -x Xwayland
expect_false "no X11 socket" ls /tmp/.X11-unix/X0
expect_equal "the shell exports no DISPLAY" null "$(shell eval "imports.gi.GLib.getenv('DISPLAY')")"
expect_equal "the stand has none either" "" "${DISPLAY:-}"

echo "== no DISPLAY =="
start_wayland_app slack --app-id slack --title "$SLACK_TITLE" \
    --unit app-slack-2382881.scope --desktop slack.desktop
focus "$SLACK_TITLE"
echo "     focused: $(shell focused)"
CHROME_DESKTOP=slack.desktop "$HANDLER" --explain https://example.com/ 2>&1 | show
app_open slack https://example.com/no-display open-now
expect_launch "the click of the focused Slack opens the default browser" \
    firefox https://example.com/no-display
expect_equal "the handler had no DISPLAY" "" "$(meta display)"
expect_unit "and sat in the cgroup of the app" app-slack-2382881.scope

echo "== a DISPLAY nobody answers on =="
# An environment left over from a session that had Xwayland
DISPLAY=:0 start_wayland_app slack-stale --app-id slack --title "general - Acme - Slack" \
    --unit app-slack-2383000.scope --desktop slack.desktop
focus "general - Acme - Slack"
echo "     \$ DISPLAY=:0 xprop -root _NET_ACTIVE_WINDOW"
DISPLAY=:0 xprop -root _NET_ACTIVE_WINDOW 2>&1 | show || true
app_open slack-stale https://example.com/dead-display open-now
expect_launch "with a dead DISPLAY the click opens the default browser" \
    firefox https://example.com/dead-display
expect_equal "the handler had the dead DISPLAY" ":0" "$(meta display)"
expect_false "and that did not start an Xwayland" pgrep -x Xwayland

echo "== a rule without a window =="
start_app netbird --unit app-gnome-netbird-14016.scope
app_open netbird "https://login.example.com/device?user_code=ABCD-EFGH"
expect_launch "the app rule routes as ever" \
    brave-browser --profile-directory=Default "https://login.example.com/device?user_code=ABCD-EFGH"

finish
