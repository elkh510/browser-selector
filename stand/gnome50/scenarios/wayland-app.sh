#!/bin/bash
# A native Wayland app opens a link: the handler is started the same way as
# for an X11 app and finds the same cgroup and CHROME_DESKTOP, so the rules on
# `app` route both alike
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

[browser brave-globex]
command = brave-browser --profile-directory=Default {url}

[rule slack]
app = slack
browser = chrome-acme

[rule editor]
app = org\.gnome\.TextEditor
browser = brave-globex
CONFIG

# The same app twice, as an X11 client and as a Wayland client, each in a
# scope of its own
start_app slack-x11 --instance slack --class Slack --title "X11 - Slack" \
    --unit app-slack-2382881.scope --desktop slack.desktop
start_wayland_app slack-wayland --app-id slack --title "Wayland - Slack" \
    --unit app-slack-2390000.scope --desktop slack.desktop

echo "== the X11 app =="
click slack-x11 "X11 - Slack" https://example.com/x11
echo "     focused: $(shell focused)"
expect_equal "the shell has the focus on an X11 client" x11 "$(focused_field client)"
expect_launch "the app rule sends it to chrome" \
    google-chrome "--profile-directory=Profile 6" https://example.com/x11
echo "     handler:  $LAST_META"
x11_parent="$(meta ppid)"

echo "== the Wayland app =="
click slack-wayland "Wayland - Slack" https://example.com/wayland
echo "     focused: $(shell focused)"
expect_equal "the shell has the focus on a Wayland client" wayland "$(focused_field client)"
expect_true "the fake app is a Wayland client of GTK" \
    grep -qx "display backend: GdkWaylandDisplay" "$OUT_DIR/app-slack-wayland.log"
expect_launch "the same rule sends it to chrome" \
    google-chrome "--profile-directory=Profile 6" https://example.com/wayland
echo "     fake app: pid $(app_pid slack-wayland), $LAST_EVENT"
echo "     handler:  $LAST_META"
expect_unit "the handler sits in the cgroup of the Wayland app" app-slack-2390000.scope
expect_equal "the handler has the CHROME_DESKTOP of the app" slack.desktop "$(meta chrome_desktop)"
expect_equal "the handler has the same parent as for the X11 app: init, the double fork" \
    "1 $x11_parent" "$(meta ppid) $x11_parent"

echo "== the cgroup alone, no CHROME_DESKTOP =="
start_wayland_app editor --app-id org.gnome.TextEditor --title "notes.txt" \
    --unit app-gnome-org.gnome.TextEditor-5001.scope
click editor "notes.txt" https://example.com/editor
expect_launch "a GNOME app is known by its unit" \
    brave-browser --profile-directory=Default https://example.com/editor
expect_equal "the handler had no CHROME_DESKTOP" "" "$(meta chrome_desktop)"

echo "== CHROME_DESKTOP alone, the cgroup of another app =="
start_wayland_app slack-link --app-id slack --title "From a link - Slack" \
    --unit 'app-gnome-google\x2dchrome-4321.scope' --desktop slack.desktop
click slack-link "From a link - Slack" https://example.com/link
expect_launch "Slack in the cgroup of a browser is known by CHROME_DESKTOP" \
    google-chrome "--profile-directory=Profile 6" https://example.com/link

echo "== an app no rule knows =="
start_wayland_app terminal --app-id org.gnome.Ptyxis --title "dev@desktop: ~" \
    --unit app-gnome-org.gnome.Ptyxis-3001.scope
click terminal "dev@desktop: ~" https://example.com/terminal
expect_launch "another Wayland app goes to the default browser" firefox https://example.com/terminal

finish
