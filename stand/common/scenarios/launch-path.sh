#!/bin/bash
# Checks the stand itself: a link travels the way it does on the desktop.
# xdg-open takes its GNOME branch and runs `gio open`, GLib starts the default
# handler with a double fork, so the application is not the parent of the
# handler, and the handler still has the cgroup and the environment of the
# application.
set -eu
. "$(dirname "$(readlink -f "$0")")/_boot.sh"
boot

write_config <<'EOF'
[settings]
default = firefox

[browser firefox]
command = firefox
EOF

echo "== what xdg-open runs =="
before="$(launches)"
sh -x "$(command -v xdg-open)" https://example.com/trace 2>"$OUT_DIR/xdg-open.trace" || true
wait_launch $((before + 1))
grep -E '^\+ (DE=|open_|gio open)' "$OUT_DIR/xdg-open.trace" | sed 's/^/     /' || true
expect_true "xdg-open takes the GNOME branch and runs gio open" \
    grep -qxF "+ gio open https://example.com/trace" "$OUT_DIR/xdg-open.trace"
expect_launch "gio open starts the handler, the handler the default browser" \
    firefox https://example.com/trace

echo "== how gio starts the handler =="
# The process calls of gio and of everything it forks: who forked whom, who
# exec'd the handler, who exited
before="$(launches)"
strace -f -o "$OUT_DIR/gio.strace" -e trace=clone,clone3,fork,vfork,execve,exit_group \
    gio open https://example.com/strace || true
wait_launch $((before + 1))
expect_launch "gio open under strace starts the default browser" firefox https://example.com/strace
forks="$(awk -v handler="execve(\"$HANDLER\"" '
    NR == 1 { gio = $1 }
    /clone|fork/ && / = [0-9]+$/ { parent[$NF] = $1; if (/CLONE_THREAD/) thread[$NF] = 1 }
    index($0, handler) && !h { h = $1 }
    /exit_group|\+\+\+ exited/ { gone[$1] = 1 }
    END {
        middle = parent[h]
        # Up from the middle process to gio itself, past the thread that forked
        top = parent[middle]
        while (top in thread) top = parent[top]
        print "gio=" gio, "middle=" middle, "handler=" h
        if (h && middle && middle != gio && !(middle in thread) && top == gio && (middle in gone))
            print "double fork"
    }' "$OUT_DIR/gio.strace")"
echo "     $(printf '%s\n' "$forks" | head -n 1)"
expect_equal "gio forks a child, the child forks the handler and exits: a double fork" \
    "double fork" "$(printf '%s\n' "$forks" | sed -n 2p)"

echo "== who starts the handler =="
start_app slack --instance slack --class Slack --title "Threads - Acme - Slack" \
    --unit app-slack-2382881.scope --desktop slack.desktop
app_open slack https://example.com/from-slack
expect_launch "a link of the fake app reaches a browser" firefox https://example.com/from-slack
echo "     fake app: pid $(app_pid slack), $LAST_EVENT"
echo "     handler:  $LAST_META"

# The fake browser was exec'd by the handler: its parent is the parent of the
# handler. On the desktop that is systemd --user, here the init of the
# container.
parent="$(meta ppid)"
xdg_open="$(printf '%s\n' "$LAST_EVENT" | sed -n 's/.*xdg_open_pid=//p')"
if [ -n "$parent" ] && [ "$parent" != "$(app_pid slack)" ] && [ "$parent" != "$xdg_open" ]; then
    pass "the parent of the handler is not the app: pid $parent ($(meta parent))"
else
    fail "the parent of the handler is not the app: pid $parent ($(meta parent))"
fi
expect_equal "the handler is adopted by init, the double fork of GLib" 1 "$parent"

if [ "$CGROUP_MODE" = real ]; then
    expect_equal "the handler sits in the cgroup of the app, a real one" \
        app-slack-2382881.scope "$(meta unit)"
else
    echo "SKIP the handler sits in the cgroup of the app: CGROUP=file, no real cgroups"
fi
expect_equal "the handler has the CHROME_DESKTOP of the app" slack.desktop "$(meta chrome_desktop)"

finish
