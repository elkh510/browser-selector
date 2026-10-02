#!/bin/bash
# Shared boot of the stand, sourced by the scenarios.
# Expects: STAND, HARNESS_DIR, REPO_DIR, OUT_DIR, CGROUP_MODE (x11/inner.sh)
set -eu

# The stand installs a handler and makes it the default browser. That must
# never reach a real home: only the container of x11/run.sh gets past this.
if [ "${STAND_CONTAINER:-}" != 1 ] || [ ! -f /.dockerenv ]; then
    echo "run the scenarios through stand/x11/run.sh, never directly" >&2
    exit 1
fi

. "$HARNESS_DIR/launch-line.sh"

export HOME="$STAND/home"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_DATA_HOME="$HOME/.local/share"
export XDG_STATE_HOME="$HOME/.local/state"
export XDG_CACHE_HOME="$HOME/.cache"
export XDG_RUNTIME_DIR="$STAND/run"
export LANG=C.UTF-8
# The session of the desktop of the user. xdg-open 1.1.3 does not know
# "ubuntu:GNOME", it finds GNOME through GNOME_DESKTOP_SESSION_ID, which the
# session of Ubuntu 22.04 still exports.
export XDG_CURRENT_DESKTOP=ubuntu:GNOME
export GNOME_DESKTOP_SESSION_ID=this-is-deprecated
export DESKTOP_SESSION=ubuntu
export PATH="$HARNESS_DIR/stubs:$PATH"
unset BROWSER CHROME_DESKTOP BROWSER_SELECTOR_CONFIG BROWSER_SELECTOR_CGROUP_FILE

HANDLER="$HOME/.local/bin/browser-selector"
DESKTOP_ENTRY="$XDG_DATA_HOME/applications/browser-selector.desktop"
CONFIG="$XDG_CONFIG_HOME/browser-selector/config.ini"
HANDLER_LOG="$XDG_STATE_HOME/browser-selector/log"
LAUNCH_LOG="$OUT_DIR/launch.log"
META_LOG="$OUT_DIR/launch-meta.log"

PASSED=0
FAILED=0
APP_PIDS=""
LAST_LAUNCH=""
LAST_META=""
LAST_EVENT=""

pass() { PASSED=$((PASSED + 1)); echo "PASS $*"; }
fail() { FAILED=$((FAILED + 1)); echo "FAIL $*"; }

# The last line of every scenario: its exit status is the one of the scenario
finish() {
    echo "== $PASSED passed, $FAILED failed =="
    [ "$FAILED" -eq 0 ]
}

cleanup() {
    local pid
    for pid in $APP_PIDS ${WM_PID:-} ${XVFB_PID:-}; do
        kill "$pid" 2>/dev/null || true
    done
    cp "$HANDLER_LOG" "$OUT_DIR/handler.log" 2>/dev/null || true
    cp "$CONFIG" "$OUT_DIR/config.ini" 2>/dev/null || true
}
trap cleanup EXIT

# --- boot --------------------------------------------------------------

# The throwaway home, with desktop entries for the fake browsers: something
# has to be the default browser before the handler takes over. The entries
# name every type xdg-settings registers a browser for, so it has nothing to
# add to them and does not sleep.
boot_home() {
    rm -rf "$HOME" "$XDG_RUNTIME_DIR"
    mkdir -p "$XDG_CONFIG_HOME" "$XDG_DATA_HOME/applications" \
        "$XDG_STATE_HOME" "$XDG_CACHE_HOME" "$XDG_RUNTIME_DIR" "$STAND/apps"
    chmod 700 "$XDG_RUNTIME_DIR"
    local browser
    for browser in google-chrome brave-browser firefox; do
        cat >"$XDG_DATA_HOME/applications/$browser.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$browser
Exec=$browser %U
MimeType=text/html;x-scheme-handler/http;x-scheme-handler/https;x-scheme-handler/about;x-scheme-handler/unknown;
Categories=Network;WebBrowser;
EOF
    done
    echo "== cgroup: $CGROUP_MODE, $(sed -n 's/^0:://p' /proc/self/cgroup) =="
}

start_x() {
    export DISPLAY=:99
    Xvfb "$DISPLAY" -screen 0 1280x800x24 -nolisten tcp >"$OUT_DIR/xvfb.log" 2>&1 &
    XVFB_PID=$!
    for _ in $(seq 1 100); do
        xdpyinfo >/dev/null 2>&1 && break
        sleep 0.1
    done

    # _NET_ACTIVE_WINDOW is kept by the window manager, there is no focused
    # window for the handler to find without one
    openbox --sm-disable >"$OUT_DIR/openbox.log" 2>&1 &
    WM_PID=$!
    for _ in $(seq 1 100); do
        xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null | grep -q "window id" && break
        sleep 0.1
    done
}

install_handler() {
    if ! bash "$REPO_DIR/install.sh" >"$OUT_DIR/install.log" 2>&1 || [ ! -x "$HANDLER" ]; then
        echo "install.sh did not install $HANDLER:" >&2
        cat "$OUT_DIR/install.log" >&2
        exit 1
    fi
}

# The handler becomes the default browser of the throwaway home, and only of
# that one: mimeapps.list in $XDG_CONFIG_HOME. Written by hand, because
# xdg-settings 1.1.3 sleeps 4 seconds for every MIME type it adds to a local
# desktop entry, 12 seconds per scenario. The way through xdg-settings is
# what install.sh --set-default does, and install.sh the scenario covers it.
make_default() {
    cat >"$XDG_CONFIG_HOME/mimeapps.list" <<'EOF'
[Default Applications]
x-scheme-handler/http=browser-selector.desktop
x-scheme-handler/https=browser-selector.desktop
EOF
    if [ "$(gio_default)" != browser-selector.desktop ]; then
        echo "the handler did not become the default browser: $(gio_default)" >&2
        exit 1
    fi
}

# What gio open starts for a link, the last word on the default browser
gio_default() {
    gio mime x-scheme-handler/https | sed -n '1s/.*: //p'
}

default_browser() { xdg-settings get default-web-browser; }

boot() {
    boot_home
    start_x
    install_handler
    make_default
}

# --- config ------------------------------------------------------------

# Config from stdin, as is
write_config_raw() {
    mkdir -p "$(dirname "$CONFIG")"
    cat >"$CONFIG"
}

# Config from stdin. A scenario that is about rules must not pass or fail
# because of a typo in its own config, so the handler has a look first.
write_config() {
    write_config_raw
    if "$HANDLER" --check >"$OUT_DIR/check.log" 2>&1; then
        pass "the config of the scenario passes --check"
    else
        fail "the config of the scenario passes --check"
        sed 's/^/     /' "$OUT_DIR/check.log"
    fi
}

# --- fake apps ---------------------------------------------------------

# start_app NAME [options of fake-app.py]
start_app() {
    local name="$1" dir="$STAND/apps/$1"
    shift
    mkdir -p "$dir"
    mkfifo "$dir/ctl"
    : >"$dir/events"
    python3 "$HARNESS_DIR/fake-app.py" --ctl "$dir" "$@" >"$OUT_DIR/app-$name.log" 2>&1 &
    echo $! >"$dir/pid"
    APP_PIDS="$APP_PIDS $!"
    for _ in $(seq 1 100); do
        grep -q "^ready" "$dir/events" && return 0
        sleep 0.1
    done
    echo "fake app $name did not come up:" >&2
    cat "$OUT_DIR/app-$name.log" >&2
    exit 1
}

app_pid() { cat "$STAND/apps/$1/pid"; }

# app_cmd NAME COMMAND: one command of fake-app.py, waits until it is done
# and leaves its event in LAST_EVENT
app_cmd() {
    local dir="$STAND/apps/$1" before
    before="$(wc -l <"$dir/events")"
    printf '%s\n' "$2" >"$dir/ctl"
    for _ in $(seq 1 400); do
        [ "$(wc -l <"$dir/events")" -gt "$before" ] && break
        sleep 0.1
    done
    LAST_EVENT="$(tail -n 1 "$dir/events")"
    case "$LAST_EVENT" in
        error*) echo "     fake app $1: $LAST_EVENT" ;;
    esac
}

app_title() { app_cmd "$1" "title $2"; }
app_focus() { app_cmd "$1" "focus"; }

# --- launches ----------------------------------------------------------

launches() {
    if [ -f "$LAUNCH_LOG" ]; then wc -l <"$LAUNCH_LOG"; else echo 0; fi
}

# wait_launch N: waits for launch number N and leaves its line in LAST_LAUNCH
# and its who-and-where line in LAST_META, both empty when nothing shows up
wait_launch() {
    LAST_LAUNCH=""
    LAST_META=""
    for _ in $(seq 1 "${2:-100}"); do
        if [ "$(launches)" -ge "$1" ]; then
            LAST_LAUNCH="$(sed -n "${1}p" "$LAUNCH_LOG")"
            LAST_META="$(sed -n "${1}p" "$META_LOG")"
            return 0
        fi
        sleep 0.1
    done
}

# app_open NAME URL [open|open-now]: the app opens the link through xdg-open,
# the launch it leads to ends up in LAST_LAUNCH
app_open() {
    local before
    before="$(launches)"
    app_cmd "$1" "${3:-open} $2"
    wait_launch $((before + 1))
}

# One field of LAST_META: pid, ppid, parent, unit, chrome_desktop, display
meta() {
    printf '%s\n' "$LAST_META" | tr '\t' '\n' | sed -n "s/^$1=//p"
}

# --- assertions --------------------------------------------------------

# expect_launch WHAT PROGRAM [ARG...]: the last launch is exactly this argv
expect_launch() {
    local what="$1" want
    shift
    want="$(launch_line "$@")"
    if [ "$LAST_LAUNCH" = "$want" ]; then
        pass "$what"
    else
        fail "$what"
        echo "     want: $want"
        echo "     got:  ${LAST_LAUNCH:-nothing was launched}"
    fi
}

# expect_equal WHAT WANT GOT
expect_equal() {
    if [ "$2" = "$3" ]; then
        pass "$1"
    else
        fail "$1"
        echo "     want: $2"
        echo "     got:  $3"
    fi
}

# expect_true WHAT COMMAND [ARG...]
expect_true() {
    local what="$1"
    shift
    if "$@" >/dev/null 2>&1; then pass "$what"; else fail "$what"; fi
}

# expect_false WHAT COMMAND [ARG...]
expect_false() {
    local what="$1"
    shift
    if "$@" >/dev/null 2>&1; then fail "$what"; else pass "$what"; fi
}

# Lines the handler added to its log since the mark was taken
log_mark() {
    if [ -f "$HANDLER_LOG" ]; then wc -l <"$HANDLER_LOG"; else echo 0; fi
}
log_since() {
    [ -f "$HANDLER_LOG" ] && tail -n "+$(($1 + 1))" "$HANDLER_LOG" || true
}

# log_has MARK REGEX: one of the lines since the mark matches
log_has() { log_since "$1" | grep -Eq "$2"; }
