#!/bin/bash
# Do the windows a click leads to come up focused under GNOME Shell, and does
# StartupNotify=true in the desktop entry of the handler change that. The
# browser here is a fake one with a real Wayland window, so the shell has a
# window to give the focus to or not. Each click comes from an app the user
# just clicked into, once from an X11 app and once from a native Wayland one,
# and goes once straight to the browser (a rule) and once through the picker.
set -eu
. "$GNOME50_DIR/scenarios/_boot.sh"
. "$GNOME50_DIR/gui.sh"
boot
start_gui

mkdir -p "$STAND/apps/browser"
mkfifo "$STAND/apps/browser/ctl"
# The title of the browser window is the link: one window per click to wait for
write_config <<CONFIG
[settings]
default = ask

[browser window]
name = A browser with a window
command = python3 $GNOME50_DIR/fake-app-wayland.py --ctl $STAND/apps/browser --app-id firefox --title {url}

[rule direct]
url = /direct
browser = window
CONFIG

PICKER="Open link"
start_app terminal --instance gnome-terminal-server --class Gnome-terminal --title "Terminal"
start_wayland_app editor --app-id org.gnome.TextEditor --title "notes.txt" \
    --unit app-gnome-org.gnome.TextEditor-5001.scope

# browser_focused WHAT URL: the window of the browser came and has the focus.
# Says what the launch left in its environment, then closes the browser.
browser_focused() {
    local pid
    wait_window "$2"
    if [ -n "$WINDOW" ] && wait_focus "$2" && [ -z "$(shell attention)" ]; then
        pass "$1"
    else
        fail "$1"
        echo "     window: ${WINDOW:-none}, focused: $(shell focused), attention: $(shell attention | tr '\n' ' ')"
    fi
    pid="$(window_field "$2" pid)"
    echo "     startup id in the environment of the browser:" \
        "$(tr '\0' '\n' <"/proc/$pid/environ" | grep -E '^(XDG_ACTIVATION_TOKEN|DESKTOP_STARTUP_ID)=' | tr '\n' ' ' || true)"
    kill "$pid"
    window_gone "$2" || true
}

# clicks TAG: the four clicks, with the desktop entry as it is now
clicks() {
    local source name title
    for source in "terminal:Terminal:an X11 app" "editor:notes.txt:a Wayland app"; do
        name="${source%%:*}"
        title="${source#*:}"
        title="${title%%:*}"
        focus "$title"
        WINDOW="$title"
        click_window 240 120
        app_cmd "$name" "open-now https://example.com/direct/$1/$name"
        browser_focused "a link of ${source##*:}, a rule decides: the browser window gets the focus" \
            "https://example.com/direct/$1/$name"
        focus "$title"
        WINDOW="$title"
        click_window 240 120
        app_cmd "$name" "open-now https://example.com/ask/$1/$name"
        wait_window "$PICKER"
        expect_true "a link of ${source##*:}, the picker asks: the picker gets the focus" wait_focus "$PICKER"
        press 1
        browser_focused "and the browser window picked there gets the focus" "https://example.com/ask/$1/$name"
    done
}

echo "== the desktop entry as installed, without StartupNotify =="
expect_false "the installed entry has no StartupNotify" grep -q "^StartupNotify" "$DESKTOP_ENTRY"
clicks plain

echo "== the same with StartupNotify=true, in the throwaway home =="
echo "StartupNotify=true" >>"$DESKTOP_ENTRY"
sleep 2
expect_equal "the entry is still what gio starts for a link" browser-selector.desktop "$(gio_default)"
clicks notify

finish
