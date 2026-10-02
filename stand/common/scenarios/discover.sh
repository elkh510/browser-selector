#!/bin/bash
# --discover in a home that looks like the desktop of the user: every browser
# with a desktop entry, every profile of its `Local State` or `profiles.ini`,
# printed as [browser ...] sections. Nothing is changed and nothing started.
set -eu
. "$(dirname "$(readlink -f "$0")")/_boot.sh"
boot_home
install_handler

APPS="$XDG_DATA_HOME/applications"

# entry FILE NAME EXEC ICON: a browser the way its package installs it
entry() {
    cat >"$APPS/$1" <<EOF
[Desktop Entry]
Version=1.0
Name=$2
Name[ru]=Браузер
Exec=$3
Icon=$4
Type=Application
Categories=Network;WebBrowser;
MimeType=text/html;x-scheme-handler/http;x-scheme-handler/https;
Actions=new-window;

[Desktop Action new-window]
Name=New Window
Exec=${3% %*} --new-window
EOF
}

# local_state DIRECTORY LAST_USED "PROFILE DIRECTORY=NAME"...
local_state() {
    local dir="$XDG_CONFIG_HOME/$1" last="$2" cache="" sep="" profile
    shift 2
    for profile in "$@"; do
        cache="$cache$sep\"${profile%%=*}\": {\"name\": \"${profile#*=}\", \"avatar_icon\": \"x\"}"
        sep=", "
    done
    mkdir -p "$dir"
    printf '{"profile": {"info_cache": {%s}%s}}\n' "$cache" "${last:+, \"last_used\": \"$last\"}" >"$dir/Local State"
}

# The entries boot_home made are replaced by the ones of the desktop: two per
# Chromium based browser, as the packages of Chrome and Brave ship them
entry google-chrome.desktop "Google Chrome" "$HARNESS_DIR/stubs/google-chrome %U" google-chrome
entry com.google.Chrome.desktop "Google Chrome" "$HARNESS_DIR/stubs/google-chrome %U" google-chrome
entry brave-browser.desktop "Brave Web Browser" "$HARNESS_DIR/stubs/brave-browser %U" brave-browser
entry com.brave.Browser.desktop "Brave Web Browser" "$HARNESS_DIR/stubs/brave-browser %U" brave-browser
entry chromium-browser.desktop "Chromium Web Browser" "chromium %U" chromium
entry firefox.desktop "Firefox Web Browser" "firefox %u" firefox
# A browser that is not installed, and an entry with a quoted path and more field codes
entry vivaldi-stable.desktop "Vivaldi" "/opt/vivaldi/vivaldi %U" vivaldi
mkdir -p "$STAND/My Browser"
cp "$HARNESS_DIR/stubs/firefox" "$STAND/My Browser/browser"
entry my-browser.desktop "My Browser" "\"$STAND/My Browser/browser\" --class \"My Browser\" %i %c %u" /opt/my/icon.png
# Not browsers: a web app of a Chrome profile, a mail program
cat >"$APPS/chrome-aghbiahbpaijignceidepookljebhfak-Profile_6.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Google Drive
Exec=$HARNESS_DIR/stubs/google-chrome "--profile-directory=Profile 6" --app-id=aghbiahbpaijignceidepookljebhfak
Icon=chrome-aghbiahbpaijignceidepookljebhfak-Profile_6
NoDisplay=true
EOF
cat >"$APPS/mail.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Mail
Exec=firefox --compose %u
MimeType=x-scheme-handler/mailto;
EOF

local_state google-chrome "Profile 15" "Profile 15=acme" "Profile 6=main" "Profile 9=Side"
# Brave: one profile in Local State, and a Default directory that is still on disk
local_state BraveSoftware/Brave-Browser "Profile 1" "Profile 1=home"
mkdir -p "$XDG_CONFIG_HOME/BraveSoftware/Brave-Browser/Default"
local_state chromium "" "Default=Work"
mkdir -p "$HOME/.mozilla/firefox"
cat >"$HOME/.mozilla/firefox/profiles.ini" <<'EOF'
[Install4F96D1932A9F858E]
Default=oi5rkzwm.default-release
Locked=1

[Profile1]
Name=default
IsRelative=1
Path=famco1iw.default
Default=1

[Profile0]
Name=default-release
IsRelative=1
Path=oi5rkzwm.default-release

[General]
StartWithLastProfile=1
Version=2
EOF

cat >"$STAND/expected" <<EOF
[browser brave-home]
name = Brave Web Browser - home
icon = brave-browser
command = $HARNESS_DIR/stubs/brave-browser --profile-directory="Profile 1"

[browser chromium-work]
name = Chromium Web Browser - Work
icon = chromium
command = chromium --profile-directory=Default

[browser chrome-acme]
name = Google Chrome - acme
icon = google-chrome
command = $HARNESS_DIR/stubs/google-chrome --profile-directory="Profile 15"

[browser chrome-main]
name = Google Chrome - main
icon = google-chrome
command = $HARNESS_DIR/stubs/google-chrome --profile-directory="Profile 6"

[browser chrome-side]
name = Google Chrome - Side
icon = google-chrome
command = $HARNESS_DIR/stubs/google-chrome --profile-directory="Profile 9"

[browser firefox-default]
name = Firefox Web Browser - default
icon = firefox
command = firefox -P default

[browser firefox-default-release]
name = Firefox Web Browser - default-release
icon = firefox
command = firefox -P default-release

[browser browser]
name = My Browser
icon = /opt/my/icon.png
command = "$STAND/My Browser/browser" --class "My Browser"
EOF

# The home before and after: every file with its size and time of change
snapshot() {
    find "$HOME" -printf '%p %s %T@\n' | sort
}

echo "== --discover =="
cp "$CONFIG" "$STAND/config.before"
snapshot >"$STAND/home.before"
rc=0
"$HANDLER" --discover >"$OUT_DIR/discover.out" 2>"$OUT_DIR/discover.err" || rc=$?
sed 's/^/     /' "$OUT_DIR/discover.out"
expect_equal "--discover exits with 0" 0 "$rc"
expect_equal "and says nothing on stderr" "" "$(cat "$OUT_DIR/discover.err")"
if diff "$STAND/expected" "$OUT_DIR/discover.out" >"$OUT_DIR/discover.diff"; then
    pass "the sections are the browsers and profiles of the home, in the format of the config"
else
    fail "the sections are the browsers and profiles of the home, in the format of the config"
    sed 's/^/     /' "$OUT_DIR/discover.diff"
fi
expect_equal "one set of sections for the two entries of Chrome" \
    3 "$(grep -c '^\[browser chrome-' "$OUT_DIR/discover.out")"
expect_equal "one section for the two entries of Brave, its Default directory is not a profile" \
    1 "$(grep -c '^\[browser brave' "$OUT_DIR/discover.out")"
expect_false "the web app, the mail program and the own entries are not browsers" \
    grep -Eq "app-id|Google Drive|compose|browser-selector" "$OUT_DIR/discover.out"
expect_false "a browser whose program is not installed is left out" grep -qi vivaldi "$OUT_DIR/discover.out"

echo "== it changes nothing =="
snapshot >"$STAND/home.after"
expect_true "no file of the home was made, changed or removed" cmp -s "$STAND/home.before" "$STAND/home.after"
expect_true "the config is the one install.sh wrote" cmp -s "$STAND/config.before" "$CONFIG"
expect_equal "no browser was started" 0 "$(launches)"

echo "== the sections are a config =="
{
    printf '[settings]\ndefault = chrome-main\n\n'
    cat "$OUT_DIR/discover.out"
} >"$CONFIG"
rc=0
"$HANDLER" --check >"$OUT_DIR/check.log" 2>&1 || rc=$?
sed 's/^/     /' "$OUT_DIR/check.log"
expect_equal "with a default in front of them they pass --check" 0 "$rc"
make_default
before="$(launches)"
xdg-open https://example.com/discovered
wait_launch $((before + 1))
expect_launch "a link opens the profile the section names" \
    google-chrome "--profile-directory=Profile 6" https://example.com/discovered

finish
