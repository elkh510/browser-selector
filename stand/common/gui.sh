#!/bin/bash
# Helpers of the scenarios that drive a window, sourced after _boot.sh. A
# window is driven the way a user does it: xdotool presses keys, types and
# clicks through the X server, the window never knows it is under test.

# GTK 4 has no GL under Xvfb, and the container has no accessibility bus
export GSK_RENDERER=cairo
export GTK_A11Y=none

WINDOW=""

# window_id TITLE: the id of the visible window with exactly this title,
# nothing when there is none
window_id() {
    xdotool search --onlyvisible --name "^$1\$" 2>/dev/null | head -n 1 || true
}

# wait_window TITLE [TENTHS]: waits for the window, gives it the focus and
# leaves its id in WINDOW; WINDOW is empty when the window does not come
wait_window() {
    WINDOW=""
    for _ in $(seq 1 "${2:-100}"); do
        WINDOW="$(window_id "$1")"
        [ -n "$WINDOW" ] && break
        sleep 0.1
    done
    [ -n "$WINDOW" ] || return 0
    focus_window
}

# The keys of xdotool go to the focused window: wait until the window
# manager says it is this one, then let the window draw itself
focus_window() {
    xdotool windowactivate "$WINDOW" 2>/dev/null || true
    for _ in $(seq 1 50); do
        [ "$(xdotool getactivewindow 2>/dev/null || true)" = "$WINDOW" ] && break
        sleep 0.1
    done
    sleep 0.3
}

# window_gone TITLE: true when the window is gone within 5 seconds
window_gone() {
    for _ in $(seq 1 50); do
        [ -z "$(window_id "$1")" ] && return 0
        sleep 0.1
    done
    return 1
}

# press KEY...: key presses for the focused window, xdotool names: 2, Return,
# Escape, alt+f
press() {
    xdotool key --delay 50 "$@"
    sleep 0.3
}

# type_text TEXT: typed into the focused entry
type_text() {
    xdotool type --delay 20 "$1"
    sleep 0.3
}

# click_window X Y: a click at a point of WINDOW; a negative number counts
# from the right or the bottom edge
click_window() {
    local x="$1" y="$2" width height
    width="$(xdotool getwindowgeometry --shell "$WINDOW" | sed -n 's/^WIDTH=//p')"
    height="$(xdotool getwindowgeometry --shell "$WINDOW" | sed -n 's/^HEIGHT=//p')"
    [ "$x" -lt 0 ] && x=$((width + x))
    [ "$y" -lt 0 ] && y=$((height + y))
    xdotool mousemove --window "$WINDOW" "$x" "$y"
    sleep 0.3
    xdotool click 1
    sleep 0.3
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
