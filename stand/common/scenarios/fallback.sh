#!/bin/bash
# A click always opens something: an app no rule knows, a browser that is not
# installed, a config that is broken or not there at all
set -eu
. "$(dirname "$(readlink -f "$0")")/_boot.sh"
boot

# The default browser carries an argument, so it cannot be mistaken for the
# last resort, which is started with the URL alone
write_config <<'EOF'
[settings]
default = firefox-main

[browser firefox-main]
command = firefox --new-tab

[browser ghost]
command = no-such-browser --profile-directory=Default

[rule ghost-app]
app = ghostapp
browser = ghost
EOF

start_app unknown --instance gnome-terminal-server --class Gnome-terminal --title "Terminal" \
    --unit app-org.example.Unknown-4711.scope
start_app ghost --unit app-ghostapp-777.scope

echo "== an app no rule knows =="
app_open unknown https://example.com/unknown
expect_launch "an unknown app goes to the default browser" \
    firefox --new-tab https://example.com/unknown

echo "== the browser of the rule is not installed =="
mark="$(log_mark)"
app_open ghost https://example.com/ghost
expect_launch "a missing program falls back to the default browser" \
    firefox --new-tab https://example.com/ghost
log_since "$mark" | sed 's/^/     /'
expect_true "the log names the missing program" log_has "$mark" "error.*no-such-browser"

echo "== the default browser is not installed either =="
write_config <<'EOF'
[settings]
default = ghost

[browser ghost]
command = no-such-browser --profile-directory=Default
EOF
app_open unknown https://example.com/no-default
expect_launch "the last resort opens, with the URL alone" \
    google-chrome https://example.com/no-default

echo "== a config with a rule for a browser that is not defined =="
write_config_raw <<'EOF'
[settings]
default = firefox-main

[browser firefox-main]
command = firefox --new-tab

[rule broken]
app = slack
browser = nowhere
EOF
rc=0
"$HANDLER" --check >"$OUT_DIR/check-broken.log" 2>&1 || rc=$?
sed 's/^/     /' "$OUT_DIR/check-broken.log"
expect_equal "--check rejects it with exit code 2" 2 "$rc"
mark="$(log_mark)"
app_open unknown https://example.com/broken
expect_launch "a config that is not valid opens the last resort" \
    google-chrome https://example.com/broken
log_since "$mark" | sed 's/^/     /'
expect_true "the error is in the log" log_has "$mark" "error.*nowhere"

echo "== a config that is not INI =="
write_config_raw <<'EOF'
default = firefox-main
this is not a config
EOF
mark="$(log_mark)"
app_open unknown https://example.com/garbage
expect_launch "a config that cannot be parsed opens the last resort" \
    google-chrome https://example.com/garbage
log_since "$mark" | sed 's/^/     /'
expect_true "the error is in the log" log_has "$mark" "error"

echo "== no config =="
rm "$CONFIG"
app_open unknown https://example.com/no-config
expect_launch "no config opens the last resort" google-chrome https://example.com/no-config

echo "== the last resort goes down its list =="
rm "$HARNESS_DIR/stubs/google-chrome"
app_open unknown https://example.com/no-chrome
expect_launch "without google-chrome it is brave-browser" \
    brave-browser https://example.com/no-chrome

finish
