#!/bin/bash
# A rule on the URL alone: the login page of a Cloudflare Access team goes to
# the browser of that team, whoever opens it
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

[rule cloudflare-acme]
url = ^https://acme\.cloudflareaccess\.com/
browser = chrome-acme
EOF

# An app no rule mentions: the warp client, a service without a window
start_app warp --unit warp-taskbar.service
start_app terminal --instance gnome-terminal-server --class Gnome-terminal --title "Terminal"

echo "== the team domain =="
URL="https://acme.cloudflareaccess.com/cdn-cgi/access/cli?aud=1234&token=abc"
app_open warp "$URL"
expect_launch "the team login goes to its chrome profile, from a service" \
    google-chrome "--profile-directory=Profile 6" "$URL"
app_open terminal "$URL"
expect_launch "and from a window" google-chrome "--profile-directory=Profile 6" "$URL"

echo "== URLs that only look like it =="
app_open warp "https://other.cloudflareaccess.com/cdn-cgi/access/cli"
expect_launch "another team goes to the default browser" \
    firefox "https://other.cloudflareaccess.com/cdn-cgi/access/cli"
app_open warp "https://example.com/?next=https://acme.cloudflareaccess.com/"
expect_launch "the domain inside a query goes to the default browser" \
    firefox "https://example.com/?next=https://acme.cloudflareaccess.com/"
app_open warp "https://acme.cloudflareaccess.com.example.org/"
expect_launch "the domain as a prefix of another goes to the default browser" \
    firefox "https://acme.cloudflareaccess.com.example.org/"

finish
