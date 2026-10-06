#!/bin/bash
# The rules that need no window, under a Wayland session: `app` from the
# cgroup and from CHROME_DESKTOP, `url`, `probe` and the built-in
# @slack-workspace. No fake app here has an X11 window, the focus is on a
# native Wayland one.
set -eu
. "$GNOME50_DIR/scenarios/_boot.sh"
boot

write_config <<'CONFIG'
[settings]
default = firefox

[browser firefox]
command = firefox

[browser chrome-main]
command = google-chrome --profile-directory="Profile 6"

[browser chrome-acme]
command = google-chrome --profile-directory="Profile 9"

[browser brave-globex]
command = brave-browser --profile-directory=Default {url}

[rule cloudflare-acme]
url = ^https://acme\.cloudflareaccess\.com/
browser = chrome-acme

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

[rule slack-acme]
app = slack
probe = @slack-workspace
probe_match = ^Acme$
browser = chrome-acme

[rule slack-globex]
app = slack
probe = @slack-workspace
probe_match = ^Globex$
browser = brave-globex

[rule warp]
app = warp-taskbar
browser = chrome-main
CONFIG

# The fixture has the shape of the real file, in the throwaway config dir
select_workspace() {
    mkdir -p "$XDG_CONFIG_HOME/Slack/storage"
    cat >"$XDG_CONFIG_HOME/Slack/storage/root-state.json" <<JSON
{"workspaces": {"T1": {"name": "Acme"}, "T2": {"name": "Globex"}},
 "workspacesMeta": {"selectedWorkspaceId": "$1"}}
JSON
}

# A desktop in use: an unrelated native Wayland window has the focus
start_wayland_app terminal --app-id org.gnome.Ptyxis --title "dev@desktop: ~" \
    --unit app-gnome-org.gnome.Ptyxis-3001.scope
focus "dev@desktop: ~"
echo "     focused: $(shell focused)"
expect_equal "the focus is on a native Wayland window" wayland "$(focused_field client)"

# No window and no CHROME_DESKTOP: the tray app of netbird, a service of the
# warp client. And a Slack that was started by a slack:// link from a browser:
# it lives in the cgroup of that browser, only CHROME_DESKTOP says slack.
start_app netbird --unit app-gnome-netbird-14016.scope
start_app warp --unit warp-taskbar.service
start_app slack --unit 'app-gnome-google\x2dchrome-4321.scope' --desktop slack.desktop

echo "== app from the cgroup, with a probe command =="
echo globex >"$STAND/netbird.active"
: >"$OUT_DIR/probe.log"
app_open netbird "https://login.example.com/device?user_code=ABCD-EFGH"
expect_launch "netbird with the globex profile goes to brave" \
    brave-browser --profile-directory=Default "https://login.example.com/device?user_code=ABCD-EFGH"
expect_unit "the handler sat in the cgroup of the app" app-gnome-netbird-14016.scope
expect_equal "the probe ran once for that click" 1 "$(wc -l <"$OUT_DIR/probe.log")"
echo default >"$STAND/netbird.active"
app_open netbird "https://login.example.com/device?user_code=IJKL-MNOP"
expect_launch "netbird with the default profile goes to chrome" \
    google-chrome "--profile-directory=Profile 6" "https://login.example.com/device?user_code=IJKL-MNOP"

echo "== app from the cgroup of a service =="
app_open warp https://example.com/warp
expect_launch "warp-taskbar.service goes to its browser" \
    google-chrome "--profile-directory=Profile 6" https://example.com/warp

echo "== app from CHROME_DESKTOP, with @slack-workspace =="
select_workspace T1
app_open slack https://example.com/one
expect_launch "Slack on Acme goes to its chrome profile" \
    google-chrome "--profile-directory=Profile 9" https://example.com/one
expect_unit "the cgroup said chrome" 'app-gnome-google\x2dchrome-4321.scope'
expect_equal "CHROME_DESKTOP said slack" slack.desktop "$(meta chrome_desktop)"
select_workspace T2
app_open slack https://example.com/two
expect_launch "Slack on Globex goes to brave" \
    brave-browser --profile-directory=Default https://example.com/two

echo "== url, from any app =="
URL="https://acme.cloudflareaccess.com/cdn-cgi/access/cli?aud=1234&token=abc"
app_open warp "$URL"
expect_launch "the team login goes to its chrome profile, from a service" \
    google-chrome "--profile-directory=Profile 9" "$URL"
app_open terminal "$URL" open-now
expect_launch "and from a native Wayland app" google-chrome "--profile-directory=Profile 9" "$URL"

echo "== no rule =="
app_open terminal https://example.com/terminal open-now
expect_launch "an app no rule knows goes to the default browser" firefox https://example.com/terminal

finish
