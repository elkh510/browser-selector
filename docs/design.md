# Design

_verified: 2026-10-05_

`browser-selector` is registered as the default web browser. For every link
it looks at where the link came from and starts the browser and profile the
first matching rule names.

Python 3.10 or newer, the handler is stdlib only. No daemon, no GNOME Shell
extension. Discovery of browsers, the picker and the settings window are in
[design-gui.md](design-gui.md).

## Layout

    browser_selector.py        the handler and everything without a window
    browser_selector_gui.py    picker and settings window
    browser-selector.desktop   the one desktop entry: default browser and app grid icon
    config.example.ini         example rules
    install.sh, uninstall.sh
    packaging/                 the .deb: build-deb.sh, inner.sh, launcher, Dockerfile
    tests/                     unit tests (unittest)
    stand/                     end to end stands, see stand/README.md
    docs/

## Command line

    browser-selector [--config PATH] URL             pick a browser and exec it
    browser-selector [--config PATH] --explain [URL] print what it sees and what
                                                     it would run, start nothing
    browser-selector [--config PATH] --check         validate the config
    browser-selector [--config PATH] [--settings]    the settings window: a start
                                                     without a URL is one too
    browser-selector --discover                      print the browsers and
                                                     profiles found, change nothing
    browser-selector [--config PATH] --init-config   write a first config from
                                                     discovery when there is none
    browser-selector --version

Exit codes: 0 fine, 2 the config is not valid (`--check` only), 1 nothing
could be started.

An argument that is empty or, leading whitespace aside, starts with `-` and
is not one of the options above is refused. It is never passed on to a
browser: Chromium trims whitespace before it looks for a switch.

The config is `--config`, else `$BROWSER_SELECTOR_CONFIG`, else
`${XDG_CONFIG_HOME:-~/.config}/browser-selector/config.ini`.

Every decision is appended to
`${XDG_STATE_HOME:-~/.local/state}/browser-selector/log` as one line: time,
rule, browser, app ids, scheme and host of the URL. Never the full URL, login
links carry tokens. Characters that do not print are replaced, a URL or a
unit name cannot forge a line. The file is mode 0600 in a 0700 directory, it
lists every host visited. Past 1 MiB it is renamed to `log.1`.

## What a rule can look at

    url      the argument
    app      who opened the link, see below
    window   class of the focused window
    title    title of the focused window
    probe    output of a command

### app

The handler is started through `xdg-open` -> `gio open`, and GLib launches it
with a double fork: its parent is `systemd --user`, the parent chain says
nothing. Two things do survive:

* the cgroup. The handler stays in the unit of the caller, the last path
  component of `/proc/self/cgroup`: `app-slack-2382881.scope`,
  `app-gnome-netbird-14016.scope`, `warp-taskbar.service`.
  The app id is that name without the `app-` prefix, an optional `gnome-`
  after it, a trailing `-<digits>` and the `.scope` or `.service` suffix,
  with the `\xNN` escapes of systemd decoded: `slack`, `netbird`,
  `warp-taskbar`, `com.microsoft.VSCode`. The instance of a template unit is
  dropped (`app-slack@autostart.service` is `slack`, that is what an
  autostarted app gets), and so is the `flatpak-` prefix;
* the environment. Chromium and Electron apps export `CHROME_DESKTOP`
  (`slack.desktop`), the app id is the value without `.desktop`.

Both ids are candidates, a rule matches when either does. The file read for
the cgroup is `$BROWSER_SELECTOR_CGROUP_FILE` when set, for the tests and the
stand.

### window and title

Read with `xprop` (run with `LC_ALL=C.UTF-8`, timeout 1 s):

    xprop -root _NET_ACTIVE_WINDOW
    xprop -id <id> WM_CLASS _NET_WM_NAME WM_NAME _NET_WM_PID

No `DISPLAY`, no `xprop`, no active window or a window without a class: there
is no window, and every rule with `window` or `title` does not match. On a
Wayland session this sees Xwayland clients only.

The window is read at most once per run and only when a rule that needs it
has passed its cheaper conditions.

### probe

`probe` is a command line (split with `shlex`, no shell), `probe_match` a
regex for its stdout. Timeout `probe_timeout` seconds, default 2, at most 30.
A probe that fails, times out or is not found does not match. At most 64 KiB
of its output are read, then it is killed. The same probe runs once per run.

Built in, no process started:

    @slack-workspace   name of the selected workspace of the Slack desktop app,
                       from ${XDG_CONFIG_HOME:-~/.config}/Slack/storage/root-state.json
                       (workspaces[workspacesMeta.selectedWorkspaceId].name)

## Config

INI, read with `configparser` (no interpolation, `;` and `#` comments, case
sensitive keys). Sections in file order:

    [settings]
    default = chrome-main
    probe_timeout = 2

    [browser chrome-main]
    command = google-chrome --profile-directory="Profile 6"

    [browser brave-globex]
    command = brave-browser --profile-directory=Default {url}

    [rule slack-acme]
    app = slack
    title = - Acme - Slack$
    browser = chrome-main

    [rule netbird-globex]
    app = netbird
    probe = netbird profile list
    probe_match = ^globex\s+✓
    browser = brave-globex

    [rule cloudflare-acme]
    url = ^https://acme\.cloudflareaccess\.com/
    browser = chrome-main

* `[settings] default` names the browser for everything no rule matches.
  Required.
* `[browser NAME] command` is split with `shlex`. `{url}` inside an argument
  is replaced by the URL, without it the URL is appended as the last
  argument. No shell is involved at any point. `name` and `icon` are
  optional, for the picker and the settings window.
* `ask` in place of a browser name, in `default` or in a rule, shows the
  picker. It cannot be a section.
* `[rule NAME]`: `browser` is required, every condition is optional, all
  given conditions must hold, the first matching rule wins. A rule without
  conditions matches everything.
* `app` and `window`: regex, case insensitive, must match a whole candidate
  (`re.fullmatch`). Candidates of `window` are both parts of `WM_CLASS`.
* `title`, `url`, `probe_match`: regex, case sensitive, `re.search`,
  `probe_match` with `re.MULTILINE`.
* `probe` and `probe_match` come together.

Not valid, reported by `--check` with the section and the key: an unknown
section or key, two sections whose names differ only in spacing, a missing
`default`, `command` or `browser`, a browser that is not defined, a regex
that does not compile, `probe` without `probe_match` or the other way round,
a `probe_timeout` outside 0 to 30, a control character in a name or a value,
a command whose program is `xdg-open`, `gio`, `gnome-open`,
`sensible-browser` or the handler itself (that would loop).

## A click always opens something

    no config file           the last resort
    config not valid         the error goes to the log, then the last resort
    window or probe fails    that condition is false, the next rule is tried
    program not found        the default browser, then the last resort
    anything unexpected      the error goes to the log, then the last resort

The last resort is the first of `google-chrome`, `brave-browser`, `firefox`,
`chromium` found in `PATH`, started with the URL alone.

The browser is started with `os.execvp`, the handler does not stay around.

A browser command must not lead back to the handler. `--check` refuses the
obvious ones by name and by the real path of the program. A wrapper script
cannot be seen through, so the handler also leaves
`BROWSER_SELECTOR_GUARD=<time>` in the environment of what it starts: a
handler that finds a value younger than 5 seconds was started by itself and
goes to the last resort.

## --explain

Plain `key: value` lines, the window is always read here:

    url: https://example.com/x
    unit: app-slack-2382881.scope
    app: slack
    window: slack, Slack
    title: Threads - Acme - Slack
    probe @slack-workspace: Acme
    rule: slack-acme
    browser: chrome-main
    command: google-chrome '--profile-directory=Profile 6' https://example.com/x

`app` lists all candidates separated by `, `. `window` and `title` are `-`
when there is no window. A `probe` line is printed for every probe that ran.
`rule` is `-` when the default was used. `command` is printed with
`shlex.join`. Without a URL the `url`, `rule`, `browser` and `command` lines
are left out.

## Install

`install.sh` works in the home of the caller and touches nothing else. What
goes where is in [design-gui.md](design-gui.md).

It does not change the default browser. It prints the two commands for it:
the switch and the way back. `install.sh --set-default` does the switch and
writes the previous default to
`${XDG_STATE_HOME:-~/.local/state}/browser-selector/previous-default`.

`uninstall.sh` puts the previous default back when the handler is the
default, removes what was installed and leaves the config and the log.

## Known limits

* A Slack that was started by a `slack://` link from a browser lives in the
  cgroup of that browser. `CHROME_DESKTOP` still says `slack`.
* The focused window is read after the click. A page an app opens on its own
  (a VPN login) has nothing to do with it: such rules use `app`, `url` and
  `probe`, not `title`.
* Snap and flatpak apps open links through the portal, the handler then sits
  in the cgroup of the portal. Only `window` and `title` tell them apart.
* The default browser of the system also gets local HTML files (as a bare
  path), `about:` and unknown schemes: `xdg-settings` registers the entry for
  `text/html`, `x-scheme-handler/about` and `x-scheme-handler/unknown` too.
  The handler passes them on like a link. Schemes with a handler of their own
  (`slack://`, `com.cloudflare.warp://`) never reach it.
