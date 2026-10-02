# browser-selector: test stand

End to end checks of the handler on the path a link really takes on the
desktop: an application runs `xdg-open URL`, xdg-open runs `gio open`, GLib
starts the default handler, the handler picks a browser. Everything runs in a
container (Ubuntu 22.04: python 3.10, xdg-utils 1.1.3, GLib 2.72, as on the
desktop) and in a throwaway home inside it. Nothing is installed, registered
or shown on the host. The contract under test is `docs/design.md` and, for
discovery, the picker, the settings window and the installer,
`docs/design-gui.md`.

    stand/
        x11/Dockerfile              the image: Xvfb, openbox, xprop, xdg-utils,
                                    gio, python3-tk, wmctrl, dbus, strace, and
                                    for the windows GTK 4.6, libadwaita 1.1,
                                    python3-gi, a font and xdotool
        x11/run.sh                  builds the image, runs the scenarios, each
                                    in a fresh container
        x11/inner.sh                inside the container: delegates a cgroup
                                    subtree, drops root, starts the scenario
        common/fake-app.py          a fake application: window class and title,
                                    cgroup, CHROME_DESKTOP, opens links with
                                    xdg-open
        common/stubs/               fake google-chrome, brave-browser, firefox,
                                    chromium (they record the launch) and a
                                    fake netbird, first in PATH
        common/launch-line.sh       the format of one line of launch.log
        common/gui.sh               for the scenarios that drive a window:
                                    wait for it, press keys, type, click
        common/scenarios/_boot.sh   shared boot: throwaway home, Xvfb and
                                    openbox, install.sh of the checkout, the
                                    handler as default browser, helpers
        common/scenarios/launch-path.sh   the stand itself: xdg-open runs gio
                                    open, gio starts the handler with a double
                                    fork, cgroup and environment are inherited
        common/scenarios/slack.sh         two workspaces of one Slack by the
                                    title of its window, two browsers
        common/scenarios/slack-state.sh   the same from root-state.json, the
                                    built-in probe @slack-workspace
        common/scenarios/clickup.sh       app id `desktop`, told apart by
                                    window class and title
        common/scenarios/netbird.sh       no window: app id from the cgroup,
                                    profile from `netbird profile list`
        common/scenarios/cloudflare.sh    a rule on the URL, from any app
        common/scenarios/focus.sh         a title rule and the focus, no
                                    DISPLAY, a dead DISPLAY
        common/scenarios/fallback.sh      unknown app, missing browser, broken
                                    config, no config, the last resort
        common/scenarios/install.sh       install.sh, the first config,
                                    --set-default, uninstall.sh and --force,
                                    a home directory with a space
        common/scenarios/discover.sh      --discover in a home with the
                                    browsers and profiles of the desktop
        common/scenarios/picker.sh        default = ask: the picker, picked
                                    with a digit, Enter and a click, closed
                                    with Esc, killed, no display
        common/scenarios/settings.sh      the settings window: Find browsers,
                                    a rule and a browser added, a regex that
                                    does not compile, the default
        common/scenarios/url-safety.sh    hostile URLs, the log, arguments
                                    that start with `-`
        out/                        logs of the last run, not in git

## Running it

    bash stand/x11/run.sh               # every scenario, about a minute
    bash stand/x11/run.sh slack.sh      # one scenario

Needs docker, version 28 or newer (see the cgroup section), and nothing else.
The first run builds the image, which pulls `ubuntu:22.04` and its packages.
`REPO=/path/to/checkout` tests another checkout with this stand.

A scenario prints one line per check:

    === slack.sh ===
    == cgroup: real, /user.slice/user-1000.slice/user@1000.service/app.slice/app-stand-runner-1.scope ==
    PASS the config of the scenario passes --check
    == workspace Acme ==
    PASS Acme goes to chrome, the profile name with a space is one argument
    ...
    == 6 passed, 0 failed ==

A `FAIL` line is followed by what was wanted and what came, a scenario with a
`FAIL` exits non-zero, and so does `run.sh`, after a summary:

    === summary ===
    clickup.sh         ok
    slack.sh           FAILED

A pass of the whole stand is `ok` on every line and exit code 0.

## What a run leaves in out/

One directory per scenario:

    scenario.log       what the scenario printed
    launch.log         one line per started browser: name and argv, tab
                       separated. A backslash, tab or newline inside an
                       argument is written as \\, \t, \n, so every tab is a
                       boundary between two arguments.
    launch-meta.log    same line numbers: pid, parent pid and parent name,
                       cgroup unit, CHROME_DESKTOP and DISPLAY of the handler
    handler.log        the log of the handler itself
    config.ini         the last config of the scenario
    app-<name>.log     stdout and stderr of a fake app, and of everything it
                       started: a traceback of the handler ends up here
    install*.log, uninstall*.log, check*.log, refused.log
    discover.out       what --discover printed, discover.sh only
    settings.log       stderr of the settings window: every change it refused
    rule.strace, ask.strace             picker.sh only: the files a click opens
    xdg-open.trace, gio.strace          launch-path.sh only
    xvfb.log, openbox.log

## How a link gets to the handler

A scenario never calls the handler with a URL. It tells a fake app to open
one, the fake app runs `xdg-open URL` as a child, and the scenario waits for
the line a fake browser writes. The handler execs the browser, so the fake
browser has the pid, the parent, the cgroup and the environment the handler
had, and writes them down.

`launch-path.sh` checks that this is the path of the desktop:

* `sh -x xdg-open` shows `DE=gnome`, `DE=gnome3`, `open_gnome3`, `gio open
  URL`. xdg-open 1.1.3 does not know `XDG_CURRENT_DESKTOP=ubuntu:GNOME`, it
  finds GNOME through `GNOME_DESKTOP_SESSION_ID`, which the session of Ubuntu
  22.04 still exports (`this-is-deprecated`). The stand sets both, plus
  `DESKTOP_SESSION=ubuntu`, as the desktop has them.
* `strace -f gio open URL` shows the double fork: gio forks a child, the child
  forks again and exits, the grandchild execs the handler (through the
  `/bin/sh -c "export GIO_LAUNCHED_DESKTOP_FILE..."` wrapper of the GLib of
  Ubuntu).
* The parent of the handler is pid 1, `docker-init`, not the fake app and not
  its xdg-open. On the desktop that place is taken by `systemd --user`.
* The handler sits in the cgroup of the fake app and has its
  `CHROME_DESKTOP`.

A few cases call the handler directly, because nothing else can: `--check` on
the config of a scenario, the arguments that start with `-` in
`url-safety.sh`, which xdg-open and gio refuse themselves, `--discover` and
`--settings`, and in `picker.sh` the two things gio hides: the exit code of a
handler whose picker was closed, and the files it opens under strace.

## The cgroup is a real one

A fake app started with `--unit app-slack-2382881.scope` makes that cgroup,
moves itself into it, and the handler reads its real `/proc/self/cgroup`:

    0::/user.slice/user-1000.slice/user@1000.service/app.slice/app-slack-2382881.scope

What it took:

* `docker run --cgroupns=private --security-opt writable-cgroups=true`. The
  second option is what Docker 28 added: the cgroup tree of the container is
  mounted read-write. No capability is added, nothing is privileged, the
  network is off (`--network none`).
* The container starts as root for one step: `inner.sh` makes
  `user.slice/user-<uid>.slice/user@<uid>.service/app.slice`, hands it to the
  stand user and moves itself into a scope there. Then it drops to that user
  with `setpriv` (no capabilities, `no_new_privs`), and everything else,
  including every fake app making its own scope, runs unprivileged.

With an older Docker, `CGROUP=file bash stand/x11/run.sh` runs the same
scenarios without real cgroups: the fake app writes the cgroup line to a file
and exports `BROWSER_SELECTOR_CGROUP_FILE`, which the handler inherits. The
header of every scenario says which mode ran, and `launch-path.sh` skips its
cgroup check in that mode.

## The fake app

    python3 fake-app.py --ctl DIR [--instance slack --class Slack --title TEXT]
                        [--unit app-slack-2382881.scope] [--desktop slack.desktop]
                        [--no-display]

Commands go into the FIFO `DIR/ctl`: `title TEXT`, `focus`, `open URL` (take
the focus, wait until `_NET_ACTIVE_WINDOW` names the window, then open),
`open-now URL` (open without the focus), `quit`. In a scenario that is
`start_app`, `app_title`, `app_focus`, `app_open` of `_boot.sh`.

## The windows

The picker and the settings window are real GTK 4 windows on the Xvfb of the
container, with `GSK_RENDERER=cairo` (no GL there) and `GTK_A11Y=none` (no
accessibility bus). `gui.sh` drives them the way a user does: xdotool sends
key presses, text and clicks through the X server, to the window that has the
focus. The window never knows it is under test, and nothing in the handler
exists for the stand.

    wait_window TITLE     waits for the window, gives it the focus, id in WINDOW
    press KEY...          2, Return, Escape, alt+f
    type_text TEXT        into the focused entry
    click_window X Y      a click at a point of WINDOW, negative from the far edge
    window_gone TITLE     true when the window is gone within 5 seconds
    wait_exit PID         exit code of a background process in EXIT_CODE

The picker is waited for instead of a browser: `click_link` of `picker.sh`
lets a fake app open the link, then waits for the window "Open link".

The settings window is driven with the keyboard only: `Alt+1` to `Alt+5`
switch the pages, every button and every field of a form has a mnemonic
(`Alt+F` Find browsers, `Alt+R` Add rule, `Alt+U` the URL field, `Alt+S`
Save), a list opens with its mnemonic and is walked with the arrow keys. What
a scenario checks is the config file, and the next click.

What is not checked on the screen: no text is read back from a window. That a
refused rule names its section and key is checked on the stderr of the window,
where the same text goes. The one click, on the last row of the picker, is
placed 40 pixels above the lower edge of the window.

## Pitfalls met on the way

* `xdg-settings set default-web-browser` of xdg-utils 1.1.3 rewrites a local
  desktop entry: it adds `text/html`, `x-scheme-handler/about` and
  `x-scheme-handler/unknown` to its `MimeType` and sleeps 4 seconds after
  each. `install.sh --set-default` therefore takes 12 seconds, and afterwards
  local HTML files and `about:` reach the handler too (`install.sh` the
  scenario shows both). The boot of the other scenarios writes
  `mimeapps.list` by hand to stay fast.
* Tk does not set `_NET_WM_PID`, and the window the window manager knows is
  not the Tk window but a wrapper around it. The fake app looks the wrapper
  up and sets the property itself.
* `WM_CLASS` of the main Tk window cannot be chosen freely. A second toplevel
  with `name=` and `class_=` can: `clickup`, `ClickUp`.
* The fake browsers are bash: their `$PPID` is the parent of the handler only
  because the handler execs them, with no fork in between.
* The docker socket needs the docker group: `permission denied` on it means
  the shell runs without the groups of the user.
* GTK aborts when its X window is destroyed under it (`xdotool windowclose`).
  A window manager does not do that, it asks the window to close: `wmctrl -c`.
* Only the shell that started a process can `wait` for it: an exit code is
  never taken inside `$(...)`.
* xdg-settings 1.1.3 takes the first word of `Exec` for the program, quote
  included. In a home directory with a space the entry is quoted, gio starts
  it, and `xdg-settings set default-web-browser` refuses it with exit code 2
  (`install.sh` the scenario shows both).

## Not covered

* Wayland. The stand is X11 only, as the desktop it models.
* GNOME Shell itself. openbox keeps `_NET_ACTIVE_WINDOW` the way mutter does,
  but focus stealing prevention and the moment the shell hands the focus to a
  browser are not modelled.
* The real applications. The class, title, unit name and state file of Slack,
  ClickUp and netbird are fixtures taken from the desktop, not the apps.
* Snap, flatpak and the portal (docs/design.md, known limits). Discovery of
  snap and flatpak browsers is covered by the unit tests, on fixtures.
* Of the settings window: editing and removing a browser or a rule, moving a
  rule, the Test and the Recent page, the row with the default browser of the
  system and its button. Their logic is covered by the unit tests, the
  widgets are not driven.
* How the windows look. A scenario checks what a window does, not its pixels.
* The focus of the picker under GNOME Shell. openbox gives a new window the
  focus, the focus stealing prevention of mutter is not modelled.

## GNOME 50

The same link path on what the desktop becomes after its upgrade: Ubuntu
26.04, GNOME Shell 50.1 on Wayland with the Xwayland of the shell. The shell
runs headless inside a container, on a virtual monitor: no window on the
display of the host, no display and no bus of the host are mounted, the
network is off, the home is a throwaway one. In the image: xdg-utils 1.2.1,
GLib 2.88.0, python 3.14.4, Xwayland 24.1.10, xdg-desktop-portal 1.21.1.

    stand/gnome50/
        Dockerfile                  the image: gnome-shell, xwayland, xprop,
                                    xdg-utils, gio, python3-tk, GTK 4, the
                                    portal, strace (972 MB)
        run.sh                      builds the image, runs the scenarios, each
                                    in a fresh container
        inner.sh                    inside the container: the cgroup subtree
                                    of x11/inner.sh, a private system bus, the
                                    session bus
        unsafe-ext/                 a shell extension that turns on unsafe
                                    mode, so org.gnome.Shell.Eval answers
        shell.py                    asks the shell through Eval: which window
                                    has the focus, give the focus to a window
        fake-app-wayland.py         the fake app as a native Wayland client
                                    (GTK 4), same FIFO commands
        scenarios/_boot.sh          common/scenarios/_boot.sh with a headless
                                    shell in place of Xvfb and openbox
        scenarios/launch-path.sh    xdg-open, gio open, the double fork, cgroup
                                    and environment, the portal
        scenarios/rules.sh          the rules that need no window
        scenarios/xprop-xwayland.sh what xprop says with an X11 window and
                                    with a Wayland window focused
        scenarios/no-xwayland.sh    a session without Xwayland
        scenarios/wayland-app.sh    a native Wayland app opens a link

    bash stand/gnome50/run.sh                      # every scenario, about 30 seconds
    bash stand/gnome50/run.sh xprop-xwayland.sh    # one scenario

Same needs, output and exit code as the X11 stand, `REPO` and `CGROUP=file`
included. The logs land in `stand/out/gnome50/<scenario>/`: the files listed
above, plus `shell.log` (the shell), `session-bus.log` (the session bus and
what it activates), `portal-monitor.log`, `xdg-open-bare.trace` and
`xdg-open-portal.trace` (launch-path.sh only).

`stand/common` is used as it is: `fake-app.py` is the X11 client (Tk under
Xwayland), the fake browsers, `launch-line.sh`, and from `_boot.sh` the home,
`install.sh`, the default browser and the helpers.

### The focus

The fake apps do not take the focus, the shell gives it: `shell.py focus
TITLE` calls `Main.activateWindow()` inside the shell and waits until
`global.display.focus_window` is that window. `shell.py focused` prints that
window: client type, the X11 window id of an X11 client, class and title.
Every `focused:` line of a scenario is such a reading, taken from the shell
and not from X11:

    focused: client=x11	id=0x600004	instance=slack	class=Slack	title=Threads - Acme - Slack
    focused: client=wayland	id=-	instance=org.gnome.TextEditor	class=org.gnome.TextEditor	title=notes.txt

### What the scenarios showed

A run of 2026-10-02: 87 checks, all PASS.

**launch-path.sh.** `xdg-open URL` still ends in `gio open`:

    + DE=gnome
    + DE=gnome3
    + open_gnome3 https://example.com/trace
    + gio open https://example.com/trace

* xdg-open 1.2.1 still does not read `XDG_CURRENT_DESKTOP=ubuntu:GNOME` (its
  `case` wants `GNOME*`). It finds GNOME through `GNOME_DESKTOP_SESSION_ID`,
  which gnome-session 50.1 still sets (the name and `this-is-deprecated` are
  in its binary), or through `org.gnome.SessionManager` on the session bus.
  With neither, as in the second trace of the scenario, it is `DE=generic`:
  `open_generic`, `xdg-mime query default x-scheme-handler/https`, and the
  handler runs as a child of xdg-open (`ppid=879 parent=sh`), without gio
  and without a double fork. The link still reaches the right browser.
* `strace -f gio open URL` shows the double fork: gio forks a child, the
  child forks again and exits, the grandchild execs
  `/usr/lib/x86_64-linux-gnu/glib-2.0/gio-launch-desktop`, which execs the
  handler (GLib 2.72 used a `/bin/sh -c` wrapper there).
* For a link of a fake app the handler has parent pid 1 (`docker-init`), the
  cgroup of the app, its `CHROME_DESKTOP`, and the `DISPLAY` of Xwayland:

      firefox	pid=1085	ppid=1	parent=docker-init	unit=app-slack-2382881.scope	chrome_desktop=slack.desktop	display=:0

* The OpenURI portal takes no part: xdg-desktop-portal is on the bus (a
  service of the shell activates it at startup) and `dbus-monitor` sees no
  call of `org.freedesktop.portal.OpenURI` for these clicks.
* `libgio-2.0.so` does not contain `StartTransientUnit`, the call to systemd
  that would move what gio starts into a unit of its own. This is a look at
  the library, the container has no systemd to watch.
* For the record, a link forced through the portal. xdg-open calls it only
  with `$XDG_RUNTIME_DIR/flatpak-info` in place (`DE=flatpak`, `open_flatpak`,
  `gdbus call ... org.freedesktop.portal.OpenURI.OpenURI`); the scenario fakes
  that file. The portal starts the handler, which then has parent pid 1, the
  cgroup of the portal (here the one of the session bus, on the desktop
  `xdg-desktop-portal.service`) and no `CHROME_DESKTOP`:

      firefox	pid=1188	ppid=1	parent=docker-init	unit=app-stand-runner-1.scope	chrome_desktop=	display=:0

**rules.sh.** With a native Wayland window focused and no X11 window
anywhere, the rules without `window` and `title` route as on X11: `app` from
the cgroup of a scope and of a service, `app` from `CHROME_DESKTOP` alone,
`probe` with a command, `@slack-workspace`, `url`, and the default browser
for an app no rule knows.

**xprop-xwayland.sh.** The config has two rules on the title of Slack, one
with the app and one without, and `firefox` as the default:

    [rule slack-acme]
    app = slack
    title = - Acme - Slack$
    browser = chrome-acme

    [rule title-alone]
    title = - Acme - Slack$
    browser = brave-title

(a) An X11 window has the focus (the Tk fake app, `slack`/`Slack`,
`Threads - Acme - Slack`). `_NET_ACTIVE_WINDOW` is the window the shell
has the focus on, the title rule fires:

    focused: client=x11	id=0x600004	instance=slack	class=Slack	title=Threads - Acme - Slack
    $ xprop -root _NET_ACTIVE_WINDOW
    _NET_ACTIVE_WINDOW(WINDOW): window id # 0x600004
    $ xprop -id 0x600004 WM_CLASS _NET_WM_NAME WM_NAME _NET_WM_PID
    WM_CLASS(STRING) = "slack", "Slack"
    _NET_WM_NAME(UTF8_STRING) = "Threads - Acme - Slack"
    WM_NAME(STRING) = "Threads - Acme - Slack"
    _NET_WM_PID(CARDINAL) = 1009
    --explain:
    window: slack, Slack
    title: Threads - Acme - Slack
    rule: slack-acme
    browser: chrome-acme

(b) A native Wayland window (GTK 4, `GdkWaylandDisplay`) gets the focus
after that. `_NET_ACTIVE_WINDOW` does not keep the Slack window. It names a
window of mutter itself, 1x1 at -100,-100, without a class or a name, so the
handler finds no window:

    focused: client=wayland	id=-	instance=org.gnome.TextEditor	class=org.gnome.TextEditor	title=notes.txt
    $ xprop -root _NET_ACTIVE_WINDOW
    _NET_ACTIVE_WINDOW(WINDOW): window id # 0x200003
    $ xprop -id 0x200003 WM_CLASS _NET_WM_NAME WM_NAME _NET_WM_PID
    WM_CLASS:  not found.
    _NET_WM_NAME:  not found.
    WM_NAME:  not found.
    _NET_WM_PID:  not found.
    $ xwininfo -id 0x200003
    xwininfo: Window id: 0x200003 (has no name)
      Absolute upper-left X:  -100
      Absolute upper-left Y:  -100
      Width: 1
      Height: 1
    --explain:
    window: -
    title: -
    rule: -
    browser: firefox

* No title rule fires on the title of the X11 window that had the focus
  before: a link of the Wayland app and a link of the unfocused Slack both go
  to `firefox`. Ten focus changes back and forth, `xprop` read right after
  each: no reading lags behind the focus.
* A second answer exists. When no X11 window had the focus since Xwayland
  came up, the property is not there at all (`_NET_ACTIVE_WINDOW:  not
  found.`). The handler finds no window then either.
* Slack itself as a native Wayland window, focused, with a title that matches
  (`general (Channel) - Acme - Slack`), the cgroup and the
  `CHROME_DESKTOP` of Slack: the title rule does not fire, the link goes to
  `firefox`. That is the contract (docs/design.md: on a Wayland session xprop
  sees Xwayland clients only), and it decides what the upgrade does to the
  `title` rules: they keep working for an app only while that app is an X11
  client.

(c) See no-xwayland.sh. With Xwayland up and an app without `DISPLAY` the
click opens the default browser as well.

**no-xwayland.sh.** The shell runs with `--no-x11`: no Xwayland process, no
socket in `/tmp/.X11-unix`, no `DISPLAY` in the shell. A focused Slack opens
a link, the handler has no `DISPLAY`, `--explain` says `window: -`, `title:
-`, the default browser opens. The same with a `DISPLAY=:0` nobody answers
on (`xprop:  unable to open display ':0'`). A rule on `app` alone still
routes.

**wayland-app.sh.** A native Wayland app is routed like an X11 one. The same
rule `app = slack` sends both to the same browser, and the handler of the
Wayland app has parent pid 1, the cgroup and the `CHROME_DESKTOP` of the app:

    google-chrome	pid=970	ppid=1	parent=docker-init	unit=app-slack-2382881.scope	chrome_desktop=slack.desktop	display=:0
    google-chrome	pid=1025	ppid=1	parent=docker-init	unit=app-slack-2390000.scope	chrome_desktop=slack.desktop	display=:0

The first line is the X11 app, the second the Wayland app. The cgroup alone
(a GNOME app without `CHROME_DESKTOP`) and `CHROME_DESKTOP` alone (Slack in
the cgroup of a browser) match as well.

### Pitfalls met on the way

* The shell starts Xwayland for the first X11 client only with the real
  cgroups of the stand, where its cgroup path looks like a unit of
  `systemd --user`. With `CGROUP=file` the path is `/` and Xwayland is
  started at boot (14 boots of 14). `xprop-xwayland.sh` skips its two checks
  on that in file mode.
* With Xwayland on demand the `xprop` of the handler can be the first X11
  client of the session. In the container it got its answer (measured by
  hand: 0.05 s for the first `xprop -root`), the handler allows 1 s.
* A headless shell comes up in the overview and stays there, and a window
  that opens under the overview gets no focus. The boot hides the overview.
* The session bus hands its own environment to what it activates, so the
  throwaway home and the fake browsers are exported before
  `dbus-run-session`. `DISPLAY`, `XAUTHORITY` and `WAYLAND_DISPLAY` the shell
  uploads itself.
* The stand takes `DISPLAY` from `Using public X11 display :0` in the log of
  the shell and `XAUTHORITY` from `$XDG_RUNTIME_DIR/.mutter-Xwaylandauth.*`.
  Without the cookie no X11 client connects. On the desktop both are in the
  environment of every app, and the handler inherits them.
* GTK 4 falls back to X11 quietly. `fake-app-wayland.py` sets
  `GDK_BACKEND=wayland` for its own start and prints the display type,
  `wayland-app.sh` checks it.
* `GIO_USE_PORTALS=1` does not send `gio open` to the portal outside a
  sandbox: gio starts the handler itself and no OpenURI call is made (tried
  by hand). Hence the faked `flatpak-info`.
* That the portal is on the bus says nothing about a click, a service of the
  shell activates it at startup. `dbus-monitor` on the OpenURI interface
  does.

### Not covered

* systemd. The container has none: the parent of the handler is the init of
  the container, the units are cgroups made by hand, and whether a unit
  started by a real `systemd --user` on 26.04 hands its cgroup to the handler
  was not watched. What speaks for it is above: fork keeps the cgroup, and
  gio has no code to leave it.
* gnome-session. It does not run in the stand: `GNOME_DESKTOP_SESSION_ID` and
  `XDG_CURRENT_DESKTOP` are set by hand to what its packages say, and
  `org.gnome.SessionManager` is not on the bus.
* The real applications. Whether Slack or ClickUp of the desktop is an X11
  or a native Wayland client after the upgrade is not tested, and that is
  what decides about their `title` rules. `sleep 5; browser-selector
  --explain` with the app focused tells: `window: -` means it is not an X11
  client.
* Snap and a real flatpak. The portal path is reached with a faked marker
  file; a snap has its own xdg-open.
* A click of a pointer, in the scenarios without a window of the handler:
  there the focus is moved by the shell, not by input.

### The picker and the settings window

The windows of `browser_selector_gui.py` under the same shell. They are native
Wayland windows, xdotool cannot reach them: `gui.sh` asks the shell where a
window is and whether it has the focus, and `shell.py keys`, `type` and
`click` send keys and clicks from a virtual keyboard and pointer of the seat.

        gui.sh                      the Wayland twin of common/gui.sh
        gui-api.py                  the GTK and libadwaita names of a source
                                    file against the installed typelibs
        scenarios/gui-api.sh        import, deprecations, criticals
        scenarios/picker.sh         common/scenarios/picker.sh plus the focus
        scenarios/startup-notify.sh the focus of the browser window, with and
                                    without StartupNotify=true
        scenarios/screenshots.sh    the PNG files

A run of 2026-10-02, all nine scenarios: 194 checks, all PASS. It ran on a
copy of the checkout taken at 12:22, before the review fixes of that day.

**gui-api.sh.** python 3.14.4, PyGObject 3.56.2, GTK 4.22.4, libadwaita 1.9.1.

* Both modules import in isolated mode with warnings as errors.
* Of the names of GTK and libadwaita the source uses, none is missing and
  none is deprecated (37 classes looked at). One hint by name,
  `.set_icon_name(`, deprecated in `Adw.ActionRow`: the call in the source is
  on an `Adw.ViewStackPage`, and the run under diagnostics does not name it.
* Picker and settings window, every page and both forms, with `python3 -W
  always` and `G_ENABLE_DIAGNOSTIC=1`: no warning, deprecation or critical
  from the tool, GTK or libadwaita. Three warnings come from PyGObject about
  itself (`GLib.unix_signal_add_full`, `asyncio.AbstractEventLoopPolicy`,
  `asyncio.get_event_loop_policy`), hidden without `-W always`.
* Icons: all there in Yaru. Adwaita 50 has no `emblem-default-symbolic` (the
  Default tab) and no `web-browser` (the desktop entry).
* The 459 unit tests pass on python 3.14 without a warning.

**picker.sh.** A click with `default = ask` shows the picker, a native
Wayland window with the app id `browser-selector`. After a real click of the
pointer into the app, a link of an X11 app and one of a native Wayland app
both give a picker that has the keyboard focus on its own
(`global.display.focus_window`), and no window asked for attention, so the
shell showed no "is ready" notification:

    picker:  client=wayland	id=-	instance=browser-selector	class=browser-selector	title=Open link	pid=1176	app=browser-selector-settings.desktop	app_name=Browser Selector	rect=420,299,440,235	focused=yes

The shell files the picker under `browser-selector-settings.desktop`, through
`StartupWMClass=browser-selector` of that entry. A digit, Enter, Down and
Enter, a click on a row start the right browser with the right argv from the
cgroup of the app, Esc and closing the window start nothing with exit code 0,
a killed picker and a missing or dead display end in the last resort, a click
a rule decides opens no file of GTK. An app without `DISPLAY` still gets the
picker, on Wayland.

**startup-notify.sh.** The browser is a fake one with a real Wayland window.
For a link of an X11 app and of a Wayland app, with a rule deciding and
through the picker: the browser window gets the focus, no window asks for
attention. With `StartupNotify=true` added to the installed
`browser-selector.desktop` it is the same, and in both cases the environment
of the browser has no `XDG_ACTIVATION_TOKEN` and no `DESKTOP_STARTUP_ID`:
`gio open` starts the handler without a launch context, so the key changes
nothing on this path.

**screenshots.sh.** `stand/out/gnome50/screenshots/`: `picker.png`,
`desktop.png` (the picker over the app), `settings-browsers.png`,
`settings-rules.png`, `settings-rule-form.png`, `settings-default.png`,
`settings-test.png`, `settings-recent.png`. Yaru icons, Ubuntu Sans, and the
browser icons of Papirus copied into the hicolor of the throwaway home, where
the packages of the browsers would put theirs. The settings window is a
Wayland window with the app id `browser-selector`, and the shell takes it for
the app of `browser-selector-settings.desktop`.

Found on the way, not asserted by a scenario:

* Picking the default in the settings window prints a GLib critical,
  `g_object_notify_by_pspec: assertion 'G_IS_OBJECT (object)' failed`, here
  and in `stand/out/settings/settings.log` of the X11 stand. `default_picked`
  runs inside `notify::selected` of the `Adw.ComboRow` and ends in `fill()`,
  which replaces the model of that very row. With the change put off through
  `GLib.idle_add` the critical was gone, 3 runs of 3 against 3 of 3 with it.
* On the Test page the Answer group is cut by the status row at the default
  size of the window, and the lines of Recent do not wrap
  (`settings-test.png`, `settings-recent.png`).

Pitfalls:

* A headless shell has no keyboard and no pointer. A fresh virtual pointer
  sits at 0,0, the hot corner, and its first motion lands at 1200,0 instead
  of 1200,760: that opens the overview, and under the overview no window
  gets the focus or a key. `start_gui` turns the hot corner off and moves the
  pointer twice.
* Two windows of the stand overlap in the middle of the screen: a click of
  the pointer goes to the one on top, so the shell raises the window first.
* The shell reads a new desktop entry a moment after `install.sh`: until
  then the first window of the handler has no app.

Not covered: driving the settings window (Find browsers, a rule added in the
window, the refusal of a bad regex), that is in the X11 stand only.
