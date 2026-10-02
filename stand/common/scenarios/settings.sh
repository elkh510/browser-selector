#!/bin/bash
# The settings window under Xvfb, driven with the keyboard: "Find browsers"
# adds what discovery finds to the config file, a rule added in the window is
# in the file and the next click obeys it, a rule with a regex that does not
# compile is refused and the file stays as it was.
set -eu
. "$(dirname "$(readlink -f "$0")")/_boot.sh"
. "$HARNESS_DIR/gui.sh"
boot

SETTINGS="Browser Selector"
SETTINGS_PID=""

# Profiles for discovery to find: two of Chrome, the one of Brave
mkdir -p "$XDG_CONFIG_HOME/google-chrome" "$XDG_CONFIG_HOME/BraveSoftware/Brave-Browser"
cat >"$XDG_CONFIG_HOME/google-chrome/Local State" <<'EOF2'
{"profile": {"info_cache": {"Profile 6": {"name": "main"}, "Profile 9": {"name": "Side"}},
             "last_used": "Profile 6"}}
EOF2
cat >"$XDG_CONFIG_HOME/BraveSoftware/Brave-Browser/Local State" <<'EOF2'
{"profile": {"info_cache": {"Profile 1": {"name": "home"}}, "last_used": "Profile 1"}}
EOF2

write_config <<'EOF2'
[settings]
default = fox

[browser fox]
name = Firefox, by hand
command = firefox --new-tab
EOF2

# sections: the section headers of the config, one line
sections() {
    grep '^\[' "$CONFIG" | tr '\n' ' ' | sed 's/ $//'
}

# section_has SECTION LINE: the section of the config has exactly this line
section_has() {
    awk -v header="[$1]" '$0 == header { inside = 1; next } /^\[/ { inside = 0 } inside' "$CONFIG" |
        grep -qxF -- "$2"
}

# config_becomes REGEX: true when a line of the config matches within 5 seconds
config_becomes() {
    for _ in $(seq 1 50); do
        grep -Eq "$1" "$CONFIG" && return 0
        sleep 0.1
    done
    return 1
}

# The window got the focus back from whatever was in front of it
to_settings() {
    WINDOW="$(window_id "$SETTINGS")"
    focus_window
}

echo "== the window opens =="
"$HANDLER" --settings >"$OUT_DIR/settings.log" 2>&1 &
SETTINGS_PID=$!
APP_PIDS="$APP_PIDS $SETTINGS_PID"
wait_window "$SETTINGS"
expect_true "browser-selector --settings shows a window under Xvfb" test -n "$WINDOW"
xprop -id "$WINDOW" WM_CLASS _NET_WM_NAME 2>/dev/null | sed 's/^/     /' || true
expect_true "opening it does not touch the config" grep -q "^name = Firefox, by hand$" "$CONFIG"

echo "== Find browsers =="
press alt+f
expect_true "the browsers of discovery are in the config file" config_becomes '^\[browser chrome-side\]$'
sed 's/^/     /' "$CONFIG"
expect_equal "every browser and profile found is a section, after the one that was there" \
    "[settings] [browser fox] [browser brave-home] [browser firefox] [browser chrome-main] [browser chrome-side]" \
    "$(sections)"
expect_true "a profile is a section with its name" section_has "browser chrome-side" "name = google-chrome - Side"
expect_true "and the command that opens it" \
    section_has "browser chrome-side" 'command = google-chrome --profile-directory="Profile 9"'
expect_true "a single profile gets its directory too" \
    section_has "browser brave-home" 'command = brave-browser --profile-directory="Profile 1"'
expect_true "the section that was there is not rewritten" section_has "browser fox" "command = firefox --new-tab"
expect_true "and keeps its name" section_has "browser fox" "name = Firefox, by hand"
expect_true "the default is not changed" grep -qx "default = fox" "$CONFIG"
expect_true "the file passes --check" "$HANDLER" --check
cp "$CONFIG" "$STAND/config.found"
press alt+f
sleep 1
expect_true "a second Find browsers adds nothing" cmp -s "$STAND/config.found" "$CONFIG"

echo "== a rule added in the window =="
press alt+2
press alt+r
wait_window "New rule"
expect_true "Add rule opens the form" test -n "$WINDOW"
type_text "docs"
press alt+u
type_text '^https://docs\.example\.com/'
# The list of browsers: the first one is selected, one down is the second
press alt+b
press Down
press Return
press alt+s
expect_true "Save closes the form" window_gone "New rule"
expect_true "the rule is in the config file" config_becomes '^\[rule docs\]$'
grep -A 3 '^\[rule docs\]$' "$CONFIG" | sed 's/^/     /'
expect_equal "with the regex as typed and the browser picked in the list" \
    '[rule docs] url = ^https://docs\.example\.com/ browser = brave-home' \
    "$(grep -A 2 '^\[rule docs\]$' "$CONFIG" | tr '\n' ' ' | sed 's/ $//')"
expect_true "the file passes --check" "$HANDLER" --check

echo "== the next click obeys it =="
start_app terminal --instance gnome-terminal-server --class Gnome-terminal --title "Terminal"
app_open terminal https://docs.example.com/page
expect_launch "a link the rule matches goes to its browser" \
    brave-browser "--profile-directory=Profile 1" https://docs.example.com/page
app_open terminal https://example.com/other
expect_launch "any other link goes to the default" firefox --new-tab https://example.com/other

echo "== a regex that does not compile =="
cp "$CONFIG" "$STAND/config.good"
to_settings
press alt+r
wait_window "New rule"
type_text "bad"
press alt+u
type_text '(unclosed'
press alt+s
sleep 1
expect_true "the config file is unchanged" cmp -s "$STAND/config.good" "$CONFIG"
expect_equal "the form stays open" "$WINDOW" "$(window_id "New rule")"
sed 's/^/     /' "$OUT_DIR/settings.log"
# What the form shows is not read back from the screen: the same text goes to
# the stderr of the window, and that is what is checked here
expect_true "the refusal names the section and the key, on stderr" \
    grep -q "not saved: \[rule bad\] url: bad regex" "$OUT_DIR/settings.log"
press Escape
expect_true "Esc closes the form" window_gone "New rule"
expect_true "the config file is still unchanged" cmp -s "$STAND/config.good" "$CONFIG"

echo "== a rule without a name =="
to_settings
press alt+r
wait_window "New rule"
press alt+s
sleep 1
expect_true "is refused too, the file is unchanged" cmp -s "$STAND/config.good" "$CONFIG"
press Escape
window_gone "New rule" || true

echo "== a browser added in the window =="
to_settings
press alt+1
press alt+b
wait_window "New browser"
expect_true "Add browser opens the form" test -n "$WINDOW"
type_text "work"
press alt+n
type_text "Chromium - Work & Co"
press alt+o
type_text 'chromium --profile-directory="Work Profile" {url}'
press Return
expect_true "Enter in a field saves and closes the form" window_gone "New browser"
expect_true "the browser is in the config file" config_becomes '^\[browser work\]$'
expect_true "with its name" section_has "browser work" "name = Chromium - Work & Co"
expect_true "and its command" section_has "browser work" 'command = chromium --profile-directory="Work Profile" {url}'
expect_true "the file passes --check" "$HANDLER" --check

echo "== the default, in the window =="
to_settings
press alt+3
press alt+e
# The list ends with "Ask every time": End goes there
press End
press Return
expect_true "Ask every time is written as default = ask" config_becomes '^default = ask$'
expect_true "the file passes --check" "$HANDLER" --check

echo "== a change that cannot be saved =="
# The directory of the config is read-only: the change is refused, and the
# list has to go back to what is saved. Only then is the same pick, made once
# more, a change again. A list that kept the refused pick would not save it.
cp "$CONFIG" "$STAND/config.ask"
chmod 555 "$(dirname "$CONFIG")"
to_settings
press alt+e
press Home
press Return
sleep 1
chmod 755 "$(dirname "$CONFIG")"
expect_true "the config file is unchanged" cmp -s "$STAND/config.ask" "$CONFIG"
expect_true "the refusal is on stderr" grep -q "not saved: .*Permission denied" "$OUT_DIR/settings.log"
press alt+e
press Home
press Return
expect_true "the list went back to the saved value: the same pick is saved now" config_becomes '^default = fox$'

echo "== the window is closed =="
to_settings
press ctrl+q
wait_exit "$SETTINGS_PID"
expect_equal "the handler exits with 0" 0 "$EXIT_CODE"
expect_equal "no window is left" "" "$(window_id "$SETTINGS")"
expect_false "GLib and GTK had nothing to complain about on stderr" \
    grep -Eq "CRITICAL|WARNING|assertion" "$OUT_DIR/settings.log"

finish
