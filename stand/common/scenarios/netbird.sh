#!/bin/bash
# Netbird opens its login page on its own: no window says anything, the app
# id comes from the cgroup alone and the active profile from a probe,
# `netbird profile list`
set -eu
. "$(dirname "$(readlink -f "$0")")/_boot.sh"
boot

write_config <<'EOF'
[settings]
default = firefox

[browser firefox]
command = firefox

[browser chrome-main]
command = google-chrome --profile-directory="Profile 6"

[browser brave-globex]
command = brave-browser --profile-directory=Default {url}

[rule netbird-globex]
app = netbird
probe = netbird profile list
probe_match = ^globex\s+✓
browser = brave-globex

[rule netbird-default]
app = netbird
probe = netbird profile list
probe_match = ^default\s+✓
browser = chrome-main
EOF

# No window and no CHROME_DESKTOP: the tray app of netbird has neither. An
# unrelated window has the focus, as on a desktop in use.
start_app terminal --instance gnome-terminal-server --class Gnome-terminal --title "Terminal"
start_app netbird --unit app-gnome-netbird-14016.scope

echo "== profile globex is active =="
echo globex >"$STAND/netbird.active"
netbird profile list | sed 's/^/     /'
: >"$OUT_DIR/probe.log"
app_open netbird "https://login.example.com/device?user_code=ABCD-EFGH"
expect_launch "the globex profile goes to brave" \
    brave-browser --profile-directory=Default "https://login.example.com/device?user_code=ABCD-EFGH"
expect_equal "the probe ran once for that click" 1 "$(wc -l <"$OUT_DIR/probe.log")"

echo "== profile default is active =="
echo default >"$STAND/netbird.active"
netbird profile list | sed 's/^/     /'
: >"$OUT_DIR/probe.log"
app_open netbird "https://login.example.com/device?user_code=IJKL-MNOP"
expect_launch "the default profile goes to chrome" \
    google-chrome "--profile-directory=Profile 6" "https://login.example.com/device?user_code=IJKL-MNOP"
expect_equal "two rules with the same probe, one run" 1 "$(wc -l <"$OUT_DIR/probe.log")"

echo "== the same link from another app =="
: >"$OUT_DIR/probe.log"
app_open terminal "https://login.example.com/device?user_code=QRST-UVWX"
expect_launch "another app goes to the default browser" \
    firefox "https://login.example.com/device?user_code=QRST-UVWX"
expect_equal "and the probe is not run for it" 0 "$(wc -l <"$OUT_DIR/probe.log")"

finish
