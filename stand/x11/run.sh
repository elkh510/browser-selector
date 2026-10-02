#!/bin/bash
# Runs the scenarios of the stand, each one in a fresh container.
#
#   bash stand/x11/run.sh [scenario.sh|all]   scenario from common/scenarios,
#                                             all of them by default
#
# Exits non-zero when a scenario failed. The handler under test is taken from
# REPO (default: the checkout this stand lives in), mounted read-only and
# installed into a throwaway home inside the container. Nothing is installed,
# registered or shown on the host; the logs land in stand/out/<scenario>/.
#
#   CGROUP=file bash stand/x11/run.sh ...     for a Docker older than 28: no
#                                             real cgroups, the unit name goes
#                                             through BROWSER_SELECTOR_CGROUP_FILE
set -eu

STAND_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
REPO="${REPO:-$(cd "$STAND_DIR/.." && pwd)}"
IMAGE="${IMAGE:-browser-selector-stand:x11}"
OUT="${OUT:-$STAND_DIR/out}"
CGROUP="${CGROUP:-real}"
WHAT="${1:-all}"

if [ "$WHAT" = all ]; then
    SCENARIOS=()
    for file in "$STAND_DIR"/common/scenarios/*.sh; do
        name="$(basename "$file")"
        [ "$name" = _boot.sh ] || SCENARIOS+=("$name")
    done
else
    SCENARIOS=("$(basename "$WHAT")")
    if [ ! -f "$STAND_DIR/common/scenarios/${SCENARIOS[0]}" ]; then
        echo "no scenario ${SCENARIOS[0]} in $STAND_DIR/common/scenarios" >&2
        exit 2
    fi
fi

# Docker turns a missing bind mount source into a directory owned by root
mkdir -p "$OUT"

docker build -q -t "$IMAGE" --build-arg "UID=$(id -u)" "$STAND_DIR/x11" >/dev/null

# The fake apps sit in cgroups named like the units of real apps, so the
# container needs a cgroup tree it can write to. A private cgroup namespace
# plus writable-cgroups (Docker 28 and up) is all it takes: no capability is
# added and nothing is privileged.
CGROUP_ARGS=()
if [ "$CGROUP" = real ]; then
    CGROUP_ARGS=(--cgroupns=private --security-opt writable-cgroups=true)
fi

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
            bash /stand/x11/inner.sh; then
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
