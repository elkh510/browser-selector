#!/bin/bash
# One Slack, two workspaces: the title of the focused Slack window names the
# workspace, and each workspace has its own browser and profile
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
title = - Acme - Slack$
browser = chrome-acme

[rule slack-globex]
app = slack
title = - Globex - Slack$
browser = brave-globex
EOF

start_app slack --instance slack --class Slack --title "Threads - Acme - Slack" \
    --unit app-slack-2382881.scope --desktop slack.desktop

echo "== workspace Acme =="
app_open slack https://github.com/acme/repo/pull/1
expect_launch "Acme goes to chrome, the profile name with a space is one argument" \
    google-chrome "--profile-directory=Profile 6" https://github.com/acme/repo/pull/1

echo "== workspace Globex, same window =="
app_title slack "general (Channel) - Globex - Slack"
app_open slack https://github.com/globex/repo/pull/2
expect_launch "Globex goes to brave" \
    brave-browser --profile-directory=Default https://github.com/globex/repo/pull/2

echo "== a title with quotes and non-ASCII characters =="
app_title slack 'Jürgen "the boss" \ • DM - Globex - Slack'
app_open slack https://github.com/globex/repo/pull/3
expect_launch "the title survives xprop, Globex goes to brave" \
    brave-browser --profile-directory=Default https://github.com/globex/repo/pull/3

echo "== a workspace no rule knows =="
app_title slack "general (Channel) - Somewhere Else - Slack"
app_open slack https://example.com/
expect_launch "another workspace goes to the default browser" firefox https://example.com/

echo "== back to Acme =="
app_title slack "Threads - Acme - Slack"
app_open slack https://example.com/again
expect_launch "the title is read on every click" \
    google-chrome "--profile-directory=Profile 6" https://example.com/again

finish
