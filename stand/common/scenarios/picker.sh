#!/bin/bash
# The picker: with `default = ask` a click no rule decides shows a window with
# the configured browsers. A digit, Enter or a click picks one, Esc or closing
# the window opens nothing. Without a display the last resort opens.
set -eu
. "$(dirname "$(readlink -f "$0")")/_boot.sh"
. "$HARNESS_DIR/gui.sh"
boot

write_config <<'EOF2'
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
EOF2

PICKER="Open link"

start_app terminal --instance gnome-terminal-server --class Gnome-terminal --title "Terminal"
start_app slack --instance slack --class Slack --title "Slack" --unit app-slack-2382881.scope
start_app netbird --unit app-gnome-netbird-14016.scope

# click_link APP URL: the app opens the link, and the picker is waited for
# instead of a browser
click_link() {
    BEFORE="$(launches)"
    app_cmd "$1" "open $2"
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

echo "== a rule decides: no picker =="
app_open slack https://example.com/rule
expect_launch "the browser of the rule opens" firefox --new-tab https://example.com/rule
expect_equal "and no picker was shown" "" "$(window_id "$PICKER")"

echo "== default = ask: the digit of a row =="
click_link terminal https://example.com/digit
picker_shown "a click no rule decides shows the picker and starts nothing"
xprop -id "$WINDOW" WM_CLASS _NET_WM_NAME 2>/dev/null | sed 's/^/     /' || true
press 2
wait_launch $((BEFORE + 1))
expect_launch "2 opens the link in the second browser" firefox --new-tab https://example.com/digit
expect_true "and the picker is gone" window_gone "$PICKER"

echo "== Enter on the selected row =="
click_link terminal 'https://example.com/enter?a=$(touch /tmp/pwned)&b=;x'
picker_shown "the picker is shown"
press Return
wait_launch $((BEFORE + 1))
expect_launch "Enter opens the first browser, the URL is one unchanged argument" \
    google-chrome "--profile-directory=Profile 6" 'https://example.com/enter?a=$(touch /tmp/pwned)&b=;x'

echo "== Down, then Enter =="
click_link terminal https://example.com/down
picker_shown "the picker is shown"
press Down Down
press Return
wait_launch $((BEFORE + 1))
expect_launch "the third row is selected and opened, the URL goes where {url} is" \
    brave-browser "--profile-directory=Profile 1" https://example.com/down

echo "== a click on a row =="
click_link terminal https://example.com/click
picker_shown "the picker is shown"
xdotool getwindowgeometry "$WINDOW" | sed 's/^/     /'
# The last row ends 12 pixels above the lower edge of the window
click_window 150 -40
wait_launch $((BEFORE + 1))
expect_launch "a click on the last row opens the third browser" \
    brave-browser "--profile-directory=Profile 1" https://example.com/click

echo "== a rule that asks =="
click_link netbird https://example.com/rule-asks
picker_shown "browser = ask in a rule shows the picker"
press 1
wait_launch $((BEFORE + 1))
expect_launch "1 opens the first browser" \
    google-chrome "--profile-directory=Profile 6" https://example.com/rule-asks
if [ "$CGROUP_MODE" = real ]; then
    expect_equal "the browser is started from the cgroup of the app" "app-gnome-netbird-14016.scope" "$(meta unit)"
fi

echo "== Esc =="
mark="$(log_mark)"
click_link terminal https://example.com/escape
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

echo "== the window is closed by the window manager =="
BEFORE="$(launches)"
"$HANDLER" https://example.com/closed >"$OUT_DIR/direct.log" 2>&1 &
pid=$!
wait_window "$PICKER"
picker_shown "the picker is shown"
wmctrl -i -c "$WINDOW"
wait_exit "$pid"
expect_equal "the handler exits with 0" 0 "$EXIT_CODE"
expect_equal "nothing was started" "$BEFORE" "$(launches)"

echo "== a key that is no row =="
click_link terminal https://example.com/other-key
picker_shown "the picker is shown"
press 9 x
expect_equal "9 and x start nothing, the picker stays" "$BEFORE $WINDOW" "$(launches) $(window_id "$PICKER")"
press 3
wait_launch $((BEFORE + 1))
expect_launch "3 still opens the third browser" \
    brave-browser "--profile-directory=Profile 1" https://example.com/other-key

echo "== the picker dies =="
# The window lives in a child of the handler. Whatever takes it away, a lost
# display or a crash of GTK, the handler is still there to open something.
mark="$(log_mark)"
click_link terminal https://example.com/killed
picker_shown "the picker is shown"
kill -KILL "$(xdotool getwindowpid "$WINDOW")"
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

echo "== no display: the last resort =="
mark="$(log_mark)"
start_app tty --unit app-org.example.Tty-4711.scope --no-display
app_open tty https://example.com/no-display
expect_launch "without a display the last resort opens, with the URL alone" \
    google-chrome https://example.com/no-display
expect_equal "the handler had no DISPLAY" "" "$(meta display)"
log_since "$mark" | sed 's/^/     /'
expect_true "the log says why" log_has "$mark" "error: picker: no display: last resort"

echo "== a display nobody answers on: the last resort =="
kill "$WM_PID" "$XVFB_PID"
wait "$XVFB_PID" 2>/dev/null || true
mark="$(log_mark)"
start_app late --unit app-org.example.Late-4712.scope
app_open late https://example.com/dead-display
expect_launch "with a dead X server the last resort opens" google-chrome https://example.com/dead-display
expect_equal "the handler had the dead DISPLAY" "$DISPLAY" "$(meta display)"
log_since "$mark" | sed 's/^/     /'
expect_true "the log says why" log_has "$mark" "error: picker: the display cannot be opened: last resort"

expect_false "no URL ever ran a command" test -e /tmp/pwned

finish
