#!/bin/bash
# install.sh and uninstall.sh in the throwaway home: the files land where the
# contract says, the first config comes from discovery, a plain install
# leaves the default browser alone, --set-default switches it and remembers
# the previous one, uninstall puts that one back and removes only what
# install.sh put there
set -eu
. "$(dirname "$(readlink -f "$0")")/_boot.sh"
boot_home

LIB="$XDG_DATA_HOME/browser-selector"
OLD_ENTRY="$XDG_DATA_HOME/applications/browser-selector-settings.desktop"
PREVIOUS="$XDG_STATE_HOME/browser-selector/previous-default"

# run LOG COMMAND...: output to $OUT_DIR/LOG, exit code in RC
run() {
    local log="$OUT_DIR/$1"
    shift
    RC=0
    "$@" >"$log" 2>&1 || RC=$?
    sed 's/^/     /' "$log"
}

echo "== before: firefox is the default browser =="
xdg-settings set default-web-browser firefox.desktop
expect_equal "the home starts with firefox as the default browser" firefox.desktop "$(default_browser)"

echo "== install.sh =="
run install-1.log bash "$REPO_DIR/install.sh"
expect_equal "install.sh exits with 0" 0 "$RC"
expect_true "the handler and the windows are in the data directory" \
    test -f "$LIB/browser_selector.py" -a -f "$LIB/browser_selector_gui.py"
expect_equal "the handler with mode 755" 755 "$(stat -c %a "$LIB/browser_selector.py" 2>/dev/null)"
expect_equal "~/.local/bin/browser-selector is a link to it" \
    "$LIB/browser_selector.py" "$(readlink "$HANDLER" 2>/dev/null)"
expect_equal "its first line makes python run isolated" \
    "#!/usr/bin/python3 -I" "$(head -n 1 "$LIB/browser_selector.py")"
expect_true "the rest is the handler of the checkout" \
    cmp -s <(tail -n +2 "$REPO_DIR/browser_selector.py") <(tail -n +2 "$LIB/browser_selector.py")
expect_true "the windows are the ones of the checkout" \
    cmp -s "$REPO_DIR/browser_selector_gui.py" "$LIB/browser_selector_gui.py"
expect_true "the desktop entry is in the applications dir" test -f "$DESKTOP_ENTRY"
expect_false "there is no second entry for the settings" test -e "$OLD_ENTRY"
expect_equal "Exec of the handler has the absolute path" \
    "Exec=$HANDLER %u" "$(grep '^Exec=' "$DESKTOP_ENTRY" 2>/dev/null)"
expect_false "the entry is shown in the app grid" grep -q "NoDisplay" "$DESKTOP_ENTRY"
expect_true "the handler runs: --version" "$HANDLER" --version
expect_equal "the default browser is not changed" firefox.desktop "$(default_browser)"
expect_false "no previous default is recorded" test -e "$PREVIOUS"
expect_true "the command to switch is printed" \
    grep -qF "xdg-settings set default-web-browser browser-selector.desktop" "$OUT_DIR/install-1.log"
expect_true "and the command to go back" \
    grep -qF "xdg-settings set default-web-browser firefox.desktop" "$OUT_DIR/install-1.log"

echo "== the first config =="
sed 's/^/     /' "$CONFIG"
expect_equal "the config is written from discovery: every browser found and no rule" \
    "[settings] [browser brave] [browser firefox] [browser chrome]" \
    "$(grep '^\[' "$CONFIG" | tr '\n' ' ' | sed 's/ $//')"
expect_true "the default is the browser that was the system default" grep -qx "default = firefox" "$CONFIG"
expect_true "it passes --check" "$HANDLER" --check

echo "== the environment of an app does not reach the handler =="
mkdir -p "$STAND/poison"
for module in configparser shlex json sitecustomize; do
    echo "raise SystemExit('the PYTHONPATH of the app was used')" >"$STAND/poison/$module.py"
done
run isolated.log env PYTHONPATH="$STAND/poison" PYTHONHOME=/nonexistent "$HANDLER" --check
expect_equal "with a PYTHONPATH and a PYTHONHOME that break python the handler still runs" 0 "$RC"

echo "== a second install keeps the config =="
cat >"$CONFIG" <<'EOF2'
[settings]
default = mine

[browser mine]
command = brave-browser --profile-directory="Profile 1"
EOF2
cp "$CONFIG" "$STAND/config.mine"
run install-2.log bash "$REPO_DIR/install.sh"
expect_equal "install.sh exits with 0" 0 "$RC"
expect_true "the config of the user is untouched" cmp -s "$STAND/config.mine" "$CONFIG"

echo "== install.sh --set-default =="
SECONDS=0
run install-3.log bash "$REPO_DIR/install.sh" --set-default
# Not a check, a fact worth seeing: xdg-settings 1.1.3 adds text/html, about
# and unknown to an entry that lacks them and sleeps 4 seconds after each
echo "     took ${SECONDS}s, the installed entry now has:"
echo "     $(grep '^MimeType=' "$DESKTOP_ENTRY" 2>/dev/null || true)"
expect_equal "install.sh --set-default exits with 0" 0 "$RC"
expect_equal "the handler is the default browser" browser-selector.desktop "$(default_browser)"
expect_equal "also for gio, which is what opens links" browser-selector.desktop "$(gio_default)"
expect_equal "the previous default is recorded" firefox.desktop "$(cat "$PREVIOUS" 2>/dev/null)"
before="$(launches)"
xdg-open https://example.com/installed
wait_launch $((before + 1))
expect_launch "a link goes through the handler and the config of the user" \
    brave-browser "--profile-directory=Profile 1" https://example.com/installed

# xdg-settings makes a default browser the handler of text/html as well, so
# more than http and https links arrive: a click on those opens something too
echo "<html></html>" >"$STAND/page.html"
before="$(launches)"
xdg-open "$STAND/page.html"
wait_launch $((before + 1))
expect_launch "a local HTML file goes through the handler to a browser too" \
    brave-browser "--profile-directory=Profile 1" "$STAND/page.html"

echo "== --set-default once more =="
run install-4.log bash "$REPO_DIR/install.sh" --set-default
expect_equal "install.sh --set-default exits with 0" 0 "$RC"
expect_equal "the recorded default is still the real browser" firefox.desktop "$(cat "$PREVIOUS" 2>/dev/null)"

echo "== uninstall.sh =="
mkdir -p "$LIB/__pycache__"
touch "$LIB/__pycache__/browser_selector_gui.cpython-310.pyc"
run uninstall-1.log bash "$REPO_DIR/uninstall.sh"
expect_equal "uninstall.sh exits with 0" 0 "$RC"
expect_equal "the previous default browser is back" firefox.desktop "$(default_browser)"
expect_equal "also for gio" firefox.desktop "$(gio_default)"
expect_false "the link in ~/.local/bin is gone" test -e "$HANDLER" -o -L "$HANDLER"
expect_false "the data directory is gone" test -e "$LIB"
expect_false "the desktop entry is gone" test -e "$DESKTOP_ENTRY"
expect_true "the config is left" cmp -s "$STAND/config.mine" "$CONFIG"
expect_true "the log is left, and uninstall.sh says so" grep -qF "Kept:    $HANDLER_LOG" "$OUT_DIR/uninstall-1.log"
expect_true "it is still there" test -s "$HANDLER_LOG"
expect_false "mimeapps.list does not mention the handler" \
    grep -q browser-selector "$XDG_CONFIG_HOME/mimeapps.list"
before="$(launches)"
xdg-open https://example.com/uninstalled
wait_launch $((before + 1))
expect_launch "a link goes straight to firefox again" firefox https://example.com/uninstalled

echo "== uninstall.sh when the handler is not the default =="
run install-5.log bash "$REPO_DIR/install.sh"
xdg-settings set default-web-browser brave-browser.desktop
run uninstall-2.log bash "$REPO_DIR/uninstall.sh"
expect_equal "uninstall.sh exits with 0" 0 "$RC"
expect_equal "the default browser is left alone" brave-browser.desktop "$(default_browser)"
expect_false "the handler is gone" test -e "$HANDLER"
expect_false "the desktop entry is gone" test -e "$DESKTOP_ENTRY"

echo "== uninstall.sh when the previous default cannot be put back =="
run install-6.log bash "$REPO_DIR/install.sh" --set-default
rm "$PREVIOUS"
run uninstall-3.log bash "$REPO_DIR/uninstall.sh"
expect_equal "uninstall.sh refuses with a non-zero exit code" 1 "$RC"
expect_true "nothing is removed: the handler, the windows, the entries" \
    test -L "$HANDLER" -a -f "$LIB/browser_selector.py" -a -f "$LIB/browser_selector_gui.py" \
    -a -f "$DESKTOP_ENTRY"
expect_equal "the handler is still the default browser" browser-selector.desktop "$(default_browser)"
before="$(launches)"
xdg-open https://example.com/still-there
wait_launch $((before + 1))
expect_launch "and a link still opens" brave-browser "--profile-directory=Profile 1" https://example.com/still-there
run uninstall-4.log bash "$REPO_DIR/uninstall.sh" --force
expect_equal "uninstall.sh --force exits with 0" 0 "$RC"
expect_false "and removes it all" test -e "$HANDLER" -o -e "$LIB" -o -e "$DESKTOP_ENTRY" -o -e "$OLD_ENTRY"
expect_true "but not the config" cmp -s "$STAND/config.mine" "$CONFIG"
xdg-settings set default-web-browser firefox.desktop

echo "== a ~/.local/bin/browser-selector that install.sh did not make =="
run install-7.log bash "$REPO_DIR/install.sh"
rm "$HANDLER"
printf '#!/bin/sh\necho mine\n' >"$HANDLER"
chmod +x "$HANDLER"
run uninstall-5.log bash "$REPO_DIR/uninstall.sh"
expect_equal "uninstall.sh exits with 0" 0 "$RC"
expect_equal "the file is left alone" mine "$("$HANDLER")"
expect_false "the rest is removed" test -e "$LIB" -o -e "$DESKTOP_ENTRY" -o -e "$OLD_ENTRY"
run install-8.log bash "$REPO_DIR/install.sh"
expect_equal "install.sh over a handler of the first layout exits with 0" 0 "$RC"
expect_equal "and puts the link in its place" "$LIB/browser_selector.py" "$(readlink "$HANDLER" 2>/dev/null)"
run uninstall-6.log bash "$REPO_DIR/uninstall.sh"

echo "== a home directory with a space =="
# Everything the boot derived from HOME, for a second home
export HOME="$STAND/home of dev"
export XDG_CONFIG_HOME="$HOME/.config" XDG_DATA_HOME="$HOME/.local/share" XDG_STATE_HOME="$HOME/.local/state"
export XDG_CACHE_HOME="$HOME/.cache"
HANDLER="$HOME/.local/bin/browser-selector"
DESKTOP_ENTRY="$XDG_DATA_HOME/applications/browser-selector.desktop"
CONFIG="$XDG_CONFIG_HOME/browser-selector/config.ini"
HANDLER_LOG="$XDG_STATE_HOME/browser-selector/log"
mkdir -p "$XDG_CONFIG_HOME/browser-selector" "$XDG_DATA_HOME/applications"
cat >"$CONFIG" <<'EOF2'
[settings]
default = spaced

[browser spaced]
command = chromium --from-the-home-with-a-space
EOF2
# A browser that is the default there, so that a switch has something to write down
sed 's/^Exec=.*/Exec=firefox %u/' "$STAND/home/.local/share/applications/firefox.desktop" \
    >"$XDG_DATA_HOME/applications/firefox.desktop"
xdg-settings set default-web-browser firefox.desktop
run install-9.log bash "$REPO_DIR/install.sh"
expect_equal "install.sh exits with 0" 0 "$RC"
echo "     $(grep '^Exec=' "$DESKTOP_ENTRY" 2>/dev/null || true)"
expect_equal "Exec is quoted the way the Desktop Entry specification asks" \
    "Exec=\"$HANDLER\" %u" "$(grep '^Exec=' "$DESKTOP_ENTRY" 2>/dev/null)"
expect_true "the handler runs from there" "$HANDLER" --check
make_default
before="$(launches)"
xdg-open https://example.com/space
wait_launch $((before + 1))
expect_launch "gio starts the handler through the quoted entry" \
    chromium --from-the-home-with-a-space https://example.com/space
# xdg-settings 1.1.3 takes the first word of Exec for the program, quote
# included, so it does not know a quoted entry: the switch says so
rm "$XDG_CONFIG_HOME/mimeapps.list"
xdg-settings set default-web-browser firefox.desktop
run install-10.log bash "$REPO_DIR/install.sh" --set-default
expect_equal "install.sh --set-default cannot switch there and exits with 1" 1 "$RC"
expect_true "it says why" grep -q "reserved character in its path cannot be registered" "$OUT_DIR/install-10.log"
expect_equal "the default browser is the one it was" firefox.desktop "$(default_browser)"
expect_false "and no previous default is written down for a switch that did not happen" \
    test -e "$XDG_STATE_HOME/browser-selector/previous-default"

finish
