#!/bin/bash
# Pictures of the picker and of every page of the settings window, taken by
# the shell, for a look at the tool in use: browsers with names and icons, a
# few rules, a log with real clicks. The PNG files stay next to the logs, in
# stand/out/gnome50/screenshots/.
set -eu
. "$GNOME50_DIR/scenarios/_boot.sh"
. "$GNOME50_DIR/gui.sh"
boot

# The icons the packages of the browsers put into hicolor. The browsers are
# not installed here, Papirus lends its drawings of them.
ICONS="$XDG_DATA_HOME/icons/hicolor/scalable/apps"
mkdir -p "$ICONS"
for icon in google-chrome brave-browser firefox; do
    cp -L "/usr/share/icons/Papirus/64x64/apps/$icon.svg" "$ICONS/$icon.svg"
done
start_gui

write_config <<'CONFIG'
[settings]
default = ask

[browser chrome-acme]
name = Google Chrome - acme
icon = google-chrome
command = google-chrome --profile-directory="Profile 15"

[browser chrome-main]
name = Google Chrome - main
icon = google-chrome
command = google-chrome --profile-directory="Profile 6"

[browser brave-home]
name = Brave Web Browser - home
icon = brave-browser
command = brave-browser --profile-directory="Profile 1"

[browser firefox-default]
name = Firefox Web Browser - default
icon = firefox
command = firefox -P default

[rule cloudflare-acme]
url = ^https://acme\.cloudflareaccess\.com/
browser = chrome-acme

[rule slack-acme]
app = slack
title = - Acme - Slack$
browser = chrome-acme

[rule netbird-globex]
app = netbird
probe = netbird profile list
probe_match = ^globex\s+✓
browser = brave-home
CONFIG

PICKER="Open link"
SETTINGS="Browser Selector"

# shot NAME: a picture of the focused window, checked to be a PNG of some size
shot() {
    sleep 0.7
    screenshot "$OUT_DIR/$1.png"
    if [ "$(head -c 4 "$OUT_DIR/$1.png" | tail -c 3)" = PNG ] && [ "$(wc -c <"$OUT_DIR/$1.png")" -gt 5000 ]; then
        pass "$1.png"
    else
        fail "$1.png"
    fi
}

echo "== clicks for the log =="
echo globex >"$STAND/netbird.active"
start_app slack --instance slack --class Slack --title "Threads - Acme - Slack" \
    --unit app-slack-2382881.scope --desktop slack.desktop
start_app netbird --unit app-gnome-netbird-14016.scope
start_wayland_app editor --app-id org.gnome.TextEditor --title "notes.txt" \
    --unit app-gnome-org.gnome.TextEditor-5001.scope
click slack "Threads - Acme - Slack" https://github.com/acme/infra/pull/42
expect_launch "the title rule of Slack" google-chrome "--profile-directory=Profile 15" \
    https://github.com/acme/infra/pull/42
app_open netbird "https://login.example.com/device?user_code=ABCD-EFGH"
expect_launch "the probe rule of netbird" brave-browser "--profile-directory=Profile 1" \
    "https://login.example.com/device?user_code=ABCD-EFGH"
app_open editor https://acme.cloudflareaccess.com/cdn-cgi/access/login open-now
expect_launch "the URL rule" google-chrome "--profile-directory=Profile 15" \
    https://acme.cloudflareaccess.com/cdn-cgi/access/login

echo "== the picker =="
focus "notes.txt"
BEFORE="$(launches)"
app_cmd editor "open-now https://docs.gnome.org/"
wait_window "$PICKER"
expect_true "the picker is shown and has the focus" wait_focus "$PICKER"
shot picker
press 4
wait_launch $((BEFORE + 1))
expect_launch "4 opens the fourth browser" firefox -P default https://docs.gnome.org/
focus "Threads - Acme - Slack"
app_title slack "general (Channel) - Globex - Slack"
app_cmd slack "open-now https://www.youtube.com/watch?v=dQw4w9WgXcQ"
wait_window "$PICKER"
expect_true "the picker over the app the link came from" wait_focus "$PICKER"
sleep 0.7
gdbus call --session -d org.gnome.Shell -o /org/gnome/Shell/Screenshot \
    -m org.gnome.Shell.Screenshot.Screenshot false false "$OUT_DIR/desktop.png" >/dev/null
expect_true "desktop.png" test -s "$OUT_DIR/desktop.png"
press Escape
window_gone "$PICKER" || true

echo "== the settings window =="
"$HANDLER" >"$OUT_DIR/settings.log" 2>&1 &
SETTINGS_PID=$!
APP_PIDS="$APP_PIDS $SETTINGS_PID"
wait_window "$SETTINGS"
expect_true "browser-selector without a URL shows the settings window with the focus" wait_focus "$SETTINGS"
wait_app_known || true
shell window "$SETTINGS" | sed 's/^/     /'
expect_equal "a native Wayland window, app id browser-selector" \
    "wayland browser-selector" "$(window_field "$SETTINGS" client) $(window_field "$SETTINGS" class)"
expect_equal "the shell takes it for the app of browser-selector.desktop" \
    "browser-selector.desktop" "$(window_field "$SETTINGS" app)"
press alt+1
shot settings-browsers
press alt+2
shot settings-rules
press alt+r
wait_window "New rule"
shot settings-rule-form
press Escape
window_gone "New rule" || true
press alt+3
shot settings-default
press alt+4
press alt+u
type_text "https://acme.cloudflareaccess.com/cdn-cgi/access/login"
press alt+a
type_text "slack"
press alt+t
shot settings-test
press alt+5
shot settings-logs
press alt+l
sleep 0.5
"$HANDLER" "https://acme.cloudflareaccess.com/cdn-cgi/access/login?next=1" >/dev/null 2>&1 || true
sleep 1
shot settings-logs-live
press ctrl+q
wait_exit "$SETTINGS_PID"
expect_equal "the window is closed with ctrl+q, exit code 0" 0 "$EXIT_CODE"
expect_equal "and printed nothing" "" "$(cat "$OUT_DIR/settings.log")"
expect_false "closing the window with Live pressed removes the live file" test -e "$XDG_RUNTIME_DIR/browser-selector.live"

ls -l "$OUT_DIR"/*.png | awk '{ print "     " $5, $NF }'
finish
