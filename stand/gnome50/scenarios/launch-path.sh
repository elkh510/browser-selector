#!/bin/bash
# The launch path of Ubuntu 26.04: xdg-open 1.2 still takes its GNOME branch
# and runs `gio open`, GLib 2.88 still starts the default handler with a
# double fork, and the handler still has the cgroup and the environment of
# the application. The OpenURI portal takes no part in it; what the handler
# sees when a link is forced through the portal is recorded at the end.
set -eu
. "$GNOME50_DIR/scenarios/_boot.sh"
boot

write_config <<'CONFIG'
[settings]
default = firefox

[browser firefox]
command = firefox
CONFIG

echo "== versions =="
echo "     $(xdg-open --version), GLib $(dpkg-query -W -f '${Version}' libglib2.0-0t64)," \
    "$(python3 --version), xdg-desktop-portal $(dpkg-query -W -f '${Version}' xdg-desktop-portal)"
echo "     XDG_CURRENT_DESKTOP=$XDG_CURRENT_DESKTOP XDG_SESSION_TYPE=$XDG_SESSION_TYPE" \
    "GNOME_DESKTOP_SESSION_ID=$GNOME_DESKTOP_SESSION_ID DESKTOP_SESSION=$DESKTOP_SESSION"

echo "== what xdg-open runs =="
before="$(launches)"
sh -x "$(command -v xdg-open)" https://example.com/trace 2>"$OUT_DIR/xdg-open.trace" || true
wait_launch $((before + 1))
grep -E '^\+ (DE=|open_|gio open)' "$OUT_DIR/xdg-open.trace" | sed 's/^/     /' || true
expect_true "xdg-open takes the GNOME branch and runs gio open" \
    grep -qxF "+ gio open https://example.com/trace" "$OUT_DIR/xdg-open.trace"
expect_launch "gio open starts the handler, the handler the default browser" \
    firefox https://example.com/trace

echo "== the same without GNOME_DESKTOP_SESSION_ID =="
# xdg-open 1.2.1 still does not read "ubuntu:GNOME": it knows GNOME by that
# variable or by org.gnome.SessionManager on the session bus. The desktop has
# both, the stand only the variable, so without it nothing says GNOME.
before="$(launches)"
env -u GNOME_DESKTOP_SESSION_ID sh -x "$(command -v xdg-open)" https://example.com/bare \
    2>"$OUT_DIR/xdg-open-bare.trace" || true
wait_launch $((before + 1))
grep -E '^\+ (dbus-send .*SessionManager|DE=|open_generic |xdg-mime query default)' \
    "$OUT_DIR/xdg-open-bare.trace" | sed 's/^/     /' || true
expect_true "XDG_CURRENT_DESKTOP=ubuntu:GNOME alone is not GNOME for xdg-open: DE=generic" \
    grep -qxF "+ DE=generic" "$OUT_DIR/xdg-open-bare.trace"
expect_false "and gio open is not run" grep -q "^+ gio open" "$OUT_DIR/xdg-open-bare.trace"
expect_launch "the generic branch still reaches the handler and the default browser" \
    firefox https://example.com/bare
echo "     handler:  $LAST_META"
if [ -n "$(meta ppid)" ] && [ "$(meta ppid)" != 1 ]; then
    pass "on that branch the handler is a child of xdg-open, no double fork: parent $(meta parent)"
else
    fail "on that branch the handler is a child of xdg-open, no double fork: parent $(meta parent)"
fi

echo "== how gio starts the handler =="
# The process calls of gio and of everything it forks: who forked whom, who
# exec'd the handler, who exited
before="$(launches)"
strace -f -s 200 -o "$OUT_DIR/gio.strace" -e trace=clone,clone3,fork,vfork,execve,exit_group \
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
grep -E 'execve\("[^"]*(gio-launch-desktop|browser-selector)"' "$OUT_DIR/gio.strace" \
    | sed -e 's/, 0x[0-9a-f]* .*//' -e 's/^/     /' || true
expect_equal "gio forks a child, the child forks the handler and exits: a double fork" \
    "double fork" "$(printf '%s\n' "$forks" | sed -n 2p)"
expect_true "the grandchild execs gio-launch-desktop, which execs the handler" \
    grep -Eq 'execve\("[^"]*/gio-launch-desktop", \[[^]]*browser-selector' "$OUT_DIR/gio.strace"

# A unit of its own for the handler would take it out of the cgroup of the
# app. With no systemd in the container that cannot be watched, so this looks
# at the library: no call to StartTransientUnit in it.
libgio="$(ldd "$(command -v gio)" | awk '/libgio-2.0/ { print $3 }')"
expect_equal "libgio has no StartTransientUnit: gio does not move what it starts into a new unit" \
    0 "$(grep -c StartTransientUnit "$libgio" || true)"

echo "== who starts the handler =="
# Every call of the OpenURI portal on the session bus, from here on
dbus-monitor --session "type='method_call',interface='org.freedesktop.portal.OpenURI'" \
    >"$OUT_DIR/portal-monitor.log" 2>&1 &
MONITOR_PID=$!
APP_PIDS="$APP_PIDS $MONITOR_PID"
sleep 1
portal_calls() { grep -c "member=OpenURI" "$OUT_DIR/portal-monitor.log" || true; }

start_app slack --instance slack --class Slack --title "Threads - Acme - Slack" \
    --unit app-slack-2382881.scope --desktop slack.desktop
click slack "Threads - Acme - Slack" https://example.com/from-slack
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

expect_unit "the handler sits in the cgroup of the app, a real one" app-slack-2382881.scope
expect_equal "the handler has the CHROME_DESKTOP of the app" slack.desktop "$(meta chrome_desktop)"
expect_equal "the handler has the DISPLAY of the session, the one of Xwayland" \
    "$DISPLAY" "$(meta display)"
sleep 1
expect_equal "the portal was running and got no OpenURI call" \
    "(true,) 0" "$(gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
        --method org.freedesktop.DBus.NameHasOwner org.freedesktop.portal.Desktop) $(portal_calls)"

echo "== for the record: a link forced through the portal =="
# xdg-open calls the portal only when it finds the marker of a flatpak. The
# marker is faked here, to see what the handler is left with on that path:
# the portal starts it, not the app.
touch "$XDG_RUNTIME_DIR/flatpak-info"
before="$(launches)"
sh -x "$(command -v xdg-open)" https://example.com/portal-trace \
    >/dev/null 2>"$OUT_DIR/xdg-open-portal.trace" || true
wait_launch $((before + 1))
grep -E '^\+ (DE=|open_|gdbus call)' "$OUT_DIR/xdg-open-portal.trace" | sed 's/^/     /' || true
app_open slack https://example.com/portal open-now
rm "$XDG_RUNTIME_DIR/flatpak-info"
expect_launch "through the portal the link still reaches the default browser" \
    firefox https://example.com/portal
echo "     handler:  $LAST_META"
sleep 1
expect_equal "both links went through OpenURI" 2 "$(portal_calls)"
portal_pid="$(gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
    --method org.freedesktop.DBus.GetConnectionUnixProcessID org.freedesktop.portal.Desktop \
    | sed 's/.*uint32 \([0-9]*\).*/\1/')"
portal_unit="$(sed -n 's|^0::.*/||p' "/proc/$portal_pid/cgroup")"
echo "     portal:   pid $portal_pid, $(cat "/proc/$portal_pid/comm"), unit $portal_unit"
expect_unit "the handler sits in the cgroup of the portal, not of the app" "$portal_unit"
expect_equal "the handler has no CHROME_DESKTOP, the one of the app is gone" "" "$(meta chrome_desktop)"

finish
