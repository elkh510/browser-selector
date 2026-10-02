#!/bin/bash
# The body of every fake browser: records the launch and starts nothing.
#
#   $OUT_DIR/launch.log        name and argv, see ../launch-line.sh
#   $OUT_DIR/launch-meta.log   same line number: who started it and where
#
# The handler execs the browser, so the fake browser has the pid, the parent,
# the cgroup and the environment of the handler itself.
. "$(dirname "$(readlink -f "$0")")/../launch-line.sh"

name="$(basename "$0")"
out="${OUT_DIR:-/tmp}"

# The meta line goes first: a scenario waits for the launch line and then
# reads both
printf '%s\tpid=%s\tppid=%s\tparent=%s\tunit=%s\tchrome_desktop=%s\tdisplay=%s\n' \
    "$name" "$$" "$PPID" "$(cat "/proc/$PPID/comm" 2>/dev/null)" \
    "$(sed -n 's|^0::.*/||p' /proc/self/cgroup)" \
    "${CHROME_DESKTOP:-}" "${DISPLAY:-}" >>"$out/launch-meta.log"
launch_line "$name" "$@" >>"$out/launch.log"
