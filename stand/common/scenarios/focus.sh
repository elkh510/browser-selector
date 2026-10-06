#!/bin/bash
# The title is the title of the focused window, whoever opens the link: a
# rule with `title` must not fire when another window has the focus, and
# without X there is no window at all and the click still opens a browser
set -eu
. "$(dirname "$(readlink -f "$0")")/_boot.sh"
boot

write_config <<'EOF'
[settings]
default = firefox

[browser firefox]
command = firefox

[browser chrome-acme]
command = google-chrome --profile-directory="Profile 6"

[rule slack-acme]
app = slack
title = - Acme - Slack$
browser = chrome-acme
EOF

focused() {
    local id
    id="$(xprop -root _NET_ACTIVE_WINDOW | sed -n 's/.*window id # //p')"
    echo "     focused: $(LC_ALL=C.UTF-8 xprop -id "$id" WM_CLASS _NET_WM_NAME | tr '\n' ' ')"
}

start_app slack --instance slack --class Slack --title "Threads - Acme - Slack" \
    --unit app-slack-2382881.scope --desktop slack.desktop
start_app terminal --instance gnome-terminal-server --class Gnome-terminal --title "dev@desktop: ~"

echo "== Slack has the focus =="
app_open slack https://example.com/focused
focused
expect_launch "the rule fires for the focused Slack" \
    google-chrome "--profile-directory=Profile 6" https://example.com/focused

echo "== another window has the focus, Slack opens a link =="
app_focus terminal
focused
app_open slack https://example.com/unfocused open-now
expect_launch "the rule does not fire, the default browser opens" \
    firefox https://example.com/unfocused

echo "== the focused window has the title, but is not Slack =="
app_title terminal "notes - Acme - Slack"
app_open terminal https://example.com/lookalike
focused
expect_launch "a title without the app goes to the default browser" \
    firefox https://example.com/lookalike

echo "== no DISPLAY =="
start_app slack-tty --unit app-slack-2382999.scope --desktop slack.desktop --no-display
app_open slack-tty https://example.com/no-display
expect_launch "without DISPLAY the click opens the default browser" \
    firefox https://example.com/no-display
expect_equal "the handler had no DISPLAY" "" "$(meta display)"

echo "== a DISPLAY nobody answers on =="
kill "$WM_PID" "$XVFB_PID"
wait "$XVFB_PID" 2>/dev/null || true
start_app slack-late --unit app-slack-2383000.scope --desktop slack.desktop
app_open slack-late https://example.com/dead-display
expect_launch "with a dead X server the click opens the default browser" \
    firefox https://example.com/dead-display
expect_equal "the handler had the dead DISPLAY" "$DISPLAY" "$(meta display)"

finish
