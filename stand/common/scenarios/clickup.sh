#!/bin/bash
# ClickUp: the desktop file of the app is desktop.desktop, so its app id is
# the meaningless "desktop". The class of the window says it is ClickUp and
# the title names the workspace.
set -eu
. "$(dirname "$(readlink -f "$0")")/_boot.sh"
boot

write_config <<'EOF'
[settings]
default = firefox

[browser firefox]
command = firefox

[browser chrome-initech]
command = google-chrome --profile-directory="Profile 15"

[rule clickup-initech]
app = desktop
window = clickup
title = \| Initech \(
browser = chrome-initech
EOF

start_app clickup --instance clickup --class ClickUp \
    --title "Overview | Project Management | Initech (Overview)" \
    --unit app-gnome-desktop-52114.scope --desktop desktop.desktop

echo "== workspace Initech =="
app_open clickup https://docs.google.com/document/d/1
expect_launch "ClickUp of Initech goes to its chrome profile" \
    google-chrome "--profile-directory=Profile 15" https://docs.google.com/document/d/1

echo "== another workspace =="
app_title clickup "Overview | Project Management | Elsewhere (Overview)"
app_open clickup https://docs.google.com/document/d/2
expect_launch "another workspace goes to the default browser" \
    firefox https://docs.google.com/document/d/2

echo "== another app with the same app id =="
# Same unit name and the title of Initech, but the window is not ClickUp
start_app other --instance notes --class Notes \
    --title "Overview | Project Management | Initech (Overview)" \
    --unit app-gnome-desktop-60001.scope --desktop desktop.desktop
app_open other https://docs.google.com/document/d/3
expect_launch "the window class keeps another 'desktop' app out" \
    firefox https://docs.google.com/document/d/3

finish
