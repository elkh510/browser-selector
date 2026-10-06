#!/bin/bash
# Runs inside the container: delegates a cgroup subtree to the stand user,
# drops root and hands over to the scenario.
set -eu

STAND_UID="${STAND_UID:-1000}"
CGROUP_MODE="${CGROUP_MODE:-real}"
USER_CG="/sys/fs/cgroup/user.slice/user-$STAND_UID.slice/user@$STAND_UID.service"

# The only step that needs root. The subtree gets the layout of a systemd
# user session and is handed to the stand user the way systemd delegates
# user@.service, so a fake app can make a scope and move itself into it. The
# scenario itself starts in a scope of its own: a process can only be moved
# by someone who may write the cgroup.procs of the common ancestor.
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
export REPO_DIR=/repo
export OUT_DIR="/out/${SCENARIO%.sh}"
export CGROUP_MODE
export CGROUP_APP_SLICE="$USER_CG/app.slice"

rm -rf "$STAND" "$OUT_DIR"
mkdir -p "$STAND" "$OUT_DIR"

# Writable copy of the scenario helpers: the mount is read-only and the
# executable bits of the checkout are not to be relied on
cp -r /stand/common "$HARNESS_DIR"
chmod +x "$HARNESS_DIR"/stubs/* "$HARNESS_DIR"/scenarios/*.sh

# gio tells the session bus about every launch, as on the desktop
set +e
dbus-run-session -- bash "$HARNESS_DIR/scenarios/$SCENARIO" 2>&1 \
    | tee "$OUT_DIR/scenario.log"
exit "${PIPESTATUS[0]}"
