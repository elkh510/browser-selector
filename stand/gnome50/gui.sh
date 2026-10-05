#!/bin/bash
# Helpers of the scenarios that drive a window, sourced after scenarios/_boot.sh.
# The Wayland twin of common/gui.sh: xdotool cannot see or reach a native
# Wayland window, so the shell is asked where the windows are, and the keys
# and clicks come from a virtual keyboard and pointer of its seat (shell.py).
# The window never knows it is under test.

# No GPU in the container
export GSK_RENDERER=cairo

# The title of the window the last wait_window found, empty when it did not come
WINDOW=""

# start_gui: call it after boot and before the first window. A headless shell
# has a seat without a keyboard and a pointer: the devices are made here, as
# a desktop has them from the start. A fresh pointer sits at 0,0, which is
# the hot corner, and its first motion only gets half way (1200,0 for
# 1200,760): together that opens the overview, and under the overview no
# window gets the focus or a key. So the hot corner is off, the pointer is
# moved twice and both the pointer and the overview are checked. The icon
# theme and the font are the ones the Ubuntu session sets.
start_gui() {
    gsettings set org.gnome.desktop.interface enable-hot-corners false
    gsettings set org.gnome.desktop.interface icon-theme Yaru
    gsettings set org.gnome.desktop.interface font-name "Ubuntu Sans 11"
    gsettings set org.gnome.desktop.interface monospace-font-name "Ubuntu Sans Mono 11"
    shell keys shift
    shell move 1200 760
    shell move 1200 760
    if [ "$(shell pointer)" != "1200 760" ] || [ "$(shell eval "Main.overview.visible")" != false ]; then
        echo "the input devices of the stand did not come up: pointer at $(shell pointer)," \
            "overview $(shell eval "Main.overview.visible")" >&2
        exit 1
    fi
    shell attention
}

# The shell reads a desktop entry a moment after it is installed: wait until
# it knows the one of the settings window, which is what it files the windows
# of the handler under
wait_app_known() {
    for _ in $(seq 1 100); do
        [ "$(shell eval "!!imports.gi.Shell.AppSystem.get_default().lookup_app('browser-selector.desktop')")" = true ] && return 0
        sleep 0.1
    done
    return 1
}

# window_id TITLE: the title when the shell has a window with exactly this
# title, nothing when there is none
window_id() {
    shell window "$1" >/dev/null 2>&1 && printf '%s\n' "$1" || true
}

# window_field TITLE FIELD: client, class, title, pid, app, app_name, rect, focused
window_field() {
    shell window "$1" 2>/dev/null | tr '\t' '\n' | sed -n "s/^$2=//p"
}

# wait_window TITLE [TENTHS]: waits for the window and leaves its title in
# WINDOW. The focus is left alone: whether a new window gets it is what some
# scenarios are about.
wait_window() {
    WINDOW=""
    for _ in $(seq 1 "${2:-100}"); do
        WINDOW="$(window_id "$1")"
        [ -n "$WINDOW" ] && break
        sleep 0.1
    done
    # Let the window draw itself
    [ -z "$WINDOW" ] || sleep 0.3
}

# wait_focus TITLE [TENTHS]: true when the shell has the focus on this window
# within the time, without anybody giving it
wait_focus() {
    for _ in $(seq 1 "${2:-30}"); do
        [ "$(focused_field title)" = "$1" ] && return 0
        sleep 0.1
    done
    return 1
}

# window_gone TITLE: true when the window is gone within 5 seconds
window_gone() {
    for _ in $(seq 1 50); do
        [ -z "$(window_id "$1")" ] && return 0
        sleep 0.1
    done
    return 1
}

# press KEY...: key presses for the focused window: 2, Return, Escape, alt+f
press() {
    shell keys "$@"
    sleep 0.3
}

# type_text TEXT: typed into the focused entry
type_text() {
    shell type "$1"
    sleep 0.3
}

# click_window X Y: a click at a point of WINDOW; a negative number counts
# from the right or the bottom edge
click_window() {
    local x="$1" y="$2" left top width height
    IFS=, read -r left top width height <<<"$(window_field "$WINDOW" rect)"
    [ "$x" -lt 0 ] && x=$((width + x))
    [ "$y" -lt 0 ] && y=$((height + y))
    shell click $((left + x)) $((top + y))
    sleep 0.3
}

# screenshot FILE: a PNG of the focused window, taken by the shell
screenshot() {
    gdbus call --session -d org.gnome.Shell -o /org/gnome/Shell/Screenshot \
        -m org.gnome.Shell.Screenshot.ScreenshotWindow true false false "$1" >/dev/null
}

# wait_exit PID [TENTHS]: waits for a background process of this shell and
# leaves its exit code in EXIT_CODE, 124 when it is still running after the
# wait. Not for $(...): only the shell that started a process can wait for it.
wait_exit() {
    EXIT_CODE=124
    for _ in $(seq 1 "${2:-100}"); do
        if ! kill -0 "$1" 2>/dev/null; then
            EXIT_CODE=0
            wait "$1" || EXIT_CODE=$?
            return 0
        fi
        sleep 0.1
    done
}
