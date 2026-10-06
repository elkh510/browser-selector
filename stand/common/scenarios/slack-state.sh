#!/bin/bash
# The same decision as slack.sh, taken from the state file of Slack instead of
# the window: the built-in probe @slack-workspace reads the selected
# workspace from Slack/storage/root-state.json. No rule looks at a title.
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

[browser brave-globex]
command = brave-browser --profile-directory=Default {url}

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
EOF

# The fixture has the shape of the real file, in the throwaway config dir
select_workspace() {
    mkdir -p "$XDG_CONFIG_HOME/Slack/storage"
    cat >"$XDG_CONFIG_HOME/Slack/storage/root-state.json" <<EOF
{"workspaces": {"T1": {"name": "Acme"}, "T2": {"name": "Globex"}},
 "workspacesMeta": {"selectedWorkspaceId": "$1"}}
EOF
}

# A title that says nothing, and a Slack that was started by a slack:// link
# from a browser: it lives in the cgroup of that browser, only CHROME_DESKTOP
# still says slack (docs/design.md, known limits)
start_app slack --instance slack --class Slack --title "Slack" \
    --unit 'app-gnome-google\x2dchrome-4321.scope' --desktop slack.desktop

echo "== selected workspace T2, Globex =="
select_workspace T2
app_open slack https://example.com/one
expect_launch "Globex goes to brave" \
    brave-browser --profile-directory=Default https://example.com/one

echo "== selected workspace T1, Acme =="
select_workspace T1
app_open slack https://example.com/two
expect_launch "Acme goes to chrome" \
    google-chrome "--profile-directory=Profile 6" https://example.com/two

echo "== a selected workspace that is not in the file =="
select_workspace T9
app_open slack https://example.com/three
expect_launch "an unknown workspace goes to the default browser" firefox https://example.com/three

echo "== no state file =="
rm "$XDG_CONFIG_HOME/Slack/storage/root-state.json"
app_open slack https://example.com/four
expect_launch "a missing state file goes to the default browser" firefox https://example.com/four

echo "== a state file that is not JSON =="
echo "{ not json" >"$XDG_CONFIG_HOME/Slack/storage/root-state.json"
app_open slack https://example.com/five
expect_launch "a broken state file goes to the default browser" firefox https://example.com/five

finish
