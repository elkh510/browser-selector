#!/bin/bash
# Shared boot of the GNOME 50 stand, sourced by its scenarios. Everything of
# common/scenarios/_boot.sh (throwaway home, install.sh of the checkout, the
# handler as default browser, fake apps, assertions) with a headless GNOME
# Shell on Wayland in place of Xvfb and openbox.
# Expects: STAND, HARNESS_DIR, GNOME50_DIR, REPO_DIR, OUT_DIR, CGROUP_MODE
# (gnome50/inner.sh)
set -eu

. "$HARNESS_DIR/scenarios/_boot.sh"

# The session of Ubuntu 26.04 on top of what the common boot exports.
# gnome-session 50.1 still sets GNOME_DESKTOP_SESSION_ID=this-is-deprecated
# (the string is in its binary), and XDG_CURRENT_DESKTOP is still ubuntu:GNOME
# (DesktopNames=ubuntu;GNOME in the session file of ubuntu-session).
# WAYLAND_DISPLAY, DISPLAY and XAUTHORITY come from the shell, start_shell
# exports them.
export XDG_SESSION_TYPE=wayland
unset WAYLAND_DISPLAY DISPLAY XAUTHORITY

SHELL_LOG="$OUT_DIR/shell.log"
MONITOR="${MONITOR:-1280x800}"

shell() { python3 "$GNOME50_DIR/shell.py" "$@"; }

cleanup() {
    local pid
    # The apps go before the shell, the shell before the session bus
    for pid in $APP_PIDS ${SHELL_PID:-}; do
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    done
    cp "$HANDLER_LOG" "$OUT_DIR/handler.log" 2>/dev/null || true
    cp "$CONFIG" "$OUT_DIR/config.ini" 2>/dev/null || true
}

# --- boot --------------------------------------------------------------

# start_shell [--no-x11]: a headless GNOME Shell with one virtual monitor.
# Without the option the shell brings its Xwayland, as the desktop does.
start_shell() {
    mkdir -p "$XDG_DATA_HOME/gnome-shell/extensions"
    cp -r "$GNOME50_DIR/unsafe-ext" "$XDG_DATA_HOME/gnome-shell/extensions/unsafe@test"
    gsettings set org.gnome.shell enabled-extensions "['unsafe@test']"
    gsettings set org.gnome.shell disable-user-extensions false

    gnome-shell --wayland --headless --virtual-monitor "$MONITOR" "$@" >"$SHELL_LOG" 2>&1 &
    SHELL_PID=$!

    local up=""
    for _ in $(seq 1 90); do
        if gdbus introspect --session -d org.gnome.Shell -o /org/gnome/Shell >/dev/null 2>&1; then
            up=1
            break
        fi
        sleep 1
    done
    if [ -z "$up" ]; then
        echo "the shell did not come up:" >&2
        tail -n 30 "$SHELL_LOG" >&2
        exit 1
    fi

    # The shell comes up in the overview and stays there, and a window that
    # opens under the overview does not get the focus. The shell answers on
    # the bus a moment before it can evaluate, hence the loop.
    local hidden=""
    for _ in $(seq 1 100); do
        if [ "$(shell eval "Main.overview.hide(); Main.overview.visible" 2>/dev/null)" = false ]; then
            hidden=1
            break
        fi
        sleep 0.2
    done
    if [ -z "$hidden" ]; then
        echo "the shell did not leave the overview:" >&2
        tail -n 30 "$SHELL_LOG" >&2
        exit 1
    fi

    WAYLAND_DISPLAY="$(cd "$XDG_RUNTIME_DIR" && ls -d wayland-* 2>/dev/null | grep -v '\.lock$' | head -n 1)"
    export WAYLAND_DISPLAY
    if [ -z "$WAYLAND_DISPLAY" ]; then
        echo "the shell has no Wayland socket in $XDG_RUNTIME_DIR" >&2
        exit 1
    fi

    case " $* " in
        *" --no-x11 "*) ;;
        *) find_xwayland ;;
    esac
    echo "== $(gnome-shell --version), headless, WAYLAND_DISPLAY=$WAYLAND_DISPLAY DISPLAY=${DISPLAY:-} =="
}

# The public X11 display of the session, the one ordinary X11 clients get, and
# the cookie mutter made for it. On the desktop both are in the environment
# of every app.
find_xwayland() {
    local number=""
    for _ in $(seq 1 100); do
        number="$(sed -n 's/.*Using public X11 display :\([0-9]*\).*/\1/p' "$SHELL_LOG" | head -n 1)"
        XAUTHORITY="$(ls "$XDG_RUNTIME_DIR"/.mutter-Xwaylandauth.* 2>/dev/null | head -n 1)"
        [ -n "$number" ] && [ -n "$XAUTHORITY" ] && break
        sleep 0.1
    done
    if [ -z "$number" ] || [ -z "$XAUTHORITY" ]; then
        echo "the shell has no X11 display:" >&2
        tail -n 30 "$SHELL_LOG" >&2
        exit 1
    fi
    export DISPLAY=":$number" XAUTHORITY
}

boot() {
    boot_home
    start_shell "$@"
    install_handler
    make_default
}

# --- fake apps ---------------------------------------------------------

# start_wayland_app NAME [options of fake-app-wayland.py]: start_app of the
# common boot for the native Wayland fake app
start_wayland_app() {
    local name="$1" dir="$STAND/apps/$1"
    shift
    mkdir -p "$dir"
    mkfifo "$dir/ctl"
    : >"$dir/events"
    python3 "$GNOME50_DIR/fake-app-wayland.py" --ctl "$dir" "$@" >"$OUT_DIR/app-$name.log" 2>&1 &
    echo $! >"$dir/pid"
    APP_PIDS="$APP_PIDS $!"
    for _ in $(seq 1 200); do
        grep -q "^ready" "$dir/events" && return 0
        sleep 0.1
    done
    echo "fake app $name did not come up:" >&2
    cat "$OUT_DIR/app-$name.log" >&2
    exit 1
}

# --- focus -------------------------------------------------------------

# focus TITLE: the shell gives the focus to the window with this title. The
# fake apps do not take it themselves: one way for X11 and Wayland windows.
focus() {
    if ! shell focus "$1"; then
        fail "the shell gives the focus to: $1"
    fi
}

# One field of the focused window as the shell sees it: client, id, instance,
# class, title
focused_field() {
    shell focused | tr '\t' '\n' | sed -n "s/^$1=//p"
}

# expect_unit WHAT UNIT: the handler of the last launch sat in this cgroup
expect_unit() {
    if [ "$CGROUP_MODE" = real ]; then
        expect_equal "$1" "$2" "$(meta unit)"
    else
        echo "SKIP $1: CGROUP=file, no real cgroups"
    fi
}

# click NAME TITLE URL: the window gets the focus, then its app opens the link
click() {
    focus "$2"
    app_open "$1" "$3" open-now
}
