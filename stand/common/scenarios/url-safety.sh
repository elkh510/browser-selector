#!/bin/bash
# A URL is data: whatever is in it, the browser gets it as one unchanged
# argument and nothing in it is ever executed or expanded. The log never has
# more than scheme and host. An argument that looks like an option is refused.
set -eu
. "$(dirname "$(readlink -f "$0")")/_boot.sh"
boot

write_config <<'EOF'
[settings]
default = firefox

[browser firefox]
command = firefox

[browser brave-app]
command = brave-browser --profile-directory="Profile 1" --app={url}

[rule app-mode]
app = appmode
browser = brave-app
EOF

# One app whose browser gets the URL appended, one whose browser has it
# inside an argument
start_app plain --instance gnome-terminal-server --class Gnome-terminal --title "Terminal"
start_app appmode --unit app-appmode-4242.scope

rm -f /tmp/pwned /tmp/pwned2 /tmp/pwned3

try() {
    echo "     $2"
    app_open plain "$2"
    expect_launch "$1: one unchanged argument" firefox "$2"
    app_open appmode "$2"
    expect_launch "$1: unchanged inside an argument" \
        brave-browser "--profile-directory=Profile 1" "--app=$2"
}

echo "== shell metacharacters =="
try "command substitution, & and ;" 'https://example.com/?a=$(touch /tmp/pwned)&b=;x'

echo "== spaces and quotes =="
try "spaces, quotes and backticks" \
    'https://example.com/a b?q="double"&r='\''single'\''&s=`touch /tmp/pwned2`'

echo "== field codes, the placeholder, a pipe and a backslash =="
try "%u, {url}, | and \\" 'https://example.com/?x=%u%U%f&y={url}&z=$HOME|touch /tmp/pwned3;\'

echo "== nothing was executed =="
expect_false "no file was created by a URL" ls /tmp/pwned /tmp/pwned2 /tmp/pwned3

echo "== the log =="
mark="$(log_mark)"
app_open plain 'https://user:hunter2@login.example.com/callback?token=SECRET-TOKEN-123#fragment'
expect_launch "a login link reaches the browser in full" \
    firefox 'https://user:hunter2@login.example.com/callback?token=SECRET-TOKEN-123#fragment'
log_since "$mark" | sed 's/^/     /'
expect_true "the log has scheme and host" log_has "$mark" "https://login\.example\.com"
expect_false "the log has no token, password or path" log_has "$mark" "SECRET|hunter2|callback"

echo "== an argument that starts with - =="
# Called directly: xdg-open and gio refuse such an argument themselves
before="$(launches)"
refused() {
    local rc=0
    "$HANDLER" "$@" >>"$OUT_DIR/refused.log" 2>&1 || rc=$?
    echo "$rc"
}
expect_equal "--incognito alone is refused with exit code 1" 1 "$(refused --incognito)"
expect_equal "an option before the URL is refused" 1 \
    "$(refused --user-data-dir=/tmp/x https://example.com/)"
expect_equal "an option after the URL is refused" 1 \
    "$(refused https://example.com/ --no-sandbox)"
expect_equal "a single dash option is refused" 1 "$(refused -P https://example.com/)"
sleep 1
expect_equal "and no browser was started" "$before" "$(launches)"

finish
