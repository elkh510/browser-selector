#!/bin/bash
# Runs the scenarios of the GNOME 50 stand, each one in a fresh container.
#
#   bash stand/gnome50/run.sh [scenario.sh|all]   scenario from gnome50/scenarios,
#                                                 all of them by default
#
# Exits non-zero when a scenario failed. A headless GNOME Shell 50 (Wayland,
# with its Xwayland) runs inside the container: no window on the display of
# the host, nothing installed or registered there. The handler under test is
# taken from REPO (default: the checkout this stand lives in), mounted
# read-only and installed into a throwaway home inside the container. The logs
# land in stand/out/gnome50/<scenario>/.
#
#   CGROUP=file bash stand/gnome50/run.sh ...     for a Docker older than 28: no
#                                                 real cgroups, the unit name goes
#                                                 through BROWSER_SELECTOR_CGROUP_FILE
set -eu

STAND_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
REPO="${REPO:-$(cd "$STAND_DIR/.." && pwd)}"
IMAGE="${IMAGE:-browser-selector-stand:gnome50}"
OUT="${OUT:-$STAND_DIR/out/gnome50}"
CGROUP="${CGROUP:-real}"
WHAT="${1:-all}"

if [ "$WHAT" = all ]; then
    SCENARIOS=()
    for file in "$STAND_DIR"/gnome50/scenarios/*.sh; do
        name="$(basename "$file")"
        [ "$name" = _boot.sh ] || SCENARIOS+=("$name")
    done
else
    SCENARIOS=("$(basename "$WHAT")")
    if [ ! -f "$STAND_DIR/gnome50/scenarios/${SCENARIOS[0]}" ]; then
        echo "no scenario ${SCENARIOS[0]} in $STAND_DIR/gnome50/scenarios" >&2
        exit 2
    fi
fi

# Docker turns a missing bind mount source into a directory owned by root
mkdir -p "$OUT"

docker build -q -t "$IMAGE" --build-arg "UID=$(id -u)" "$STAND_DIR/gnome50" >/dev/null

# The fake apps sit in cgroups named like the units of real apps, see
# x11/run.sh: a private cgroup namespace plus writable-cgroups (Docker 28 and
# up), no capability is added and nothing is privileged.
CGROUP_ARGS=()
if [ "$CGROUP" = real ]; then
    CGROUP_ARGS=(--cgroupns=private --security-opt writable-cgroups=true)
fi

# --network none also keeps the Xwayland of the shell to the container: its
# display number and its abstract socket are not the ones of the host
FAILED=()
for scenario in "${SCENARIOS[@]}"; do
    echo "=== $scenario ==="
    if ! docker run --rm --init \
            --network none \
            "${CGROUP_ARGS[@]}" \
            -e SCENARIO="$scenario" \
            -e CGROUP_MODE="$CGROUP" \
            -e STAND_UID="$(id -u)" \
            -v "$STAND_DIR:/stand:ro" \
            -v "$REPO:/repo:ro" \
            -v "$OUT:/out" \
            "$IMAGE" \
            bash /stand/gnome50/inner.sh; then
        FAILED+=("$scenario")
    fi
    echo
done

echo "=== summary ==="
for scenario in "${SCENARIOS[@]}"; do
    result=ok
    for failed in "${FAILED[@]}"; do
        [ "$failed" = "$scenario" ] && result=FAILED
    done
    printf '%-18s %s\n' "$scenario" "$result"
done
[ "${#FAILED[@]}" -eq 0 ]
