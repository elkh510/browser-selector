#!/bin/bash
# Runs inside the container: delegates a cgroup subtree to the stand user,
# drops root, starts the two buses a GNOME session has and hands over to the
# scenario.
set -eu

STAND_UID="${STAND_UID:-1000}"
CGROUP_MODE="${CGROUP_MODE:-real}"
USER_CG="/sys/fs/cgroup/user.slice/user-$STAND_UID.slice/user@$STAND_UID.service"

# The only step that needs root, the same as in x11/inner.sh: the subtree
# gets the layout of a systemd user session and is handed to the stand user,
# so a fake app can make a scope and move itself into it.
if [ "$(id -u)" = 0 ]; then
    if [ "$CGROUP_MODE" = real ]; then
        if ! mkdir -p "$USER_CG/app.slice/app-stand-runner-1.scope"; then
            echo "/sys/fs/cgroup is not writable: Docker 28 or newer is needed," >&2
            echo "or run with CGROUP=file" >&2
            exit 1
        fi
        chown -R "$STAND_UID:$STAND_UID" "$USER_CG"
        echo $$ >"$USER_CG/app.slice/app-stand-runner-1.scope/cgroup.procs"
    fi
    exec setpriv --reuid "$STAND_UID" --regid "$STAND_UID" --clear-groups \
        --inh-caps=-all --bounding-set=-all --no-new-privs bash "$0"
fi

export STAND_CONTAINER=1
export STAND=/tmp/stand
export HARNESS_DIR="$STAND/harness"
export GNOME50_DIR="$STAND/gnome50"
export REPO_DIR=/repo
export OUT_DIR="/out/${SCENARIO%.sh}"
export CGROUP_MODE
export CGROUP_APP_SLICE="$USER_CG/app.slice"

# The throwaway home of common/scenarios/_boot.sh, set here already: the
# session bus hands its own environment to everything it activates, dconf
# for one, and that must not be the home of root.
export HOME="$STAND/home"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_DATA_HOME="$HOME/.local/share"
export XDG_STATE_HOME="$HOME/.local/state"
export XDG_CACHE_HOME="$HOME/.cache"
export XDG_RUNTIME_DIR="$STAND/run"
# No accessibility bus in the container, GTK would wait for it
export NO_AT_BRIDGE=1
export GTK_A11Y=none
# The fake browsers, also for what the bus activates: the portal starts the
# handler from its own environment
export PATH="$HARNESS_DIR/stubs:$PATH"

rm -rf "$STAND" "$OUT_DIR"
mkdir -p "$STAND" "$OUT_DIR"

# Writable copies of the scenario helpers: the mount is read-only and the
# executable bits of the checkout are not to be relied on
cp -r /stand/common "$HARNESS_DIR"
cp -r /stand/gnome50 "$GNOME50_DIR"
chmod +x "$HARNESS_DIR"/stubs/* "$HARNESS_DIR"/scenarios/*.sh "$GNOME50_DIR"/scenarios/*.sh

# The shell talks to logind and friends on the system bus at startup. A
# private one is enough, the calls just fail with ServiceUnknown.
cat >"$STAND/system-bus.conf" <<CONF
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>system</type>
  <listen>unix:path=$STAND/system-bus</listen>
  <policy context="default">
    <allow user="*"/>
    <allow own="*"/>
    <allow send_type="method_call"/>
    <allow send_type="signal"/>
    <allow receive_type="method_return"/>
    <allow receive_type="error"/>
    <allow receive_type="signal"/>
  </policy>
</busconfig>
CONF
dbus-daemon --config-file="$STAND/system-bus.conf" --fork
export DBUS_SYSTEM_BUS_ADDRESS="unix:path=$STAND/system-bus"

# The session bus and everything it activates (dconf, gvfs, the portal) write
# to session-bus.log, the scenario alone to the terminal and scenario.log.
# The timeout is for a shell that does not come up: it must not hang the run.
set +e
timeout 600 dbus-run-session -- \
    bash -c 'exec bash "$0" 2>&3 3>&-' "$GNOME50_DIR/scenarios/$SCENARIO" \
    3>&1 2>"$OUT_DIR/session-bus.log" | tee "$OUT_DIR/scenario.log"
exit "${PIPESTATUS[0]}"
